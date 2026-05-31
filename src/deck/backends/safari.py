"""Safari backend — path for all Synadia Google targets.

Dedup is by tab URL across every Safari window (substring match on
``target.match``). Because Synadia Google lives in Safari and personal Google
lives in Chrome (a physically different browser), this can never resolve to a
personal tab — no profile-aware logic needed.

  * find   -> AppleScript scans all windows/tabs; on a match selects that tab
              and activates Safari. Returns a Handle (found=True).
  * create -> AppleScript opens the URL in a NEW Safari window so it can be
              placed independently on the target workspace.

After focus/create the orchestrator uses AeroSpace's focused-window query to
learn which workspace the window lives on, so we never map AppleScript window
objects to AeroSpace window-ids.
"""

from .. import aerospace
from ..aerospace import find_new_window
from ..config import Target
from . import Handle, run_osascript

APP_NAME = "Safari"


def _osa_str(s: str) -> str:
    """Quote a Python string for embedding inside AppleScript double quotes."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _find_script(match: str) -> str:
    m = _osa_str(match)
    # `is running` does not launch Safari, so find() stays side-effect-free.
    return f'''
if application "Safari" is not running then return "NONE"
tell application "Safari"
    set theMatch to "{m}"
    repeat with w in windows
        set tabIndex to 0
        repeat with t in tabs of w
            set tabIndex to tabIndex + 1
            if (URL of t is not missing value) and (URL of t contains theMatch) then
                set current tab of w to t
                set index of w to 1
                activate
                return "FOUND"
            end if
        end repeat
    end repeat
    return "NONE"
end tell
'''


def _close_script(match: str) -> str:
    m = _osa_str(match)
    return f'''
if application "Safari" is not running then return "NONE"
tell application "Safari"
    set theMatch to "{m}"
    repeat with w in windows
        repeat with t in tabs of w
            if (URL of t is not missing value) and (URL of t contains theMatch) then
                close t
                return "CLOSED"
            end if
        end repeat
    end repeat
    return "NONE"
end tell
'''


def _create_script(url: str) -> str:
    u = _osa_str(url)
    return f'''
tell application "Safari"
    make new document with properties {{URL:"{u}"}}
    activate
    return "CREATED"
end tell
'''


def _add_tab_script(window_id: str, url: str) -> str:
    u = _osa_str(url)
    # AeroSpace's window-id IS Safari's AppleScript window id, so address the
    # window directly — no title bridge needed.
    return f'''
if application "Safari" is not running then return "NONE"
tell application "Safari"
    try
        tell window id {window_id}
            set current tab to (make new tab with properties {{URL:"{u}"}})
        end tell
        activate
        return "TABBED"
    on error
        return "NOWIN"
    end try
end tell
'''


class SafariBackend:
    def find(self, target: Target) -> Handle | None:
        match = target.match or target.url
        result = run_osascript(_find_script(match))
        if result.endswith("FOUND"):
            return Handle(
                app=APP_NAME,
                found=True,
                ref={"match": match},
                detail=f"Safari tab matching '{match}'",
            )
        return None

    def focus(self, handle: Handle) -> None:
        # find() already selected the tab + activated Safari; nothing more.
        pass

    def create(self, target: Target) -> Handle:
        # Prefer consolidation: add the URL as a new tab in a Safari window that
        # already lives on the target workspace (one browser-per-workspace with N
        # tabs). Fall back to a new window when that workspace has no Safari.
        target_ws = aerospace.resolve_workspace(target.workspace)
        if target_ws is not None:
            for w in aerospace.windows_on_workspace(APP_NAME, target_ws):
                result = run_osascript(_add_tab_script(w["window_id"], target.url))
                if result.endswith("TABBED"):
                    return Handle(
                        app=APP_NAME,
                        found=False,
                        window_id=w["window_id"],
                        detail=f"new tab in Safari window on workspace {target_ws}",
                    )

        run_osascript(_create_script(target.url))
        return Handle(
            app=APP_NAME,
            found=False,
            detail=f"new Safari window -> {target.url}",
        )

    def close(self, handle: Handle) -> None:
        match = handle.ref.get("match", "")
        run_osascript(_close_script(match))

    def new_window_id(self, target: Target, before_ids, timeout: float = 2.0):
        return find_new_window(before_ids, APP_NAME, timeout=timeout)

    def describe_create(self, target: Target) -> list[str]:
        target_ws = aerospace.resolve_workspace(target.workspace)
        aero = (
            aerospace.windows_on_workspace(APP_NAME, target_ws) if target_ws else []
        )
        if aero:
            return [
                f"osascript: tell Safari window id {aero[0]['window_id']} "
                f"(on workspace {target_ws}) to make new tab with URL {target.url}",
            ]
        return [
            f"osascript: tell Safari to make new document with URL {target.url} "
            f"(no Safari window on workspace {target_ws}; opens a new one)",
        ]

    def describe_focus(self, handle: Handle) -> list[str]:
        match = handle.ref.get("match", "")
        return [
            f"osascript: tell Safari to select tab matching '{match}' + activate",
        ]

    def describe_close(self, handle: Handle) -> list[str]:
        match = handle.ref.get("match", "")
        return [
            f"osascript: tell Safari to close tab matching '{match}'",
        ]
