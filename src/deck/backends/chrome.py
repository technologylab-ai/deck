"""Chrome backend — default profile, normal tab (Phase 1).

Dedup is by tab URL substring (``target.match``) across all Chrome windows.
Phase 1 opens a *normal tab* (in a new window so it can be placed); Phase 2 will
honor ``mode = "app"`` to launch a ``--app=<url>`` window via the Chrome binary.

Because personal Google lives here and Synadia Google lives in Safari, no
profile-aware dedup is needed — the browser boundary isolates them.
"""

from ..aerospace import find_new_window
from ..config import Target
from . import Handle, run_osascript

APP_NAME = "Google Chrome"


def _osa_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _find_script(match: str) -> str:
    m = _osa_str(match)
    # `is running` does not launch Chrome, so find() stays side-effect-free.
    return f'''
if application "Google Chrome" is not running then return "NONE"
tell application "Google Chrome"
    set theMatch to "{m}"
    repeat with w in windows
        set tabIndex to 0
        repeat with t in tabs of w
            set tabIndex to tabIndex + 1
            if (URL of t contains theMatch) then
                set active tab index of w to tabIndex
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
tell application "Google Chrome"
    make new window
    set URL of active tab of front window to "{u}"
    activate
    return "CREATED"
end tell
'''


class ChromeBackend:
    def find(self, target: Target) -> Handle | None:
        match = target.match or target.url
        result = run_osascript(_find_script(match))
        if result.endswith("FOUND"):
            return Handle(
                app=APP_NAME,
                found=True,
                ref={"match": match},
                detail=f"Chrome tab matching '{match}'",
            )
        return None

    def focus(self, handle: Handle) -> None:
        # find() already selected the tab + activated Chrome.
        pass

    def create(self, target: Target) -> Handle:
        run_osascript(_create_script(target.url))
        return Handle(
            app=APP_NAME,
            found=False,
            detail=f"new Chrome tab -> {target.url}",
        )

    def new_window_id(self, target: Target, before_ids, timeout: float = 2.0):
        return find_new_window(before_ids, APP_NAME, timeout=timeout)

    def describe_create(self, target: Target) -> list[str]:
        note = ""
        if target.mode == "app":
            note = "  (mode='app' requested; Phase 1 opens a normal tab anyway)"
        return [
            f"osascript: tell Chrome to make new window + set URL {target.url}{note}",
        ]

    def describe_focus(self, handle: Handle) -> list[str]:
        match = handle.ref.get("match", "")
        return [
            f"osascript: tell Chrome to select tab matching '{match}' + activate",
        ]
