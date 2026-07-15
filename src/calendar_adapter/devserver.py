"""Development CalDAV server: Radicale served in-process.

Used by the quickstart (scripts/run_radicale.py) and by the integration
tests, so both run the exact same server.

Why not `python -m radicale` directly? Radicale's startup probe
`path_supports_symlink` only catches PermissionError, but os.symlink on
Windows without Developer Mode raises a plain OSError (WinError 1314),
crashing storage initialization. Serving in-process lets us patch the
probe to answer "no symlink support", which is the truthful result.
"""

from __future__ import annotations

from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import radicale.config
import radicale.pathutils
from radicale.app import Application

__all__ = ["make_dev_server"]


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


def _patch_symlink_probe() -> None:
    """Idempotent: wrap Radicale's symlink probe so OSError means False."""
    original = radicale.pathutils.path_supports_symlink
    if getattr(original, "_polyglot_safe", False):
        return

    def safe_probe(path: str) -> bool:
        try:
            return bool(original(path))
        except OSError:
            return False

    safe_probe._polyglot_safe = True  # type: ignore[attr-defined]
    radicale.pathutils.path_supports_symlink = safe_probe


def make_dev_server(
    storage_folder: str | Path,
    host: str = "127.0.0.1",
    port: int = 0,
) -> WSGIServer:
    """A ready-to-serve Radicale WSGI server with open (none) auth.

    port=0 picks a free port; read it back from server.server_port.
    Never expose this beyond localhost: authentication is disabled.
    """
    _patch_symlink_probe()
    configuration = radicale.config.load()
    configuration.update(
        {
            "auth": {"type": "none"},
            "storage": {"filesystem_folder": str(storage_folder)},
        },
        "polyglot-devserver",
        privileged=True,
    )
    application = Application(configuration)
    return make_server(host, port, application, handler_class=_QuietHandler)
