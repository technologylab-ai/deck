# deck

A small, **stdlib-only** Python CLI that opens macOS apps and browser tabs on
specific [AeroSpace](https://nikitabobko.github.io/AeroSpace/) workspaces
**idempotently** — open if not already open, otherwise just focus. Built to be
driven one target at a time by Elgato Stream Deck buttons (`deck open <target>`),
so presses feel instant.

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
- Python **3.11+** (for `tomllib`). System Python 3.9 won't do; the `deck`
  entrypoint locates a Homebrew `python3.11/3.12/3.13` itself.
- No third-party packages.

## Install

```sh
git clone <this repo> streamdeck-tool
cd streamdeck-tool
cp targets.toml.example ~/.config/deck/targets.toml   # then edit
# optional: put `deck` on your PATH
ln -s "$PWD/deck" /opt/homebrew/bin/deck
```

`~/.config/deck/targets.toml` honors `XDG_CONFIG_HOME` if set.

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
deck                  # shell entrypoint: finds python3.11+, execs the package
src/deck/             # stdlib-only package (python -m deck)
  cli.py              # argparse: open / list / doctor; --dry-run
  config.py           # load + validate targets.toml
  aerospace.py        # enumerate windows, place + switch
  logging.py          # file logger
  backends/           # app / safari / chrome behind one find/focus/create/place
targets.toml.example
aerospace-snippet.toml
```
