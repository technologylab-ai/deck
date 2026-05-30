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


def _create_script(url: str) -> str:
    u = _osa_str(url)
    return f'''
tell application "Safari"
    make new document with properties {{URL:"{u}"}}
    activate
    return "CREATED"
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
        run_osascript(_create_script(target.url))
        return Handle(
            app=APP_NAME,
            found=False,
            detail=f"new Safari window -> {target.url}",
        )

    def new_window_id(self, target: Target, before_ids, timeout: float = 2.0):
        return find_new_window(before_ids, APP_NAME, timeout=timeout)

    def describe_create(self, target: Target) -> list[str]:
        return [
            f"osascript: tell Safari to make new document with URL {target.url}",
        ]

    def describe_focus(self, handle: Handle) -> list[str]:
        match = handle.ref.get("match", "")
        return [
            f"osascript: tell Safari to select tab matching '{match}' + activate",
        ]
