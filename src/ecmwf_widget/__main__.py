"""The commands of the package, under one name.

    python -m ecmwf_widget service once
    python -m ecmwf_widget widget --open
    python -m ecmwf_widget --help

The console scripts (``ecmwf-service``, ``ecmwf-widget``, ...) call the
same functions, so both ways are the same command.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

__all__ = ["COMMANDS", "main"]

#: The command name and the module that implements it.
COMMANDS: dict[str, str] = {
    "service": "ecmwf_widget.service",
    "widget": "ecmwf_widget.widget",
    "publisher": "ecmwf_widget.auto_publish",
    "publish": "ecmwf_widget.publish",
    "build-site": "ecmwf_widget.build_site",
    "build-places": "ecmwf_widget.build_places",
    "make-icons": "ecmwf_widget.make_icons",
    "download": "ecmwf_widget.download_9km",
}


def _usage() -> str:
    lines = ["usage: python -m ecmwf_widget <command> [options]", "", "commands:"]
    for name, module in COMMANDS.items():
        summary = (module.rsplit(".", 1)[-1]).replace("_", "-")
        lines.append(f"  {name:<14} the {summary} command")
    lines.append("")
    lines.append("Every command takes --help. The console scripts are the same:")
    lines.append("  ecmwf-service, ecmwf-widget, ecmwf-publisher, ecmwf-publish,")
    lines.append("  ecmwf-build-site, ecmwf-build-places, ecmwf-make-icons, ecmwf-download")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run one of the commands."""
    import importlib

    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in ("-h", "--help"):
        print(_usage())
        return 0

    name = arguments.pop(0)
    if name not in COMMANDS:
        print(f"unknown command: {name}", file=sys.stderr)
        print(_usage(), file=sys.stderr)
        return 2

    module = importlib.import_module(COMMANDS[name])
    entry: Callable[[list[str] | None], int] = module.main
    return int(entry(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
