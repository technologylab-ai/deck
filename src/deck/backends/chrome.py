"""Chrome backend — default profile, dedup via the Accessibility (AX) API.

Why AX instead of AppleScript: the user routinely runs extra Chrome instances
via ``--app=<url> --user-data-dir=...`` (OBS capture, slides, a browser demo).
They all share bundle id ``com.google.Chrome``, so ``tell application "Google
Chrome"`` Apple Events route to an arbitrary instance (often one with no
scriptable windows), making AppleScript dedup/focus unreliable. The AX API
targets Chrome windows by PID and exposes each window's *active-tab* URL as the
window-level ``AXDocument`` attribute — instantly, no tree traversal, immune to
how many Chrome instances are running.

``find`` reads ``AXDocument`` across every Chrome window and matches
``target.match``; the window's AX title bridges to the AeroSpace window-id (the
titles are identical), and ``focus`` uses ``aerospace focus --window-id`` to
focus the window and follow to its workspace. ``create`` opens the URL in its
own ``--new-window`` in the default profile, so a deck-opened app is always the
active tab of its window and ``AXDocument`` reliably matches it next time.

Requires Accessibility permission for the app running deck (Ghostty for dev,
Elgato Stream Deck for buttons). Limitation: ``AXDocument`` is the active tab
only, so a target sitting as a *background* tab in a shared window isn't seen —
not an issue for deck-opened windows, which are single-purpose.
"""

import subprocess

from .. import aerospace
from ..config import Target
from . import BackendError, Handle, run_osascript

APP_NAME = "Google Chrome"
CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# osascript surfaces these when the controlling app lacks Accessibility access.
_AX_DENIED = ("-25211", "assistive access", "not allowed assistive")


def _osa_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _ax_find_script(match: str) -> str:
    m = _osa_str(match)
    # AXDocument is the active tab's URL, exposed at window level — no traversal.
    return f'''
tell application "System Events"
    set theMatch to "{m}"
    repeat with p in (every process whose name is "Google Chrome")
        repeat with w in windows of p
            try
                set u to (value of attribute "AXDocument" of w) as text
                if u contains theMatch then return (name of w)
            end try
        end repeat
    end repeat
    return ""
end tell
'''


def _ax_raise_script(title: str) -> str:
    t = _osa_str(title)
    return f'''
tell application "System Events"
    set theTitle to "{t}"
    repeat with p in (every process whose name is "Google Chrome")
        repeat with w in windows of p
            if (name of w) is theTitle then
                perform action "AXRaise" of w
                set frontmost of p to true
                return "OK"
            end if
        end repeat
    end repeat
    return ""
end tell
'''


class ChromeBackend:
    def find(self, target: Target) -> Handle | None:
        match = target.match or target.url
        try:
            title = run_osascript(_ax_find_script(match))
        except BackendError as exc:
            if any(s in str(exc) for s in _AX_DENIED):
                raise BackendError(
                    "Chrome dedup needs Accessibility permission. Grant it to the "
                    "app running deck (Ghostty for dev, Elgato Stream Deck for "
                    "buttons) in System Settings → Privacy & Security → "
                    "Accessibility, then retry."
                ) from exc
            raise
        if not title:
            return None

        # The AX window title equals the AeroSpace window title; bridge to its id.
        window_id = None
        for w in aerospace.list_windows():
            if w["app"].lower() == APP_NAME.lower() and w["title"] == title:
                window_id = w["window_id"]
                break

        return Handle(
            app=APP_NAME,
            found=True,
            window_id=window_id,
            ref={"title": title, "match": match},
            detail=f"Chrome window '{title}' (AXDocument matches '{match}')",
        )

    def focus(self, handle: Handle) -> None:
        if handle.window_id:
            aerospace.focus_window(handle.window_id)
        else:
            # Couldn't map to an AeroSpace id (race); raise the window via AX.
            run_osascript(_ax_raise_script(handle.ref.get("title", "")))

    def create(self, target: Target) -> Handle:
        # Open a new window in the DEFAULT Chrome profile via the binary. We do
        # NOT use AppleScript `make new window`: with extra Chrome instances
        # running under their own --user-data-dir, Apple Events route to an
        # arbitrary instance and can spawn the window in a throwaway, logged-out
        # profile. Launching the binary with --new-window and no --user-data-dir
        # always hands off to the running default-profile instance.
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
        return aerospace.find_new_window(before_ids, APP_NAME, timeout=timeout)

    def describe_create(self, target: Target) -> list[str]:
        note = ""
        if target.mode == "app":
            note = "  (mode='app' requested; Phase 1 opens a normal window anyway)"
        return [
            f"{CHROME_BIN} --new-window {target.url}{note}",
            "(default profile; avoids AppleScript routing to a stray instance)",
        ]

    def describe_focus(self, handle: Handle) -> list[str]:
        title = handle.ref.get("title", "")
        if handle.window_id:
            return [
                f"aerospace focus --window-id {handle.window_id}  "
                f"(focuses '{title}' + follows to its workspace)"
            ]
        return [f"AX: raise Chrome window '{title}' + activate"]
