"""Windowless system actions for `type = "action"` targets.

Unlike app/browser targets, these have no AeroSpace window and no workspace —
`deck open <name>` just performs the action and returns. The only one so far is
toggling/setting the global macOS appearance (light/dark).

Setting appearance drives **System Events** via Apple Events, so the app running
deck (your terminal for dev, Elgato Stream Deck for buttons) needs Automation
access to System Events — a one-time prompt on first press, same model as the
Safari/Chrome backends. Reading the current mode, by contrast, goes through
`defaults` and needs no permission.
"""

import subprocess

from .logging import get_logger

_log = get_logger()


class ActionError(Exception):
    """Raised when a system action cannot be performed."""


# AppleScript fragments. The toggle is atomic (`not dark mode`) so a press never
# races a separate read; the explicit forms set an absolute value.
_TOGGLE = (
    'tell application "System Events" to tell appearance preferences '
    "to set dark mode to not dark mode"
)
_SET = (
    'tell application "System Events" to tell appearance preferences '
    "to set dark mode to {value}"
)

# action id -> the osascript that performs it
_SCRIPTS = {
    "theme-toggle": _TOGGLE,
    "theme-dark": _SET.format(value="true"),
    "theme-light": _SET.format(value="false"),
}


def script_for(action: str) -> str:
    """The AppleScript an action runs (used by --dry-run)."""
    try:
        return _SCRIPTS[action]
    except KeyError:
        raise ActionError(f"unknown action '{action}'") from None


def current_mode() -> str:
    """Return 'dark' or 'light' — permission-free read via `defaults`.

    `AppleInterfaceStyle` is present (== "Dark") only in dark mode; in light mode
    the key is absent and `defaults read` exits non-zero.
    """
    try:
        proc = subprocess.run(
            ["/usr/bin/defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "light"
    return "dark" if proc.stdout.strip() == "Dark" else "light"


def run_action(action: str) -> str:
    """Perform a system action; return the resulting mode ('dark'/'light').

    Raises ActionError with a clear message if Apple Events are denied (TCC
    error -1743) or System Events is otherwise unreachable.
    """
    script = script_for(action)
    try:
        proc = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except FileNotFoundError as exc:
        raise ActionError("osascript not found at /usr/bin/osascript") from exc
    except subprocess.TimeoutExpired as exc:
        raise ActionError("osascript timed out talking to System Events") from exc

    if proc.returncode != 0:
        err = proc.stderr.strip()
        if "-1743" in err or "Not authorized" in err:
            raise ActionError(
                "not authorized to control System Events — grant the app running "
                "deck (your terminal for dev, Elgato Stream Deck for buttons) "
                "Automation access to System Events in System Settings › Privacy "
                "& Security › Automation."
            )
        raise ActionError(err or "osascript failed")

    _log.info("action %s -> %s", action, current_mode())
    return current_mode()
