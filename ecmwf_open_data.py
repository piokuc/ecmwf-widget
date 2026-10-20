"""Download ECMWF IFS 0.1 deg (~9 km) free & open forecast data.

Since 20 October 2026 ECMWF publishes a subset of its highest-resolution IFS
forecast at 0.1 deg (about 9 km) alongside the long-standing 0.25 deg tier.

Access model
------------
No registration, no API key, no login. Every endpoint used here is anonymous
HTTP(S) GET. The data is licensed CC-BY-4.0, so it may be redistributed and
used commercially, but ECMWF must be attributed.

Caveats that matter when you plan a download:

* The 0.1 deg tier is published roughly 2 hours after the 0.25 deg tier, so the
  newest run available here is usually one cycle behind the 0.25 deg data.
* Only the last 12 forecast runs are retained (a rolling archive of about
  2-3 days). For the full historical archive you need a service agreement.
* Each run is split into one ``-sfc`` and one ``-pl`` file per forecast step.
  A single pressure-level file is ~370 MB, so pulling whole files to grab a
  couple of parameters is wasteful. This module reads the companion ``.index``
  file and uses HTTP range requests to fetch only the byte ranges you asked
  for.
* The portal limits concurrent connections (500-2000). Cloud mirrors
  (AWS / Google / Azure) hold identical data and are useful as fallbacks.

Typical use::

    from ecmwf_open_data import download, latest_run

    run = latest_run()                       # (date, time) of newest 0.1 deg run
    download(run[0], run[1], param=["2t", "msl"], step=[24, 48], out="data")

Or use the ``ecmwf-opendata`` package, which already speaks this protocol::

    from ecmwf.opendata import Client
    Client(source="ecmwf", model="ifs", resol="0p1").retrieve(
        date="20261020", time="06", step=[24], param=["2t"], levtype="sfc"
    )
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import re
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor

import requests
import urllib3

__all__ = [
    "SOURCES",
    "IndexEntry",
    "OpenDataError",
    "authorize_url",
    "build_index_url",
    "build_url",
    "download",
    "download_step",
    "fetch_index",
    "latest_run",
    "select_entries",
]


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

#: Base URL of each mirror. All are anonymous; none require credentials.
SOURCES: dict[str, str] = {
    "ecmwf": "https://data.ecmwf.int/forecasts",
    "aws": "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com",
    "google": "https://storage.googleapis.com/ecmwf-open-data",
    "azure": "https://ai4edataeuwest.blob.core.windows.net/ecmwf",
}

#: Mirrors that accept a multi-range request (several byte ranges in one HTTP
#: call). The ECMWF portal does; S3, Google Cloud Storage and Azure Blob
#: ignore the header and return the whole object, so they must be asked for
#: one range at a time.
MULTI_RANGE_SOURCES = {"ecmwf"}

#: Azure Blob requires a read-only SAS token. It is issued publicly, so this
#: is still no registration, but the token has to be fetched once per session.
AZURE_SAS_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token/ai4edataeuwest/ecmwf"

#: Lev types are grouped into the files published for a run.
#: Soil-level fields travel inside the surface file.
LEVFILE = {"sfc": "sfc", "sol": "sfc", "pl": "pl"}

#: Filesystem-safe representation of a lev type.
LEVSUFFIX = {"sfc": "sfc", "sol": "sfc", "pl": "pl"}

#: ECMWF requires attribution for CC-BY-4.0 data.
ATTRIBUTION = (
    "Generated using ECMWF free and open data "
    "(https://www.ecmwf.int/en/forecasts/datasets/open-data), "
    "licensed under CC-BY-4.0."
)

USER_AGENT = "ecmwf-open-data-downloader/1.0 (+https://www.ecmwf.int/en/forecasts/datasets/open-data)"


class OpenDataError(RuntimeError):
    """Raised when data cannot be located or retrieved."""


# --------------------------------------------------------------------------- #
# URL construction
# --------------------------------------------------------------------------- #


def _normalise_run(date: str | dt.date | dt.datetime, time: str | int | None = None) -> tuple[str, str]:
    """Return the ``(yyyymmdd, HH)`` pair identifying a forecast run."""
    if isinstance(date, dt.datetime):
        date, time = date.strftime("%Y%m%d"), date.strftime("%H")
    elif isinstance(date, dt.date):
        date = date.strftime("%Y%m%d")

    date = str(date).replace("-", "")
    if not re.fullmatch(r"\d{8}", date):
        raise ValueError(f"date must be YYYYMMDD, got {date!r}")

    if time is None:
        time = "00"
    time = f"{int(time):02d}"
    if time not in {"00", "06", "12", "18"}:
        raise ValueError(f"time must be one of 00/06/12/18, got {time!r}")
    return date, time


def build_url(
    source: str,
    date: str | dt.date,
    time: str | int,
    step: int,
    *,
    model: str = "ifs",
    resol: str = "0p1",
    stream: str = "oper",
    type: str = "fc",
    levtype: str = "sfc",
    extension: str = "grib2",
) -> str:
    """Build the URL of one GRIB2 file.

    The layout is::

        {base}/{yyyymmdd}/{HH}z/{model}/{resol}/{stream}/
            {yyyymmddHH}0000-{step}h-{stream}-{type}{-levfile}.{ext}

    At 0.1 deg the surface and pressure-level fields live in separate files,
    which is why ``levfile`` is part of the name. At 0.25 deg the two are
    combined and ``levfile`` is empty.
    """
    date, time = _normalise_run(date, time)
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}, choose from {sorted(SOURCES)}")
    if levtype not in LEVFILE:
        raise ValueError(f"unknown levtype {levtype!r}, choose from {sorted(LEVFILE)}")

    levfile = LEVFILE[levtype]
    suffix = f"-{levfile}" if resol == "0p1" else ""
    name = f"{date}{time}0000-{step}h-{stream}-{type}{suffix}.{extension}"
    return f"{SOURCES[source]}/{date}/{time}z/{model}/{resol}/{stream}/{name}"



def build_index_url(*args, **kwargs) -> str:
    """URL of the ``.index`` companion of a GRIB2 file."""
    kwargs["extension"] = "index"
    return build_url(*args, **kwargs)


# --------------------------------------------------------------------------- #
# Index handling
# --------------------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True)
class IndexEntry:
    """One GRIB message inside a file, located by its byte range."""

    param: str
    levtype: str
    levelist: str | None
    step: str
    offset: int
    length: int
    date: str = ""
    time: str = ""
    stream: str = ""
    type: str = ""
    number: str = ""

    @property
    def end(self) -> int:
        """Inclusive last byte of the message."""
        return self.offset + self.length - 1

    @property
    def level(self) -> int | None:
        try:
            return int(self.levelist)
        except (TypeError, ValueError):
            return None


def _session(retries: int = 5, backoff: float = 1.0) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    retry = urllib3.util.retry.Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = requests.adapters.HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _get(
    session: requests.Session,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    retries: int = 4,
    backoff: float = 2.0,
    timeout: float = 300,
) -> requests.Response:
    """GET with a retry loop for the transient errors the mirrors produce.

    S3 in particular answers with ``503 SlowDown`` when it is being hammered.
    """
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.get(url, headers=headers or {}, timeout=timeout)
            if response.status_code in (429, 500, 502, 503, 504):
                last_error = OpenDataError(f"HTTP {response.status_code} for {url}")
                if attempt < retries - 1:
                    time.sleep(backoff * (2**attempt))
                    continue
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt == retries - 1:
                raise OpenDataError(f"failed to fetch {url}: {exc}") from exc
            time.sleep(backoff * (2**attempt))
    raise OpenDataError(f"failed to fetch {url}: {last_error}")


def _azure_token(session: requests.Session) -> str:
    """Fetch a read-only SAS token for the Azure mirror."""
    response = _get(session, AZURE_SAS_URL, retries=3, timeout=30)
    response.raise_for_status()
    return response.json()["token"]


def _source_of(url: str) -> str | None:
    """Return the mirror name a URL belongs to."""
    for name, base in SOURCES.items():
        if url.startswith(base):
            return name
    return None


def _supports_multi_range(url: str) -> bool:
    """Whether the mirror serving ``url`` handles multi-range requests."""
    source = _source_of(url)
    return bool(source) and source in MULTI_RANGE_SOURCES


def authorize_url(
    url: str,
    source: str,
    session: requests.Session,
    token_cache: dict[str, str] | None = None,
) -> str:
    """Add the Azure SAS token when the Azure mirror is used."""
    if source != "azure":
        return url
    token_cache = {} if token_cache is None else token_cache
    if "token" not in token_cache:
        token_cache["token"] = _azure_token(session)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{token_cache['token']}"


def fetch_index(
    url: str,
    *,
    session: requests.Session | None = None,
    retries: int = 3,
    backoff: float = 2.0,
) -> list[IndexEntry]:
    """Download and parse an ECMWF ``.index`` file.

    The index is JSON-lines; each line describes one GRIB message with its
    ``_offset`` and ``_length`` inside the parent file.
    """
    session = session or _session()
    last_error: Exception | None = None

    for attempt in range(retries):
        try:
            response = _get(session, url, retries=1, timeout=60)
            if response.status_code == 404:
                raise OpenDataError(f"no such index file: {url}")
            response.raise_for_status()
            break
        except OpenDataError:
            raise
        except requests.RequestException as exc:
            last_error = exc
            if attempt == retries - 1:
                raise OpenDataError(f"failed to fetch index {url}: {exc}") from exc
            time.sleep(backoff * (2**attempt))
    else:  # pragma: no cover - loop always breaks or raises
        raise OpenDataError(f"failed to fetch index {url}: {last_error}")

    entries: list[IndexEntry] = []
    for line in response.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OpenDataError(f"malformed index line in {url}: {line[:120]}") from exc
        entries.append(
            IndexEntry(
                param=raw.get("param", ""),
                levtype=raw.get("levtype", ""),
                levelist=raw.get("levelist"),
                step=str(raw.get("step", "")),
                offset=int(raw["_offset"]),
                length=int(raw["_length"]),
                date=str(raw.get("date", "")),
                time=str(raw.get("time", "")),
                stream=str(raw.get("stream", "")),
                type=str(raw.get("type", "")),
                number=str(raw.get("number", "") or ""),
            )
        )
    return entries


def select_entries(
    entries: Iterable[IndexEntry],
    *,
    param: Sequence[str] | None = None,
    levelist: Sequence[int | str] | None = None,
    levtype: Sequence[str] | None = None,
    number: Sequence[int | str] | None = None,
) -> list[IndexEntry]:
    """Filter index entries by parameter, level, level type and member."""
    wanted_params = {p.lower() for p in param} if param else None
    wanted_levels = {str(lvl) for lvl in levelist} if levelist else None
    wanted_levtypes = {lt.lower() for lt in levtype} if levtype else None
    wanted_numbers = {str(n) for n in number} if number else None

    selected = []
    for entry in entries:
        if wanted_params is not None and entry.param.lower() not in wanted_params:
            continue
        if wanted_levels is not None and str(entry.levelist) not in wanted_levels:
            continue
        if wanted_levtypes is not None and entry.levtype.lower() not in wanted_levtypes:
            continue
        if wanted_numbers is not None and entry.number not in wanted_numbers:
            continue
        selected.append(entry)
    return selected


def merge_ranges(entries: Sequence[IndexEntry]) -> list[tuple[int, int]]:
    """Collapse selected messages into the fewest contiguous byte ranges.

    Adjacent GRIB messages are stored back to back, so a run of them can be
    pulled with a single range request.
    """
    ranges: list[tuple[int, int]] = []
    for entry in sorted(entries, key=lambda e: e.offset):
        start, end = entry.offset, entry.end
        if ranges and start <= ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))
    return ranges


# --------------------------------------------------------------------------- #
# Range fetching
# --------------------------------------------------------------------------- #


def _parse_multipart(body: bytes, boundary: bytes) -> list[bytes]:
    """Split a ``multipart/byteranges`` response into its parts."""
    parts: list[bytes] = []
    for raw in (b"\r\n" + body).split(b"\r\n--" + boundary):
        raw = raw.lstrip(b"\r\n")
        if raw.startswith(b"--"):
            break
        if not raw:
            continue
        _, sep, data = raw.partition(b"\r\n\r\n")
        if not sep:
            _, sep, data = raw.partition(b"\n\n")
        if data.endswith(b"\r\n"):
            data = data[:-2]
        parts.append(data)
    return parts


def fetch_ranges(
    url: str,
    ranges: Sequence[tuple[int, int]],
    *,
    session: requests.Session | None = None,
    multi_range: bool | None = None,
) -> bytes:
    """Fetch the given byte ranges of ``url`` and return them concatenated.

    A single request with a multi-range header is used when the server allows
    it (the ECMWF portal does, the S3, GCS and Azure mirrors do not - asking
    them for several ranges makes them return the whole object instead).
    """
    if not ranges:
        return b""

    session = session or _session()
    header = "bytes=" + ",".join(f"{start}-{end}" for start, end in ranges)

    if multi_range is None:
        multi_range = len(ranges) > 1 and _supports_multi_range(url)

    if multi_range:
        response = _get(session, url, headers={"Range": header})
        if response.status_code == 206:
            content_type = response.headers.get("Content-Type", "")
            match = re.search(r"boundary=([^\s;]+)", content_type)
            if match:
                parts = _parse_multipart(response.content, match.group(1).strip('"').encode())
                if len(parts) == len(ranges):
                    return b"".join(parts)

    chunks: list[bytes] = []
    for start, end in ranges:
        response = _get(session, url, headers={"Range": f"bytes={start}-{end}"})
        if response.status_code == 416:
            raise OpenDataError(f"range {start}-{end} not satisfiable for {url}")
        response.raise_for_status()
        chunks.append(response.content)
    return b"".join(chunks)


# --------------------------------------------------------------------------- #
# High level API
# --------------------------------------------------------------------------- #


def latest_run(
    source: str = "ecmwf",
    *,
    model: str = "ifs",
    resol: str = "0p1",
    lookback_hours: int = 96,
    session: requests.Session | None = None,
) -> tuple[str, str]:
    """Find the most recent run for which data is actually published.

    The 0.1 deg tier lags the 0.25 deg tier by about two hours, so the newest
    available run is normally older than the current cycle. This probes the
    index of step 0 backwards through the cycle times until it finds one.
    """
    session = session or _session()
    token_cache: dict[str, str] = {}
    now = dt.datetime.now(dt.UTC)
    # Give the 0.1 deg files a two hour grace period before probing.
    candidate = now - dt.timedelta(hours=2)
    candidate = candidate.replace(minute=0, second=0, microsecond=0)
    candidate -= dt.timedelta(hours=candidate.hour % 6)

    for _ in range(lookback_hours // 6 + 1):
        date = candidate.strftime("%Y%m%d")
        time = candidate.strftime("%H")
        url = build_index_url(source, date, time, 0, model=model, resol=resol, levtype="sfc")
        url = authorize_url(url, source, session, token_cache)
        try:
            response = session.get(url, timeout=30)
        except requests.RequestException:
            response = None
        if response is not None and response.status_code == 200:
            return date, time
        candidate -= dt.timedelta(hours=6)

    raise OpenDataError(
        "no published run found in the last "
        f"{lookback_hours} h; the 0.1 deg tier keeps only ~12 runs (~2-3 days)"
    )


def download_step(
    date: str,
    time: str,
    step: int,
    *,
    source: str = "ecmwf",
    param: Sequence[str] | None = None,
    levelist: Sequence[int | str] | None = None,
    levtype: str = "sfc",
    out: str | os.PathLike[str] | None = None,
    whole_file: bool = False,
    session: requests.Session | None = None,
    model: str = "ifs",
    resol: str = "0p1",
    stream: str = "oper",
    type: str = "fc",
) -> str | None:
    """Download one forecast step and return the path of the written file.

    Only the requested fields are transferred: the ``.index`` file says where
    each GRIB message lives and the download uses HTTP range requests. Set
    ``whole_file=True`` to pull the complete file instead.
    """
    session = session or _session()
    index_url = build_index_url(
        source, date, time, step, model=model, resol=resol, stream=stream, type=type, levtype=levtype
    )
    data_url = build_url(
        source, date, time, step, model=model, resol=resol, stream=stream, type=type, levtype=levtype
    )
    token_cache: dict[str, str] = {}
    index_url = authorize_url(index_url, source, session, token_cache)
    data_url = authorize_url(data_url, source, session, token_cache)

    try:
        entries = fetch_index(index_url, session=session)
    except OpenDataError:
        return None

    selected = select_entries(entries, param=param, levelist=levelist, levtype=[levtype])
    if not selected:
        return None

    if whole_file:
        response = _get(session, data_url)
        response.raise_for_status()
        payload = response.content
    else:
        payload = fetch_ranges(data_url, merge_ranges(selected), session=session)

    if out is None:
        out = f"{date}{time}0000-{step}h-{stream}-{type}-{LEVSUFFIX[levtype]}.grib2"
    out = os.fspath(out)
    parent = os.path.dirname(out)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out, "wb") as handle:
        handle.write(payload)
    return out


def download(
    date: str | dt.date | None = None,
    time: str | int | None = None,
    *,
    step: int | Sequence[int] = 0,
    source: str = "ecmwf",
    param: Sequence[str] | None = None,
    levelist: Sequence[int | str] | None = None,
    levtype: str | Sequence[str] = "sfc",
    out: str | os.PathLike[str] = ".",
    whole_file: bool = False,
    max_workers: int = 4,
    model: str = "ifs",
    resol: str = "0p1",
    stream: str = "oper",
    type: str = "fc",
    session: requests.Session | None = None,
    verbose: bool = True,
) -> list[str]:
    """Download one or more forecast steps and return the written file paths.

    Parameters
    ----------
    date, time
        Forecast run to fetch. Defaults to the latest published run.
    step
        Forecast step(s) in hours.
    source
        Which mirror to use: ``ecmwf``, ``aws``, ``google`` or ``azure``.
    param
        Short parameter names such as ``["2t", "msl"]``. ``None`` takes all.
    levelist
        Pressure levels, e.g. ``[500, 850]``.
    levtype
        ``sfc`` (surface), ``pl`` (pressure level) or ``sol`` (soil).
    out
        Output directory or file path.
    whole_file
        Download complete files instead of extracting selected fields.
    """
    session = session or _session()

    if date is None:
        date, time = latest_run(source, model=model, resol=resol, session=session)
    date, time = _normalise_run(date, time)

    steps = [step] if isinstance(step, int) else list(step)
    levtypes = [levtype] if isinstance(levtype, str) else list(levtype)

    if str(out).endswith((".grib2", ".grib", ".grb")):
        out_dir = os.path.dirname(os.fspath(out)) or "."
        os.makedirs(out_dir, exist_ok=True)
    else:
        out_dir = os.fspath(out)
        os.makedirs(out_dir, exist_ok=True)

    jobs = [(s, lt) for s in steps for lt in levtypes]

    def run_job(job: tuple[int, str]) -> str | None:
        job_step, job_lev = job
        name = f"{date}{time}0000-{job_step}h-{stream}-{type}-{LEVSUFFIX[job_lev]}.grib2"
        path = os.path.join(out_dir, name)
        result = download_step(
            date,
            time,
            job_step,
            source=source,
            param=param,
            levelist=levelist,
            levtype=job_lev,
            out=path,
            whole_file=whole_file,
            session=session,
            model=model,
            resol=resol,
            stream=stream,
            type=type,
        )
        if result and verbose:
            size = os.path.getsize(result) / 1e6
            print(f"  wrote {result} ({size:.1f} MB)")
        return result

    paths: list[str] = []
    if max_workers > 1 and len(jobs) > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            paths = [p for p in pool.map(run_job, jobs) if p]
    else:
        paths = [p for p in (run_job(job) for job in jobs) if p]

    if verbose:
        print(ATTRIBUTION)
    return paths
