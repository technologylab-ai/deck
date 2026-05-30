"""Chrome backend — default profile, normal tab (Phase 1).

Dedup is by tab URL substring (``target.match``) across all Chrome windows.
Phase 1 opens a *normal tab* (in a new window so it can be placed); Phase 2 will
honor ``mode = "app"`` to launch a ``--app=<url>`` window via the Chrome binary.

Because personal Google lives here and Synadia Google lives in Safari, no
profile-aware dedup is needed — the browser boundary isolates them.
"""

import subprocess

from ..aerospace import find_new_window
from ..config import Target
from . import Handle, run_osascript

APP_NAME = "Google Chrome"
CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


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
        # Open a new window in the DEFAULT Chrome profile via the binary. We do
        # NOT use AppleScript `make new window`: when extra Chrome instances run
        # with their own --user-data-dir (e.g. OBS `--app` windows), Apple
        # Events route to an arbitrary instance and can spawn the window in a
        # throwaway, logged-out profile. Launching the binary with --new-window
        # and no --user-data-dir always hands off to the running default-profile
        # instance ("Opening in existing browser session").
        subprocess.run(
            [CHROME_BIN, "--new-window", target.url],
            capture_output=True,
            text=True,
            check=False,
        )
        return Handle(
            app=APP_NAME,
            found=False,
            detail=f"new Chrome window -> {target.url}",
        )

    def new_window_id(self, target: Target, before_ids, timeout: float = 2.0):
        return find_new_window(before_ids, APP_NAME, timeout=timeout)

    def describe_create(self, target: Target) -> list[str]:
        note = ""
        if target.mode == "app":
            note = "  (mode='app' requested; Phase 1 opens a normal window anyway)"
        return [
            f"{CHROME_BIN} --new-window {target.url}{note}",
            "(default profile; avoids AppleScript routing to a stray instance)",
        ]

    def describe_focus(self, handle: Handle) -> list[str]:
        match = handle.ref.get("match", "")
        return [
            f"osascript: tell Chrome to select tab matching '{match}' + activate",
        ]
