"""AeroSpace integration: enumerate windows, place them, switch workspaces.

All interaction goes through the `aerospace` CLI via subprocess. We never
hardcode workspace names — callers pass them in from config (which the user
derived from their own aerospace.toml).
"""

import subprocess
import time

from .logging import get_logger

AEROSPACE = "/opt/homebrew/bin/aerospace"

# Stable field separator for --format. Pipe is unlikely to appear in app names;
# window titles can contain it, so we split with a max count and keep the title
# as the remainder.
_FORMAT = "%{window-id}|%{app-name}|%{workspace}|%{window-title}"

_log = get_logger()


class AeroSpaceError(Exception):
    """Raised when the aerospace CLI is missing or fails unexpectedly."""


def _run(args: list[str]) -> subprocess.CompletedProcess:
    cmd = [AEROSPACE, *args]
    _log.debug("aerospace: %s", " ".join(cmd))
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=10
        )
    except FileNotFoundError as exc:
        raise AeroSpaceError(f"aerospace binary not found at {AEROSPACE}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AeroSpaceError("aerospace command timed out") from exc


def list_windows() -> list[dict]:
    """Return all windows as dicts: window_id, app, workspace, title."""
    proc = _run(["list-windows", "--all", "--format", _FORMAT])
    if proc.returncode != 0:
        raise AeroSpaceError(
            f"list-windows failed: {proc.stderr.strip() or proc.returncode}"
        )
    windows = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        wid, app, ws, title = parts
        windows.append(
            {
                "window_id": wid.strip(),
                "app": app.strip(),
                "workspace": ws.strip(),
                "title": title.strip(),
            }
        )
    return windows


def window_ids() -> set[str]:
    """Convenience: just the set of current window-ids."""
    return {w["window_id"] for w in list_windows()}


def find_window_id(app: str, before_ids: set[str]) -> str | None:
    """Return a window-id for `app` that is not in `before_ids`, else None."""
    for w in list_windows():
        if w["window_id"] in before_ids:
            continue
        if app and w["app"].lower() != app.lower():
            continue
        return w["window_id"]
    return None


def find_new_window(
    before_ids: set[str], app: str, timeout: float = 2.0, interval: float = 0.1
) -> str | None:
    """Poll list-windows until a new window-id for `app` appears or we time out.

    Handles the race where a freshly-opened window shows up a beat later.
    """
    deadline = time.monotonic() + timeout
    while True:
        wid = find_window_id(app, before_ids)
        if wid is not None:
            return wid
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


def place_and_switch(window_id: str, workspace: str) -> None:
    """Move a window to a workspace and switch focus to that workspace."""
    proc = _run(
        [
            "move-node-to-workspace",
            "--window-id",
            window_id,
            workspace,
            "--focus-follows-window",
        ]
    )
    if proc.returncode != 0:
        raise AeroSpaceError(
            f"move-node-to-workspace failed: {proc.stderr.strip() or proc.returncode}"
        )
    switch_to(workspace)


def switch_to(workspace: str) -> None:
    """Switch the active workspace."""
    proc = _run(["workspace", workspace])
    if proc.returncode != 0:
        raise AeroSpaceError(
            f"workspace switch failed: {proc.stderr.strip() or proc.returncode}"
        )


def focus_window(window_id: str) -> None:
    """Focus a specific window by id; AeroSpace follows to its workspace."""
    proc = _run(["focus", "--window-id", window_id])
    if proc.returncode != 0:
        raise AeroSpaceError(
            f"focus --window-id failed: {proc.stderr.strip() or proc.returncode}"
        )


def focused_window() -> dict | None:
    """Return the currently-focused window dict, or None."""
    proc = _run(["list-windows", "--focused", "--format", _FORMAT])
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        wid, app, ws, title = parts
        return {
            "window_id": wid.strip(),
            "app": app.strip(),
            "workspace": ws.strip(),
            "title": title.strip(),
        }
    return None


def workspace_of(window_id: str) -> str | None:
    """Return the workspace a given window-id currently lives on, if known."""
    for w in list_windows():
        if w["window_id"] == window_id:
            return w["workspace"]
    return None
