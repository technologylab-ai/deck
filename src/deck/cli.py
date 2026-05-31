"""deck CLI — Typer dispatch for open / list / doctor, Rich output.

Stream Deck buttons call `deck open <target>`. Presses must feel instant, so we
keep imports light and do the minimum work per command.
"""

import json
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
    # Native apps can cold-start slowly (Outlook/Teams take several seconds to
    # draw their first window); browsers usually attach to an already-running
    # instance. new_window_id() returns the instant the window appears, so a
    # generous ceiling only costs wall-clock on an actual failure.
    launch_timeout = 15.0 if target.kind == "app" else 8.0
    new_id = backend.new_window_id(target, before, timeout=launch_timeout)
    if new_id is None:
        _err(
            f"opened {target.name} but its window did not appear within "
            f"{launch_timeout:.0f}s, so it was left where it launched. Either "
            f"retry 'deck open {target.name}', or pin it statically with an "
            f"on-window-detected rule (see aerospace-snippet.toml) so AeroSpace "
            f"places it regardless of launch speed."
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
# close
# --------------------------------------------------------------------------- #


@app.command("close")
def cmd_close(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="target name (see 'deck list')"),
) -> None:
    """Close a target: quit an app, or close the matched browser tab.

    Idempotent — closing an already-closed target is a no-op success. This is
    the verb the Stream Deck plugin calls on a long-press.
    """
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
    _log.info("close %s (kind=%s)", tgt.name, tgt.kind)

    if ctx.obj.dry_run:
        raise typer.Exit(code=_dry_run_close(tgt, backend))

    try:
        raise typer.Exit(code=_live_close(tgt, backend))
    except typer.Exit:
        raise
    except Exception as exc:
        _log.exception("close %s failed", tgt.name)
        _err(f"close {tgt.name} failed: {exc}")
        raise typer.Exit(code=1)


def _live_close(target, backend) -> int:
    handle = backend.find(target)
    if handle is None:
        console.print(f"{target.name} not open (nothing to close)")
        return 0
    backend.close(handle)
    console.print(f"closed {target.name}")
    return 0


def _dry_run_close(target, backend) -> int:
    console.print(
        f"[dim]\\[dry-run][/] close {target.name}  (kind={target.kind})"
    )
    handle = None
    try:
        handle = backend.find(target)
    except Exception as exc:
        console.print(f"  find: error ({exc})")
    if handle is None:
        console.print("  match: not open (nothing to close)")
        return 0
    console.print(f"  match: {handle.detail}")
    for line in backend.describe_close(handle):
        console.print(f"  would close: {line}")
    return 0


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #


@app.command("list")
def cmd_list(
    as_json: bool = typer.Option(
        False, "--json", help="emit JSON (used by the Stream Deck plugin)"
    ),
) -> None:
    """List configured targets."""
    try:
        cfg = config.load()
    except config.ConfigError as exc:
        _err(str(exc))
        raise typer.Exit(code=1)

    if as_json:
        items = []
        for name, t in cfg.targets.items():
            item = {
                "name": name,
                "kind": t.kind,
                "workspace": t.workspace,
                "mode": t.mode,
            }
            if t.kind == "app":
                item["bundle"] = t.bundle
            else:
                item["url"] = t.url
            items.append(item)
        # print() (not Rich) so output is clean JSON for the plugin to parse.
        print(json.dumps(items))
        return

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
# bundle — resolve an app name/query to a bundle id (config helper)
# --------------------------------------------------------------------------- #


@app.command("bundle")
def cmd_bundle(
    query: str = typer.Argument(..., help="app name or fuzzy substring"),
) -> None:
    """Find an app's bundle id to paste into targets.toml."""
    rows: list[tuple[str, str, str]] = []  # (app, bundle, path)
    seen: set[str] = set()

    # Exact-ish path: Launch Services resolves "Microsoft Teams" -> the app.
    exact = _bundle_exact(query)
    if exact:
        rows.append(exact)
        seen.add(exact[1])

    # Fuzzy path: Spotlight metadata for app bundles whose display name matches.
    for app_name, bundle, path in _bundle_fuzzy(query):
        if bundle in seen:
            continue
        seen.add(bundle)
        rows.append((app_name, bundle, path))

    if not rows:
        _err(f"no app found matching '{query}'")
        raise typer.Exit(code=1)

    table = Table(show_edge=False, pad_edge=False, box=None)
    table.add_column("App", style="bold cyan")
    table.add_column("Bundle ID", style="green")
    table.add_column("Path", style="dim")
    for app_name, bundle, path in rows:
        table.add_row(app_name, bundle, path)
    console.print(table)


def _bundle_exact(query: str) -> tuple[str, str, str] | None:
    """Resolve an exact-ish app name to its bundle id via Launch Services.

    Uses NSWorkspace + NSBundle (pure Launch Services / file reads) — NOT
    AppleScript. The old `osascript 'id of app "X"'` approach sent an Apple Event
    that made macOS prompt "<terminal> wants to control <App>" for every lookup;
    a bundle-id query needs no such permission.
    """
    try:
        from AppKit import NSWorkspace  # noqa: PLC0415
        from Foundation import NSBundle  # noqa: PLC0415
    except ImportError:
        return None

    path = NSWorkspace.sharedWorkspace().fullPathForApplication_(query)
    if not path:
        return None
    bundle_obj = NSBundle.bundleWithPath_(path)
    bundle = bundle_obj.bundleIdentifier() if bundle_obj else None
    if not bundle:
        return None
    name = path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".app") or query
    return (name, bundle, path)


def _bundle_fuzzy(query: str) -> list[tuple[str, str, str]]:
    """Spotlight-driven fuzzy lookup of app bundles matching the query."""
    safe = query.replace('"', '').replace("'", "")
    mdfind_q = (
        "kMDItemContentType == 'com.apple.application-bundle' && "
        f"kMDItemDisplayName == '*{safe}*'c"
    )
    try:
        proc = subprocess.run(
            ["/usr/bin/mdfind", mdfind_q],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    out: list[tuple[str, str, str]] = []
    for path in proc.stdout.splitlines():
        path = path.strip()
        if not path:
            continue
        try:
            mp = subprocess.run(
                ["/usr/bin/mdls", "-name", "kMDItemCFBundleIdentifier", "-raw", path],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        bundle = mp.stdout.strip()
        if not bundle or bundle == "(null)":
            continue
        name = path.rsplit("/", 1)[-1].removesuffix(".app")
        out.append((name, bundle, path))
    return out


# --------------------------------------------------------------------------- #
# icon — emit a data:image/png URL for a target (Stream Deck setImage)
# --------------------------------------------------------------------------- #


@app.command("icon")
def cmd_icon(
    target: str = typer.Argument(..., help="target name (see 'deck list')"),
    size: int = typer.Option(288, "--size", help="icon size in pixels"),
    refresh: bool = typer.Option(
        False, "--refresh", help="rebuild the cached icon"
    ),
) -> None:
    """Print a data:image/png;base64 URL for a target's icon."""
    from . import icons

    try:
        cfg = config.load()
    except config.ConfigError as exc:
        _err(str(exc))
        raise typer.Exit(code=1)

    tgt = cfg.targets.get(target)
    if tgt is None:
        _err(f"unknown target '{target}'. Try 'deck list'.")
        raise typer.Exit(code=1)

    try:
        url = icons.data_url(tgt, size=size, refresh=refresh)
    except icons.IconError as exc:
        _err(f"icon {target}: {exc}")
        raise typer.Exit(code=1)
    # Bare print so the plugin captures only the data URL (no Rich styling).
    print(url)


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

    # Both Safari and Chrome targets drive the browser via Apple Events
    # (Automation). Safari via plain AppleScript; Chrome via ScriptingBridge
    # addressed to the default-profile PID. Without Automation they fail at press
    # time (osascript -1743 / ScriptingBridge returns nil).
    browsers = {"safari": "Safari", "chrome": "Google Chrome"}
    used = {t.kind for t in cfg.targets.values()} & browsers.keys()
    for kind in sorted(used):
        app_name = browsers[kind]
        state = _automation_state(app_name)
        if state == "ok":
            _ok("automation:", app_name)
        elif state == "denied":
            _bad(
                "automation:",
                f"{app_name} NOT AUTHORIZED — grant the app running deck (your "
                f"terminal for dev, Elgato Stream Deck for buttons) Automation "
                f"access to {app_name} in System Settings › Privacy & Security › "
                f"Automation (or run 'deck open' once and approve the prompt).",
            )
            ok = False
        elif state == "not-running":
            console.print(
                f"[yellow]–[/] automation: {app_name} not running "
                f"(can't verify until launched)"
            )
        else:
            console.print(f"[yellow]?[/] automation: {app_name} ({state})")

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
