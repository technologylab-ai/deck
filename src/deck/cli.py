"""deck CLI — Typer dispatch for open / list / doctor, Rich output.

Stream Deck buttons call `deck open <target>`. Presses must feel instant, so we
keep imports light and do the minimum work per command.
"""

import shutil
import subprocess
import sys
from dataclasses import dataclass

import typer
from rich.console import Console
from rich.table import Table

from . import __version__, aerospace, config
from .backends import get_backend
from .logging import get_logger, log_path

_log = get_logger()

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    name="deck",
    help="Idempotently open apps/tabs on AeroSpace workspaces.",
    no_args_is_help=True,
    add_completion=True,
)


@dataclass
class State:
    """Per-invocation flags stashed on the Typer context object."""

    dry_run: bool = False


def _err(msg: str) -> None:
    err_console.print(f"[red]deck:[/] {msg}")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"deck {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    ctx: typer.Context,
    dry_run: bool = typer.Option(
        False, "--dry-run", help="print what would happen without acting"
    ),
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="show version and exit",
    ),
) -> None:
    """deck — open or focus apps/tabs on AeroSpace workspaces."""
    ctx.obj = State(dry_run=dry_run)


# --------------------------------------------------------------------------- #
# open
# --------------------------------------------------------------------------- #


@app.command("open")
def cmd_open(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="target name (see 'deck list')"),
) -> None:
    """Open or focus a target."""
    try:
        cfg = config.load()
    except config.ConfigError as exc:
        _err(str(exc))
        raise typer.Exit(code=1)

    tgt = cfg.targets.get(target)
    if tgt is None:
        _err(f"unknown target '{target}'. Try 'deck list'.")
        raise typer.Exit(code=1)
    if cfg.errors and any(target in e for e in cfg.errors):
        for e in cfg.errors:
            if target in e:
                _err(e)
        raise typer.Exit(code=1)

    backend = get_backend(tgt)
    _log.info("open %s (kind=%s, ws=%s)", tgt.name, tgt.kind, tgt.workspace)

    if ctx.obj.dry_run:
        raise typer.Exit(code=_dry_run_open(tgt, backend))

    try:
        raise typer.Exit(code=_live_open(tgt, backend))
    except typer.Exit:
        raise
    except Exception as exc:  # surface a clean error; details go to the log
        _log.exception("open %s failed", tgt.name)
        _err(f"open {tgt.name} failed: {exc}")
        raise typer.Exit(code=1)


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
        console.print(f"focused {target.name} on workspace {ws or '?'}")
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
    console.print(
        f"opened {target.name} on workspace {target.workspace} (window {new_id})"
    )
    return 0


def _dry_run_open(target, backend) -> int:
    console.print(
        f"[dim]\\[dry-run][/] open {target.name}  "
        f"(kind={target.kind}, ws={target.workspace})"
    )
    # find() is read-only (enumerates tabs / running apps), safe in dry-run.
    handle = None
    try:
        handle = backend.find(target)
    except Exception as exc:
        console.print(f"  find: error ({exc})")

    if handle is not None:
        console.print(f"  match: {handle.detail}")
        for line in backend.describe_focus(handle):
            console.print(f"  would focus: {line}")
        if handle.window_id:
            console.print(
                f"  would: aerospace workspace <ws of window {handle.window_id}>"
            )
        else:
            console.print("  would: switch to the focused window's workspace")
    else:
        console.print("  match: no existing window")
        for line in backend.describe_create(target):
            console.print(f"  would create: {line}")
        console.print(
            f"  would place: aerospace move-node-to-workspace --window-id <new> "
            f"{target.workspace} --focus-follows-window"
        )
        console.print(f"  would: aerospace workspace {target.workspace}")
    return 0


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #


@app.command("list")
def cmd_list() -> None:
    """List configured targets."""
    try:
        cfg = config.load()
    except config.ConfigError as exc:
        _err(str(exc))
        raise typer.Exit(code=1)

    if not cfg.targets:
        console.print("no targets configured")
        return

    table = Table(show_edge=False, pad_edge=False, box=None)
    table.add_column("Name", style="bold cyan")
    table.add_column("Workspace", justify="right")
    table.add_column("Kind")
    table.add_column("Target")

    for name, t in cfg.targets.items():
        if t.kind == "app":
            target_desc = t.bundle or ""
        else:
            target_desc = t.url or ""
            if t.mode == "app":
                target_desc += " [magenta]\\[mode=app][/]"
        table.add_row(name, t.workspace, t.kind, target_desc)

    console.print(table)

    for e in cfg.errors:
        _err(e)


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #


def _ok(label: str, detail: str) -> None:
    console.print(f"[green]✓[/] {label} {detail}")


def _bad(label: str, detail: str) -> None:
    console.print(f"[red]✗[/] {label} {detail}")


@app.command("doctor")
def cmd_doctor() -> None:
    """Sanity-check the environment."""
    ok = True

    console.print(f"[bold]deck {__version__}[/]")
    console.print(f"python: {sys.executable} ({sys.version.split()[0]})")
    console.print(f"log:    {log_path()}")

    # config
    try:
        cfg = config.load()
        console.print(f"config: {cfg.path}  ({len(cfg.targets)} targets)")
        for e in cfg.errors:
            _bad("config:", e)
            ok = False
    except config.ConfigError as exc:
        _bad("config:", str(exc))
        raise typer.Exit(code=1)

    # aerospace
    if shutil.which("aerospace") or _exists(aerospace.AEROSPACE):
        _ok("aerospace:", aerospace.AEROSPACE)
    else:
        _bad("aerospace:", f"MISSING at {aerospace.AEROSPACE}")
        ok = False

    # chrome binary
    chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if _exists(chrome_bin):
        _ok("chrome:", chrome_bin)
    else:
        console.print(
            f"[yellow]–[/] chrome:    not found at {chrome_bin} "
            f"(only needed for chrome targets)"
        )

    # osascript
    if _exists("/usr/bin/osascript"):
        _ok("osascript:", "/usr/bin/osascript")
    else:
        _bad("osascript:", "MISSING at /usr/bin/osascript")
        ok = False

    # bundle ids for app targets
    for name, t in cfg.targets.items():
        if t.kind == "app" and t.bundle:
            if _app_exists(t.bundle):
                _ok("bundle:", f"{t.bundle} ({name})")
            else:
                _bad("bundle:", f"{t.bundle} ({name}) NOT FOUND")
                ok = False

    kinds = {t.kind for t in cfg.targets.values()}

    # Safari targets use Apple Events (Automation). Without it they fail at press
    # time with osascript error -1743.
    if "safari" in kinds:
        state = _automation_state("Safari")
        if state == "ok":
            _ok("automation:", "Safari")
        elif state == "denied":
            _bad(
                "automation:",
                "Safari NOT AUTHORIZED — grant this terminal Automation access to "
                "Safari in System Settings › Privacy & Security › Automation (or "
                "run 'deck open' once and approve the prompt).",
            )
            ok = False
        elif state == "not-running":
            console.print(
                "[yellow]–[/] automation: Safari not running "
                "(can't verify until launched)"
            )
        else:
            console.print(f"[yellow]?[/] automation: Safari ({state})")

    # Chrome targets dedup via the Accessibility (AX) API, not Apple Events —
    # robust to the user's multiple --app Chrome instances. Without Accessibility,
    # find() can't read tab URLs and every press opens a fresh window.
    if "chrome" in kinds:
        state = _accessibility_state()
        if state == "ok":
            _ok("accessibility:", "granted (Chrome tab dedup)")
        elif state == "denied":
            _bad(
                "accessibility:",
                "NOT GRANTED — give the app running deck (your terminal for dev, "
                "Elgato Stream Deck for buttons) Accessibility access in System "
                "Settings › Privacy & Security › Accessibility. Chrome dedup needs "
                "it; without it every press opens a new window.",
            )
            ok = False
        else:
            console.print(f"[yellow]?[/] accessibility: ({state})")

    if ok:
        console.print("status: [green]ok[/]")
    else:
        console.print("status: [red]problems found[/]")
        raise typer.Exit(code=1)


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


def _accessibility_state() -> str:
    """Probe whether the app controlling deck has Accessibility (AX) access.

    Returns 'ok', 'denied' (TCC error -25211), or an error string. Reading a UI
    element attribute is AX-gated; merely listing processes is not, so we count a
    process's windows to force the check.
    """
    try:
        proc = subprocess.run(
            [
                "/usr/bin/osascript",
                "-e",
                'tell application "System Events" to return (count of windows of '
                "(first application process whose frontmost is true))",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    if proc.returncode == 0:
        return "ok"
    if "-25211" in proc.stderr or "assistive access" in proc.stderr:
        return "denied"
    return proc.stderr.strip() or f"exit {proc.returncode}"


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


def main() -> None:
    """Console-script entrypoint (see [project.scripts] in pyproject.toml)."""
    app()
