"""deck CLI — argparse dispatch for open / list / doctor.

Stream Deck buttons call `deck open <target>`. Presses must feel instant, so we
keep imports light and do the minimum work per command.
"""

import argparse
import shutil
import subprocess
import sys

from . import __version__, aerospace, config
from .backends import get_backend
from .logging import get_logger, log_path

_log = get_logger()


def _err(msg: str) -> None:
    print(f"deck: {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# open
# --------------------------------------------------------------------------- #


def cmd_open(args) -> int:
    try:
        cfg = config.load()
    except config.ConfigError as exc:
        _err(str(exc))
        return 1

    target = cfg.targets.get(args.target)
    if target is None:
        _err(f"unknown target '{args.target}'. Try 'deck list'.")
        return 1
    if cfg.errors and any(args.target in e for e in cfg.errors):
        for e in cfg.errors:
            if args.target in e:
                _err(e)
        return 1

    backend = get_backend(target)
    _log.info("open %s (kind=%s, ws=%s)", target.name, target.kind, target.workspace)

    if args.dry_run:
        return _dry_run_open(target, backend)

    try:
        return _live_open(target, backend)
    except Exception as exc:  # surface a clean error; details go to the log
        _log.exception("open %s failed", target.name)
        _err(f"open {target.name} failed: {exc}")
        return 1


def _live_open(target, backend) -> int:
    handle = backend.find(target)

    if handle is not None:
        backend.focus(handle)
        # Switch to whatever workspace the focused window lives on.
        ws = None
        if handle.window_id:
            ws = aerospace.workspace_of(handle.window_id)
        if ws is None:
            focused = aerospace.focused_window()
            if focused:
                ws = focused["workspace"]
        if ws is not None:
            aerospace.switch_to(ws)
        print(f"focused {target.name} on workspace {ws or '?'}")
        return 0

    # Not open yet: create, resolve the new window, place + switch.
    before = aerospace.window_ids()
    handle = backend.create(target)
    new_id = backend.new_window_id(target, before, timeout=2.0)
    if new_id is None:
        _err(
            f"opened {target.name} but could not find its new window to place it "
            f"(it may still be launching). Configure an on-window-detected rule "
            f"or retry."
        )
        return 1
    aerospace.place_and_switch(new_id, target.workspace)
    print(f"opened {target.name} on workspace {target.workspace} (window {new_id})")
    return 0


def _dry_run_open(target, backend) -> int:
    print(f"[dry-run] open {target.name}  (kind={target.kind}, ws={target.workspace})")
    # find() is read-only (enumerates tabs / running apps), safe in dry-run.
    handle = None
    try:
        handle = backend.find(target)
    except Exception as exc:
        print(f"  find: error ({exc})")

    if handle is not None:
        print(f"  match: {handle.detail}")
        for line in backend.describe_focus(handle):
            print(f"  would focus: {line}")
        if handle.window_id:
            print(f"  would: aerospace workspace <ws of window {handle.window_id}>")
        else:
            print("  would: switch to the focused window's workspace")
    else:
        print("  match: no existing window")
        for line in backend.describe_create(target):
            print(f"  would create: {line}")
        print(
            f"  would place: aerospace move-node-to-workspace --window-id <new> "
            f"{target.workspace} --focus-follows-window"
        )
        print(f"  would: aerospace workspace {target.workspace}")
    return 0


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #


def cmd_list(args) -> int:
    try:
        cfg = config.load()
    except config.ConfigError as exc:
        _err(str(exc))
        return 1

    if not cfg.targets:
        print("no targets configured")
        return 0

    width = max(len(n) for n in cfg.targets)
    for name, t in cfg.targets.items():
        if t.kind == "app":
            desc = f"app {t.bundle}"
        else:
            desc = f"{t.kind} {t.url}"
            if t.mode == "app":
                desc += " [mode=app]"
        print(f"{name:<{width}}  ws {t.workspace:<3}  {desc}")

    for e in cfg.errors:
        _err(e)
    return 0


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #


def cmd_doctor(args) -> int:
    ok = True

    print(f"deck {__version__}")
    print(f"python: {sys.executable} ({sys.version.split()[0]})")
    print(f"log:    {log_path()}")

    # config
    try:
        cfg = config.load()
        print(f"config: {cfg.path}  ({len(cfg.targets)} targets)")
        for e in cfg.errors:
            print(f"  ERROR {e}")
            ok = False
    except config.ConfigError as exc:
        print(f"config: ERROR {exc}")
        return 1

    # aerospace
    if shutil.which("aerospace") or _exists(aerospace.AEROSPACE):
        print(f"aerospace: {aerospace.AEROSPACE} ✓")
    else:
        print(f"aerospace: MISSING at {aerospace.AEROSPACE}")
        ok = False

    # chrome binary
    chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if _exists(chrome_bin):
        print(f"chrome:    {chrome_bin} ✓")
    else:
        print(f"chrome:    not found at {chrome_bin} (only needed for chrome targets)")

    # osascript
    if _exists("/usr/bin/osascript"):
        print("osascript: /usr/bin/osascript ✓")
    else:
        print("osascript: MISSING at /usr/bin/osascript")
        ok = False

    # bundle ids for app targets
    for name, t in cfg.targets.items():
        if t.kind == "app" and t.bundle:
            if _app_exists(t.bundle):
                print(f"bundle:    {t.bundle} ({name}) ✓")
            else:
                print(f"bundle:    {t.bundle} ({name}) NOT FOUND")
                ok = False

    # Automation (Apple Events) permission for each browser the config uses.
    # Without it, browser targets fail at press time with osascript error -1743.
    browsers = {"safari": "Safari", "chrome": "Google Chrome"}
    used = {t.kind for t in cfg.targets.values()} & browsers.keys()
    for kind in sorted(used):
        app_name = browsers[kind]
        state = _automation_state(app_name)
        if state == "ok":
            print(f"automation: {app_name} ✓")
        elif state == "denied":
            print(
                f"automation: {app_name} NOT AUTHORIZED — grant this terminal "
                f"Automation access to {app_name} in System Settings › Privacy & "
                f"Security › Automation (or just run 'deck open' once and approve "
                f"the prompt)."
            )
            ok = False
        elif state == "not-running":
            print(f"automation: {app_name} not running (can't verify until launched)")
        else:
            print(f"automation: {app_name} ? ({state})")

    print("status:", "ok" if ok else "problems found")
    return 0 if ok else 1


def _exists(path: str) -> bool:
    from pathlib import Path

    return Path(path).exists()


def _app_exists(bundle: str) -> bool:
    """Resolve a bundle id to an app path via Launch Services (osascript)."""
    try:
        proc = subprocess.run(
            ["/usr/bin/osascript", "-e", f'id of app id "{bundle}"'],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _automation_state(app_name: str) -> str:
    """Probe Apple Events authorization for a browser without launching it.

    Returns 'ok', 'denied' (TCC error -1743), 'not-running', or an error string.
    """
    # Don't launch the app just to probe; only a running app can be verified.
    try:
        running = subprocess.run(
            ["/usr/bin/osascript", "-e", f'application "{app_name}" is running'],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    if running.stdout.strip() != "true":
        return "not-running"

    try:
        proc = subprocess.run(
            ["/usr/bin/osascript", "-e", f'tell application "{app_name}" to count windows'],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    if proc.returncode == 0:
        return "ok"
    if "-1743" in proc.stderr or "Not authorized" in proc.stderr:
        return "denied"
    return proc.stderr.strip() or f"exit {proc.returncode}"


# --------------------------------------------------------------------------- #
# arg parsing
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="deck",
        description="Idempotently open apps/tabs on AeroSpace workspaces.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would happen without acting",
    )
    p.add_argument("--version", action="version", version=f"deck {__version__}")

    sub = p.add_subparsers(dest="command", required=True)

    p_open = sub.add_parser("open", help="open or focus a target")
    p_open.add_argument("target", help="target name (see 'deck list')")
    p_open.set_defaults(func=cmd_open)

    p_list = sub.add_parser("list", help="list configured targets")
    p_list.set_defaults(func=cmd_list)

    p_doctor = sub.add_parser("doctor", help="sanity-check the environment")
    p_doctor.set_defaults(func=cmd_doctor)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
