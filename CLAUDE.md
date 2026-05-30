# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

**Phase 1 is built** (config loader, CLI, dry-run, AeroSpace placement, and the `app`/`safari`/
`chrome` normal-tab backends). The full build spec lives in `claude-code-prompt.md` (the canonical
source of truth for design decisions). Remaining: Phase 2 (Chrome `--app=<url>` window mode) and
Phase 3 (Stream Deck wiring). Stop after each phase for the user to test.

### Layout & commands

Packaged with uv (`pyproject.toml`); the entrypoint is the `deck` console script
(`deck.cli:main`). The package lives at `src/deck/` (standard hatchling src-layout). Install with
`uv tool install --editable .` (shim at `~/.local/bin/deck`); for in-repo dev use `uv run deck …`
or `python -m deck`. `.python-version` pins 3.12 and uv auto-provisions it (3.11+ needed for
`tomllib`).

- `deck list` — list configured targets
- `deck doctor` — sanity-check config, binaries, interpreter, log path
- `deck open <target>` — open or focus (the verb Stream Deck calls)
- `deck --dry-run open <target>` — print the plan without acting
- Config: `~/.config/deck/targets.toml` (honors `XDG_CONFIG_HOME`); template in `targets.toml.example`
- Log: `~/.local/state/deck/deck.log` (honors `XDG_STATE_HOME`)
- Compile check: `python3.12 -m py_compile src/deck/*.py src/deck/backends/*.py`

## What `deck` is

A small, **stdlib-only** Python CLI that opens macOS apps and browser tabs on specific
**AeroSpace** workspaces **idempotently** — open if not already open, otherwise just focus.
Invoked one target at a time by Elgato Stream Deck buttons, e.g. `deck open synadia-gmail`.
Presses must feel instant (fast startup).

## Core architectural invariant: the browser boundary does the dedup

This is the key idea — internalize it before changing browser logic:

- **Synadia** Google apps (Gmail, Calendar, …) live in **Safari**.
- **Personal** apps (e.g. HEY) live in **Chrome** (default profile).

Because Synadia and personal Google live in *physically different browsers*, profile-aware dedup
is **not needed**. `synadia-gmail` inspects only Safari tabs and can never resolve to personal
Gmail in Chrome. Do **not** build CDP / `--remote-debugging-port` logic now — it's explicitly
out of scope (see "Future" in the spec). Keep the design open to per-Chrome-profile dedup later
via a `profile` field, but don't build it.

## Backend interface

Targets are config-driven; the target's `type`/`browser` selects a pluggable backend. Keep all
backends behind one interface:

```
find(target) -> handle | None
focus(handle)
create(target) -> handle
place(handle, workspace)
```

Three backends:
- **`app`** — native macOS app via `open -b <bundle-id>`; dedup = is the app running. These can
  *also* be pinned via AeroSpace `on-window-detected` rules.
- **`safari`** — open/focus a URL via AppleScript (`osascript`); enumerate windows+tabs, match
  the URL, `set current tab` + `activate`, else `make new tab`. Path for all Synadia targets.
- **`chrome`** — dedup via the **Accessibility (AX) API**, not AppleScript. The user runs extra
  Chrome instances (`--app=<url> --user-data-dir=…` for OBS capture / slides / a demo); they all
  share bundle id `com.google.Chrome`, so `tell application "Google Chrome"` Apple Events route to
  an arbitrary instance and break AppleScript dedup/focus (and can spawn windows in a throwaway
  profile). Instead, `find()` reads each Chrome window's active-tab URL from the window-level
  `AXDocument` attribute (instant, no traversal, PID-targeted — immune to how many Chrome instances
  run), matches `target.match`, bridges the AX window title to the AeroSpace window-id, and `focus()`
  uses `aerospace focus --window-id`. `create()` opens the URL via `Google Chrome --new-window <url>`
  in the **default profile** (no AppleScript, no stray-profile risk). Requires **Accessibility**
  permission for the app running deck (terminal for dev, Elgato Stream Deck for buttons). Limitation:
  `AXDocument` is the active tab only, so a target sitting as a background tab in a shared window
  isn't matched — fine for deck-opened single-purpose windows. Phase 2 (`mode = "app"`, `--app=<url>`)
  is still later. See `memory/deck-chrome-dedup-accessibility.md`.

## AeroSpace integration

- **Never hardcode workspace names** — they use a numerical postfix and must be read from the
  user's `aerospace.toml`.
- After opening a new window, find it by polling `aerospace list-windows --all` with `--format`
  to get window-id + app + title. Handle the race where the window appears a beat later (short
  retry loop with timeout), then move it by window-id and switch to its workspace.
- Consult `aerospace --help` / man pages for exact flags rather than guessing.
- Also emit static `on-window-detected` rules (e.g. Outlook → comms workspace) as a paste-in
  snippet for `aerospace.toml`.

## Config

TOML at `~/.config/deck/targets.toml`, loaded with `tomllib`. One table per target. `browser`
implies a web target; `type = "app"` is a native app. Adding a target must require editing TOML
**only** — no code and no Stream Deck changes.

## CLI surface

- `deck open <target>` — main verb Stream Deck calls.
- `deck list` — list configured targets.
- `deck --dry-run open <target>` — print matched tab / launch cmd / placement without acting.
- `deck doctor` — sanity-check config, binary paths, AeroSpace presence.

Logs to a file; clear errors.

## Hard constraints

- **Dependencies are allowed and managed by uv.** The CLI uses **Typer + Rich** (`pyproject.toml`
  pins them). Still macOS-only: native apps via `open -b`, Safari via AppleScript (`osascript`),
  Chrome dedup via the **Accessibility (AX) API** (`osascript` → System Events `AXDocument`),
  AeroSpace via its CLI. The config loader uses `tomllib` (stdlib).
- **Permissions:** Safari targets need Automation (Apple Events); Chrome targets need Accessibility
  (grant the terminal for dev, Elgato Stream Deck for buttons). `deck doctor` checks both.
- Verify the user's environment (Chrome binary path, workspace names, URLs); leave clearly-marked
  `TODO` placeholders for anything that can't be determined rather than guessing.
