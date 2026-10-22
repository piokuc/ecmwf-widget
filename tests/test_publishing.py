"""The publishing daemon: pulling on the ECMWF schedule and pushing to git."""

from __future__ import annotations

import datetime as dt
import subprocess

import pytest

from ecmwf_widget import auto_publish
from ecmwf_widget.scheduler import DEFAULT_DELAY, cycle_times, next_expected


# -- the schedule ------------------------------------------------------------ #

def test_wait_until_sleeps_in_slices_and_never_past_the_deadline():
    """The deadline comes from the wall clock, not from one long sleep."""
    class Clock:
        def __init__(self, start):
            self.moment = start

        def now(self):
            return self.moment

        def advance(self, seconds):
            self.moment += dt.timedelta(seconds=seconds)

    # Eleven minutes to the deadline, and the clock advances by exactly
    # what sleep was told: a machine that wakes late with the deadline in
    # the past returns without sleeping.
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        clock.advance(seconds)

    clock = Clock(dt.datetime(2026, 10, 22, 2, 29))
    deadline = dt.datetime(2026, 10, 22, 2, 40)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(auto_publish.time, "sleep", fake_sleep)
        auto_publish._wait_until(deadline, now=clock.now)

    # Sixty second slices, one six-second tail, never past the deadline.
    assert all(seconds <= 60 for seconds in sleeps)
    assert sleeps[-1] <= 60
    assert clock.now() >= deadline


def test_wait_until_already_past_returns_at_once():
    sleeps = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(auto_publish.time, "sleep", lambda s: sleeps.append(s))
        auto_publish._wait_until(dt.datetime(2026, 10, 22, 2, 40, tzinfo=dt.UTC))
    assert sleeps == []


def test_delay_is_the_default_schedule():
    assert DEFAULT_DELAY == dt.timedelta(hours=8, minutes=40)


def test_cycle_times_span_now():
    now = dt.datetime(2026, 10, 21, 9, 40)
    times = cycle_times(now)
    past = [t for t in times if t <= now]
    future = [t for t in times if t > now]
    assert past and future
    assert past[-1] == dt.datetime(2026, 10, 21, 6, 0)
    assert future[0] == dt.datetime(2026, 10, 21, 12, 0)


def test_next_expected_is_always_after_now():
    for hour in range(0, 24):
        now = dt.datetime(2026, 10, 21, hour, 7)
        expected = next_expected(now, DEFAULT_DELAY)
        assert expected > now
        # and it is some cycle plus the delay
        base = expected - DEFAULT_DELAY
        assert base.hour % 6 == 0 and base.minute == 0


# -- the git publish step ------------------------------------------------------- #

@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repository with an empty bare remote, and cwd switched into it."""
    work = tmp_path / "work"
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", "--initial-branch=main", str(remote)], check=True
    )
    work.mkdir()

    def git(*args, cwd=work):
        return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)

    git("init", "-q", "--initial-branch=main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    git("remote", "add", "origin", str(remote))
    monkeypatch.chdir(work)
    return work, remote, git


def _commit_baseline(work, remote, git, index_html="<html/>"):
    (work / "index.html").write_text(index_html)
    git("add", "index.html")
    git("commit", "-q", "-m", "seed")
    git("push", "-q", "-u", "origin", "main")


def test_publish_with_nothing_changed_is_a_noop(repo, monkeypatch):
    work, remote, git = repo
    _commit_baseline(work, remote, git)
    monkeypatch.setattr(
        auto_publish.build_site, "build", lambda *a, **kw: {"file": "x", "size": 0}
    )
    assert auto_publish.publish(str(work), "places.yml", dry_run=False, max_places=None) is False


def test_publish_in_dry_run_builds_but_does_not_push(repo, monkeypatch):
    work, remote, git = repo
    _commit_baseline(work, remote, git)
    called = []

    def fake_build(out_dir, config_path, max_places):
        (work / "index.html").write_text("<html>new</html>")
        called.append(out_dir)
        return {"file": str(work / "index.html"), "size": 14}

    monkeypatch.setattr(auto_publish.build_site, "build", fake_build)

    assert auto_publish.publish(str(work), "places.yml", dry_run=True, max_places=None) is False
    assert called == [str(work)]
    # the change is in the working tree but no commit was made
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=work, capture_output=True, text=True, check=True
    ).stdout
    assert " M index.html" in status
    commit = subprocess.run(
        ["git", "log", "--oneline", "-1"], cwd=work, capture_output=True, text=True, check=True
    ).stdout
    assert "seed" in commit


def test_publish_commits_a_gitignored_page(repo, monkeypatch):
    """The built page is in .gitignore; the daemon must push it anyway."""
    work, remote, git = repo
    _commit_baseline(work, remote, git)
    (work / ".gitignore").write_text("index.html\nlatest.json\n")
    git("add", ".gitignore")
    git("commit", "-q", "-m", "ignore the built page")

    def fake_build(out_dir, config_path, max_places):
        (work / "latest.json").write_text('{"updated": "now"}')
        return {"file": str(work / "latest.json"), "size": 20}

    monkeypatch.setattr(auto_publish.build_site, "build", fake_build)
    assert auto_publish.publish(str(work), "places.yml", dry_run=False, max_places=None) is True

    head = subprocess.run(
        ["git", "--git-dir", str(remote), "show", "--name-only", "--format=", "main"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "latest.json" in head


def test_publish_commits_and_pushes_a_new_version(repo, monkeypatch):
    work, remote, git = repo
    _commit_baseline(work, remote, git)

    def fake_build(out_dir, config_path, max_places):
        (work / "index.html").write_text("<html>newer</html>")
        return {"file": str(work / "index.html"), "size": 16}

    monkeypatch.setattr(auto_publish.build_site, "build", fake_build)
    assert auto_publish.publish(str(work), "places.yml", dry_run=False, max_places=None) is True

    head = subprocess.run(
        ["git", "--git-dir", str(remote), "log", "--oneline", "-1", "main"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "Update the forecast" in head


def test_publish_survives_a_failing_commit(repo, monkeypatch):
    work, remote, git = repo
    _commit_baseline(work, remote, git)

    def fake_build(out_dir, config_path, max_places):
        (work / "index.html").write_text("<html>changed but broken</html>")
        return {"file": str(work / "index.html"), "size": 24}

    monkeypatch.setattr(auto_publish.build_site, "build", fake_build)

    def broken_git(*args):
        if args[0] == "commit":
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="nothing to commit?")
        if args[0] == "add":
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[0] == "status":
            return subprocess.CompletedProcess(args, 0, stdout=" M index.html\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(auto_publish, "run_git", broken_git)
    assert auto_publish.publish(str(work), "places.yml", dry_run=False, max_places=None) is False
