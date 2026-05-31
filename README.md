# deck

A small Python CLI that opens macOS apps and browser tabs on specific
[AeroSpace](https://nikitabobko.github.io/AeroSpace/) workspaces **idempotently**
— open if not already open, otherwise just focus. Built to be driven one target
at a time by Elgato Stream Deck buttons (`deck open <target>`), so presses feel
instant. Packaged with [uv](https://docs.astral.sh/uv/); CLI built on Typer + Rich.

> **Status:** Phases 1 & 3 — config loader, CLI, dry-run, AeroSpace placement, the
> `app` / `safari` / `chrome` (normal tab) backends, and a dedicated **Stream Deck
> plugin** (tap to open/focus, long-press to close). Phase 2 (Chrome `--app=<url>`
> windows) is still to come; the plugin already drives it once built.

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
deck list                         # show configured targets (--json for the plugin)
deck doctor                       # sanity-check config, binaries, interpreter
deck open synadia-gmail           # open or focus, then switch to its workspace
deck close synadia-gmail          # quit the app / close the matched tab
deck --dry-run open synadia-gmail # print the plan without acting
deck bundle teams                 # find an app's bundle id for targets.toml
deck icon hey                     # data:image/png URL for the button (favicon/app icon)
```

`deck open <target>` is the verb Stream Deck calls on a tap. It:

1. Looks for an existing window/tab (read-only). If found → focus it and switch
   AeroSpace to that window's workspace.
2. Otherwise → open it, wait for the new window to appear, move it to the
   target's workspace, and switch there.

`deck close <target>` is the inverse (Stream Deck long-press): it quits a native
app, or closes the matched browser tab. Both verbs are idempotent.

### Config helpers

- `deck bundle <query>` resolves an app name (or fuzzy substring) to a bundle id
  via Launch Services + Spotlight — e.g. `deck bundle teams` →
  `com.microsoft.teams2`. Paste the result into a `type = "app"` target.
- `deck icon <target>` prints a `data:image/png;base64,…` URL: the site favicon
  (via DuckDuckGo's icon service) for web targets, or the macOS app icon (via
  `NSWorkspace`) for app targets. Cached under `~/.cache/deck/icons/`; `--refresh`
  rebuilds. The Stream Deck plugin feeds this straight into `setImage`.

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

[chatgpt]
type = "app"
bundle = "com.openai.chat"
workspace = "current"         # open on the focused workspace; don't move it
```

`workspace` is an AeroSpace workspace name, or the special value `"current"` to
open the target on whatever workspace is focused and leave it there (no move).
What "already open" means depends on the target type:

- **App `current` target** — global: if the app is running anywhere, a press
  focuses it where it lives; otherwise it launches on your focused workspace.
  Handy for a single-instance "summon it near me" app like ChatGPT.
- **Browser `current` target** — *workspace-local*: only a matching tab **on the
  workspace you're on** counts as open. A matching tab on another workspace is
  ignored, so a press opens a fresh one **here** instead of yanking you away.
  This is what you want for a browser app you keep several tabs of (e.g. Gemini
  conversations scattered across workspaces).

See `targets.toml.example` for the full set.

## AeroSpace placement

`deck` moves freshly-opened windows with
`aerospace move-node-to-workspace --window-id <id> <ws> --focus-follows-window`
and then `aerospace workspace <ws>`. For native apps you can *also* pin them
statically — paste the rules from `aerospace-snippet.toml` into
`~/.config/aerospace/aerospace.toml` and run `aerospace reload-config`.

## Stream Deck plugin

A dedicated Elgato **SDK v2** plugin lives in `streamdeck-plugin/`. It's a thin
shell: every behavior shells out to `~/.local/bin/deck`, so all real logic stays
in Python and adding a target to `targets.toml` needs **no plugin change**.

- **Tap** a key → `deck open <target>` (open or focus on its workspace).
- **Long-press** (>0.5s) → `deck close <target>` (quit the app / close the tab).
- The button **icon** auto-appears from `deck icon` (favicon or app icon); the
  **title** defaults to the target name (override it in the Property Inspector).
- The target **dropdown** is populated live from `deck list --json`.

Stream Deck launches commands with a minimal `PATH` (no Homebrew), so the plugin
calls `deck` by its absolute shim path `~/.local/bin/deck` — make sure
`uv tool install --editable .` has been run.

> **Step-by-step user guide:** [`docs/user-guide.html`](docs/user-guide.html) —
> install, add a button, gestures, adding targets, permissions, troubleshooting.

### Build & install

```sh
cd streamdeck-plugin
npm install
npm run build                                   # → ai.technologylab.deck.sdPlugin/bin/plugin.js

npm i -g @elgato/cli                            # provides the `streamdeck` CLI
streamdeck dev                                  # enable developer mode (required)
streamdeck link ai.technologylab.deck.sdPlugin  # register the plugin
```

The built `*.sdPlugin/` is committed, so it installs without a build if you
prefer. Then in the Stream Deck app: drag **Open Target** onto a key, pick a
target from the dropdown — the icon appears. Tap to open, long-press to close.
For a distributable file, `streamdeck pack ai.technologylab.deck.sdPlugin`
produces an `.streamDeckPlugin`.

### Permissions

The first time a **Chrome/Safari** target is pressed *from a button*, macOS shows
a one-time "**Elgato Stream Deck** wants to control Google Chrome/Safari"
Automation prompt — approve it. The same applies to `deck close` on an **app**
target (a quit Apple Event). TCC attributes these to Stream Deck.app (which hosts
the plugin), so it's a single grant per app, not per target. `deck doctor`
reports Automation status.

## Logs

`~/.local/state/deck/deck.log` (honors `XDG_STATE_HOME`). The plugin itself logs
under `streamdeck-plugin/ai.technologylab.deck.sdPlugin/logs/` (gitignored).

## Layout

```
pyproject.toml        # uv package: deps (typer, rich) + `deck` console script
.python-version       # uv auto-provisions this interpreter (3.12)
src/deck/             # package (also runnable via `python -m deck`)
  cli.py              # Typer + Rich: open / close / list / doctor / bundle / icon; --dry-run
  config.py           # load + validate targets.toml
  aerospace.py        # enumerate windows, place + switch
  icons.py            # favicons (DuckDuckGo) + app icons (NSWorkspace) → data URLs
  logging.py          # file logger
  backends/           # app / safari / chrome behind one find/focus/create/close/place
targets.toml.example
aerospace-snippet.toml
streamdeck-plugin/    # Elgato SDK v2 plugin (thin shell over the `deck` CLI)
docs/design-decisions.html  # why the Chrome backend works the way it does
```

## Design notes

`docs/design-decisions.html` is a self-contained write-up of the reasoning,
dead ends, and live evidence behind the Chrome backend — the multi-instance
Apple-Events trap and why dedup goes through ScriptingBridge addressed to a
specific Chrome PID. Read it before changing browser logic; it captures what the
code alone can't.
