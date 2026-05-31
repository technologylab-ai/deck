# deck

A small Python CLI that opens macOS apps and browser tabs on specific
[AeroSpace](https://nikitabobko.github.io/AeroSpace/) workspaces **idempotently**
— open if not already open, otherwise just focus. Built to be driven one target
at a time by Elgato Stream Deck buttons (`deck open <target>`), so presses feel
instant. Packaged with [uv](https://docs.astral.sh/uv/); CLI built on Typer + Rich.

> **Status:** Phase 1 — config loader, CLI, dry-run, AeroSpace placement, and the
> `app` / `safari` / `chrome` (normal tab) backends. Phase 2 adds Chrome
> `--app=<url>` windows; Phase 3 wires up Stream Deck.

## Why two browsers

- **Synadia** Google apps (Gmail, Calendar, …) live in **Safari**.
- **Personal** apps (e.g. HEY) live in **Chrome**.

Because they live in physically different browsers, dedup never needs to be
profile-aware: `synadia-gmail` only inspects Safari tabs and can never resolve to
personal Gmail in Chrome. The browser boundary *is* the isolation.

## Requirements

- macOS with [AeroSpace](https://github.com/nikitabobko/AeroSpace) at
  `/opt/homebrew/bin/aerospace`.
- [uv](https://docs.astral.sh/uv/). Python **3.11+** is required (for `tomllib`);
  uv reads `.python-version` and auto-provisions 3.12 on first run — no manual
  interpreter setup.
- **Automation** (Apple Events) permission for the app that runs deck (your
  terminal during dev, the **Elgato Stream Deck** app for buttons) → Safari and
  Google Chrome. Chrome tab dedup talks to the default-profile Chrome via
  ScriptingBridge, so it sees background tabs too. The first Chrome press shows a
  one-time "deck wants to control Google Chrome" prompt — approve it. `deck
  doctor` reports whether Automation is granted.

## Install

```sh
git clone <this repo> streamdeck-tool
cd streamdeck-tool
uv tool install --editable .                          # installs the `deck` shim
cp targets.toml.example ~/.config/deck/targets.toml   # then edit
```

`uv tool install --editable .` puts a `deck` console script on your PATH (at
`~/.local/bin/deck`) backed by the working tree, so source edits take effect
without reinstalling. For in-repo development without installing, use
`uv run deck …`. `~/.config/deck/targets.toml` honors `XDG_CONFIG_HOME` if set.

Optional shell completion (Typer): `deck --install-completion`.

## Usage

```sh
deck list                         # show configured targets
deck doctor                       # sanity-check config, binaries, interpreter
deck open synadia-gmail           # open or focus, then switch to its workspace
deck --dry-run open synadia-gmail # print the plan without acting
```

`deck open <target>` is the verb Stream Deck calls. It:

1. Looks for an existing window/tab (read-only). If found → focus it and switch
   AeroSpace to that window's workspace.
2. Otherwise → open it, wait for the new window to appear, move it to the
   target's workspace, and switch there.

## Config

TOML at `~/.config/deck/targets.toml`, one table per target. Adding a target
requires editing **this file only** — no code, no Stream Deck changes.

```toml
[synadia-gmail]
browser = "safari"            # safari | chrome  (web target)
url = "https://mail.google.com"
workspace = "7"               # AeroSpace workspace name
match = "mail.google.com"     # dedup substring; defaults to url

[outlook]
type = "app"                  # native macOS app
bundle = "com.microsoft.Outlook"
workspace = "1"
```

See `targets.toml.example` for the full set.

## AeroSpace placement

`deck` moves freshly-opened windows with
`aerospace move-node-to-workspace --window-id <id> <ws> --focus-follows-window`
and then `aerospace workspace <ws>`. For native apps you can *also* pin them
statically — paste the rules from `aerospace-snippet.toml` into
`~/.config/aerospace/aerospace.toml` and run `aerospace reload-config`.

## Logs

`~/.local/state/deck/deck.log` (honors `XDG_STATE_HOME`).

## Layout

```
pyproject.toml        # uv package: deps (typer, rich) + `deck` console script
.python-version       # uv auto-provisions this interpreter (3.12)
src/deck/             # package (also runnable via `python -m deck`)
  cli.py              # Typer + Rich: open / list / doctor; --dry-run
  config.py           # load + validate targets.toml
  aerospace.py        # enumerate windows, place + switch
  logging.py          # file logger
  backends/           # app / safari / chrome behind one find/focus/create/place
targets.toml.example
aerospace-snippet.toml
docs/design-decisions.html  # why the Chrome backend works the way it does
```

## Design notes

`docs/design-decisions.html` is a self-contained write-up of the reasoning,
dead ends, and live evidence behind the Chrome backend — the multi-instance
Apple-Events trap and why dedup goes through ScriptingBridge addressed to a
specific Chrome PID. Read it before changing browser logic; it captures what the
code alone can't.
