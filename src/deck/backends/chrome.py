"""Chrome backend — default profile, dedup via ScriptingBridge (PID-targeted).

Why not plain AppleScript: the user routinely runs extra Chrome instances via
``--app=<url> --user-data-dir=...`` (OBS capture, slides, a browser demo). They
all share bundle id ``com.google.Chrome``, so ``tell application "Google Chrome"``
Apple Events route to an *arbitrary* instance and dedup/focus break.

Fix: address Apple Events to a *specific* process id with ScriptingBridge
(``SBApplication initWithProcessIdentifier:``). We target the default-profile
Chrome (the main process launched with no ``--user-data-dir``), so we always talk
to the user's real, logged-in browser regardless of how many ``--app`` Chrome
instances are running. This gives the full Chrome scripting dictionary: every
window, every tab (including **background** tabs), their URLs, and the ability to
select a tab — none of which AppleScript routing or the AX API could deliver here.

``find`` scans all tabs for ``target.match``; ``focus`` selects that tab, raises
its window, activates Chrome, and switches AeroSpace to the window's workspace.
``create`` opens the URL in its own ``--new-window`` in the default profile.

Requires Automation (Apple Events) permission for the app running deck (your
terminal for dev, Elgato Stream Deck for buttons) → Google Chrome. ``deck doctor``
checks it.
"""

import subprocess

from .. import aerospace
from ..config import Target
from . import BackendError, Handle

APP_NAME = "Google Chrome"
CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
_CHROME_MAIN = "Google Chrome.app/Contents/MacOS/Google Chrome"


def _default_profile_pid() -> int | None:
    """PID of the default-profile Chrome (main process, no --user-data-dir).

    Prefers the instance without --user-data-dir (the user's real browser) over
    the --app/--user-data-dir instances that share the same bundle id.
    """
    try:
        out = subprocess.run(
            ["/bin/ps", "-ax", "-o", "pid=,command="],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        ).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    candidates: list[tuple[bool, int]] = []
    for line in out.splitlines():
        line = line.strip()
        if _CHROME_MAIN not in line:
            continue
        if "--type=" in line or "Helper" in line:  # renderers / helpers
            continue
        pid_str, _, cmd = line.partition(" ")
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        is_default = "--user-data-dir" not in cmd
        candidates.append((is_default, pid))

    if not candidates:
        return None
    # Default-profile instance first; otherwise fall back to any main instance.
    candidates.sort(key=lambda c: (not c[0], c[1]))
    return candidates[0][1]


def _chrome_app(pid: int):
    """SBApplication addressed to a specific Chrome PID (lazy PyObjC import)."""
    from ScriptingBridge import SBApplication

    return SBApplication.alloc().initWithProcessIdentifier_(pid)


def _aerospace_id_for_title(title: str) -> str | None:
    """Map a Chrome window title to its AeroSpace window-id.

    ScriptingBridge titles are the bare page title; AeroSpace appends
    " - Google Chrome - <profile>", so we match on prefix.
    """
    if not title:
        return None
    for w in aerospace.list_windows():
        if w["app"].lower() != APP_NAME.lower():
            continue
        if w["title"] == title or w["title"].startswith(title):
            return w["window_id"]
    return None


class ChromeBackend:
    def find(self, target: Target) -> Handle | None:
        match = target.match or target.url
        pid = _default_profile_pid()
        if pid is None:
            return None  # no Chrome running → caller will create()

        app = _chrome_app(pid)
        if app is None:
            return None
        windows = app.windows()
        if windows is None:
            # SB returns nil when Automation is denied (can't distinguish from a
            # transient miss, but denial is the likely cause worth surfacing).
            raise BackendError(
                "Could not read Chrome tabs — grant the app running deck (your "
                "terminal for dev, Elgato Stream Deck for buttons) Automation "
                "access to Google Chrome in System Settings → Privacy & Security → "
                "Automation, then retry."
            )

        for w in windows:
            tabs = w.tabs()
            if tabs is None:
                continue
            for ti, t in enumerate(tabs):
                url = t.URL() or ""
                if match in url:
                    cur_title = w.title() or ""
                    return Handle(
                        app=APP_NAME,
                        found=True,
                        window_id=_aerospace_id_for_title(cur_title),
                        ref={
                            "sb_app": app,
                            "sb_window": w,
                            "tab_index": ti,
                            "url": url,
                            "title": cur_title,
                        },
                        detail=f"Chrome tab {ti + 1} in window '{cur_title}' ({url})",
                    )
        return None

    def focus(self, handle: Handle) -> None:
        w = handle.ref.get("sb_window")
        ti = handle.ref.get("tab_index")
        app = handle.ref.get("sb_app")
        if w is not None and ti is not None:
            w.setActiveTabIndex_(ti + 1)  # AppleScript tab index is 1-based
            w.setIndex_(1)  # bring the window to the front within Chrome
            if app is not None:
                app.activate()
        if handle.window_id:
            aerospace.focus_window(handle.window_id)
        else:
            focused = aerospace.focused_window()
            if focused:
                aerospace.switch_to(focused["workspace"])

    def create(self, target: Target) -> Handle:
        # Prefer consolidation: if a Chrome window already lives on the target
        # workspace, add the URL as a new TAB there instead of opening a separate
        # window. Keeps one browser-per-workspace with N tabs rather than N
        # windows. Falls back to a new window when that workspace has no Chrome.
        target_ws = aerospace.resolve_workspace(target.workspace)
        if target_ws is not None:
            tabbed = self._add_tab_on_workspace(target, target_ws)
            if tabbed is not None:
                return tabbed

        # No Chrome window on the target workspace → open a new window in the
        # DEFAULT Chrome profile via the binary. We do NOT use AppleScript `make
        # new window`: with extra Chrome instances running under their own
        # --user-data-dir, Apple Events route to an arbitrary instance and can
        # spawn the window in a throwaway, logged-out profile. Launching the
        # binary with --new-window and no --user-data-dir always hands off to the
        # running default-profile instance.
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

    def _add_tab_on_workspace(self, target: Target, target_ws: str) -> Handle | None:
        """Add the URL as a new tab in a Chrome window on `target_ws`.

        Returns a Handle (window_id set to that window) on success, or None if
        there is no Chrome window on that workspace / we can't reach Chrome.
        """
        aero = aerospace.windows_on_workspace(APP_NAME, target_ws)
        if not aero:
            return None
        pid = _default_profile_pid()
        if pid is None:
            return None
        app = _chrome_app(pid)
        if app is None:
            return None
        windows = app.windows()
        if windows is None:
            return None

        # Chrome's SB window id != AeroSpace window-id, so bridge by title:
        # AeroSpace shows "<page> - Google Chrome - <profile>", ScriptingBridge
        # shows the bare "<page>". Match an SB window to an AeroSpace window that
        # is on the target workspace, then we know that window's AeroSpace id.
        for sb in windows:
            title = sb.title() or ""
            if not title:
                continue
            wid = next(
                (w["window_id"] for w in aero if w["title"].startswith(title)),
                None,
            )
            if wid is None:
                continue
            tab = app.classForScriptingClass_("tab").alloc().initWithProperties_(
                {"URL": target.url}
            )
            sb.tabs().addObject_(tab)
            sb.setActiveTabIndex_(len(sb.tabs()))  # select the new (last) tab
            sb.setIndex_(1)  # raise the window within Chrome
            app.activate()
            return Handle(
                app=APP_NAME,
                found=False,
                window_id=wid,
                detail=f"new tab in Chrome window on workspace {target_ws}",
            )
        return None

    def close(self, handle: Handle) -> None:
        # Close just the matched tab via the same PID-addressed SB window object
        # find() resolved it from (its window/tab refs are live for this run).
        w = handle.ref.get("sb_window")
        ti = handle.ref.get("tab_index")
        if w is None or ti is None:
            return
        tabs = w.tabs()
        if tabs is None or ti >= len(tabs):
            return
        tabs[ti].close()

    def new_window_id(self, target: Target, before_ids, timeout: float = 2.0):
        return aerospace.find_new_window(before_ids, APP_NAME, timeout=timeout)

    def describe_create(self, target: Target) -> list[str]:
        target_ws = aerospace.resolve_workspace(target.workspace)
        aero = (
            aerospace.windows_on_workspace(APP_NAME, target_ws) if target_ws else []
        )
        if aero:
            return [
                f"add a new tab -> {target.url} to the Chrome window on workspace "
                f"{target_ws} (window {aero[0]['window_id']})",
            ]
        note = ""
        if target.mode == "app":
            note = "  (mode='app' requested; Phase 1 opens a normal window anyway)"
        return [
            f"{CHROME_BIN} --new-window {target.url}{note}",
            f"(no Chrome window on workspace {target_ws}; opens a new one in the "
            f"default profile)",
        ]

    def describe_focus(self, handle: Handle) -> list[str]:
        ti = handle.ref.get("tab_index")
        lines = [
            f"ScriptingBridge: select tab {(ti + 1) if ti is not None else '?'} "
            f"in '{handle.ref.get('title', '')}' + activate Chrome"
        ]
        if handle.window_id:
            lines.append(f"aerospace focus --window-id {handle.window_id}")
        return lines

    def describe_close(self, handle: Handle) -> list[str]:
        ti = handle.ref.get("tab_index")
        return [
            f"ScriptingBridge: close tab {(ti + 1) if ti is not None else '?'} "
            f"in '{handle.ref.get('title', '')}'"
        ]
