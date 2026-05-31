"""Native macOS app backend.

dedup = is the app running. We use AeroSpace's own window list (filtered by
bundle-id) to detect a running app and to grab its window-id. Launch/focus is
`open -b <bundle>`, which activates an already-running app or starts it.

Placement for app targets is *primarily* delegated to AeroSpace
`on-window-detected` rules (see aerospace-snippet.toml); the dynamic move in
cli.py is a fallback for apps without a static rule.
"""

import subprocess

from ..aerospace import AEROSPACE
from ..config import Target
from ..logging import get_logger
from . import BackendError, Handle

_log = get_logger()


def _windows_for_bundle(bundle: str) -> list[dict]:
    """Return AeroSpace windows for a bundle-id (empty if not running)."""
    # NB: the `--all` alias conflicts with filtering flags ("--all conflicts
    # with filtering flags"), so we must NOT combine it with --app-bundle-id.
    # `--monitor all` spans every monitor and still allows the bundle filter.
    cmd = [
        AEROSPACE,
        "list-windows",
        "--monitor",
        "all",
        "--app-bundle-id",
        bundle,
        "--format",
        "%{window-id}|%{app-name}",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=10
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise BackendError(f"aerospace list-windows failed: {exc}") from exc
    if proc.returncode != 0:
        # A real failure (e.g. bad flags) must not masquerade as "not running".
        # An unknown/uninstalled bundle exits non-zero with empty output, which
        # is the legitimate "not open" case; surface anything else.
        if proc.stderr.strip():
            raise BackendError(
                f"aerospace list-windows failed: {proc.stderr.strip()}"
            )
        return []
    out = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        wid, app = line.split("|", 1)
        out.append({"window_id": wid.strip(), "app": app.strip()})
    return out


class AppBackend:
    def find(self, target: Target) -> Handle | None:
        wins = _windows_for_bundle(target.bundle)
        if not wins:
            return None
        first = wins[0]
        return Handle(
            app=first["app"],
            found=True,
            window_id=first["window_id"],
            ref={"bundle": target.bundle},
            detail=f"{first['app']} (window {first['window_id']})",
        )

    def focus(self, handle: Handle) -> None:
        bundle = handle.ref.get("bundle")
        _open_bundle(bundle)

    def create(self, target: Target) -> Handle:
        _open_bundle(target.bundle)
        # window-id is resolved by the orchestrator after the window appears;
        # app-name for matching is best-effort from a follow-up list-windows.
        return Handle(
            app="",  # resolved by caller via bundle re-query if needed
            found=False,
            ref={"bundle": target.bundle},
            detail=f"open -b {target.bundle}",
        )

    def resolve_app_name(self, target: Target) -> str:
        """Best-effort AeroSpace app-name for a freshly-launched bundle."""
        wins = _windows_for_bundle(target.bundle)
        return wins[0]["app"] if wins else ""

    def new_window_id(self, target: Target, before_ids, timeout: float = 2.0):
        """Poll for a new window of this bundle that wasn't there before."""
        import time

        deadline = time.monotonic() + timeout
        while True:
            for w in _windows_for_bundle(target.bundle):
                if w["window_id"] not in before_ids:
                    return w["window_id"]
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.1)

    def close(self, handle: Handle) -> None:
        # Quit the whole app (all its windows) — the natural inverse of "open"
        # for a native target, and what frees up its AeroSpace workspace.
        _quit_bundle(handle.ref.get("bundle"))

    def describe_create(self, target: Target) -> list[str]:
        return [f"open -b {target.bundle}"]

    def describe_focus(self, handle: Handle) -> list[str]:
        return [f"open -b {handle.ref.get('bundle')}  (activate running app)"]

    def describe_close(self, handle: Handle) -> list[str]:
        return [
            f'osascript: tell application id "{handle.ref.get("bundle")}" to quit'
        ]


def _quit_bundle(bundle: str) -> None:
    if not bundle:
        raise BackendError("app target has no bundle id")
    _log.debug("quit app id %s", bundle)
    # A quit Apple Event needs Automation permission for the app running deck →
    # the target app (first time shows a one-time prompt, same as the browsers).
    try:
        proc = subprocess.run(
            ["/usr/bin/osascript", "-e", f'tell application id "{bundle}" to quit'],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise BackendError(f"quit failed: {exc}") from exc
    if proc.returncode != 0:
        raise BackendError(
            f"quit {bundle} failed: {proc.stderr.strip() or proc.returncode}"
        )


def _open_bundle(bundle: str) -> None:
    if not bundle:
        raise BackendError("app target has no bundle id")
    _log.debug("open -b %s", bundle)
    try:
        proc = subprocess.run(
            ["/usr/bin/open", "-b", bundle],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise BackendError(f"open failed: {exc}") from exc
    if proc.returncode != 0:
        raise BackendError(
            f"open -b {bundle} failed: {proc.stderr.strip() or proc.returncode}"
        )
