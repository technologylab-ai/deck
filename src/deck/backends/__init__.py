"""Backend interface + registry.

Every backend implements the same small surface so the `open` orchestration in
cli.py never special-cases a target kind:

    find(target)   -> Handle | None      # is it already open? (read-only)
    focus(handle)  -> None               # bring it to the foreground
    create(target) -> Handle             # open it fresh
    place(handle, workspace) -> None     # move the new window + switch

Plus a describe* path used by --dry-run to print exact commands without acting.

The Handle carries enough to (a) focus the existing window and (b) resolve the
new AeroSpace window-id after a create().
"""

import subprocess
from dataclasses import dataclass, field
from typing import Protocol

from ..config import Target
from ..logging import get_logger

_log = get_logger()


class BackendError(Exception):
    """Raised when a backend's underlying command fails."""


def run_osascript(script: str) -> str:
    """Run an AppleScript via osascript and return stdout (stripped)."""
    _log.debug("osascript:\n%s", script)
    try:
        proc = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except FileNotFoundError as exc:
        raise BackendError("osascript not found at /usr/bin/osascript") from exc
    except subprocess.TimeoutExpired as exc:
        raise BackendError("osascript timed out") from exc
    if proc.returncode != 0:
        raise BackendError(proc.stderr.strip() or "osascript failed")
    return proc.stdout.strip()


@dataclass
class Handle:
    """Reference to a found-or-created window."""

    app: str  # AeroSpace app-name, used to resolve the window-id after create()
    found: bool  # True if this came from find(); False if freshly created
    window_id: str | None = None  # known window-id, when available
    ref: dict = field(default_factory=dict)  # backend-private focus reference
    detail: str = ""  # human-readable description for logs / dry-run


class Backend(Protocol):
    def find(self, target: Target) -> Handle | None: ...
    def focus(self, handle: Handle) -> None: ...
    def create(self, target: Target) -> Handle: ...

    # Dry-run description: the exact command(s)/AppleScript that focus/create
    # would execute for this target, given a prior find() result.
    def describe_create(self, target: Target) -> list[str]: ...
    def describe_focus(self, handle: Handle) -> list[str]: ...


def get_backend(target: Target) -> Backend:
    """Select the backend for a target by its kind."""
    from . import app, chrome, safari

    if target.kind == "app":
        return app.AppBackend()
    if target.kind == "safari":
        return safari.SafariBackend()
    if target.kind == "chrome":
        return chrome.ChromeBackend()
    raise ValueError(f"no backend for kind '{target.kind}'")
