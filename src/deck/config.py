"""Config loading and validation for deck.

Reads ~/.config/deck/targets.toml (honoring XDG_CONFIG_HOME) with tomllib.
One TOML table per target. The discriminator:

  * ``type = "app"``      -> native macOS app backend (needs ``bundle``)
  * ``browser = "safari"`` or ``"chrome"`` -> web backend (needs ``url``)

Validation never raises for an individual bad target; instead every problem is
collected into ``ConfigResult.errors`` so ``deck doctor`` can report them all.
A hard parse/IO failure (missing file, bad TOML) does raise ``ConfigError``.
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_VALID_BROWSERS = ("safari", "chrome")
_VALID_MODES = ("tab", "app")

# Sentinel workspace value: open the target on whatever workspace is focused and
# leave it there (no move), rather than pinning it to a fixed workspace name.
CURRENT_WORKSPACE = "current"


class ConfigError(Exception):
    """Raised when the config file is missing or not parseable."""


@dataclass
class Target:
    name: str
    kind: str  # "app" | "safari" | "chrome"
    workspace: str
    bundle: str | None = None
    browser: str | None = None
    url: str | None = None
    match: str | None = None
    mode: str = "tab"  # "tab" (Phase 1) | "app" (Phase 2)


@dataclass
class ConfigResult:
    path: Path
    targets: dict[str, Target] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def config_path() -> Path:
    """Resolve the targets.toml path, honoring XDG_CONFIG_HOME."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "deck" / "targets.toml"


def _parse_target(name: str, table: dict, errors: list[str]) -> Target | None:
    if not isinstance(table, dict):
        errors.append(f"[{name}]: expected a table, got {type(table).__name__}")
        return None

    workspace = table.get("workspace")
    if workspace is None:
        errors.append(f"[{name}]: missing required field 'workspace'")
        ws = ""
    else:
        # AeroSpace workspace names are strings; numeric TOML values are fine.
        ws = str(workspace)

    is_app = table.get("type") == "app"
    browser = table.get("browser")

    if "type" in table and table["type"] != "app":
        errors.append(f"[{name}]: unknown type '{table['type']}' (only 'app')")

    if is_app:
        bundle = table.get("bundle")
        if not bundle:
            errors.append(f"[{name}]: app target missing required field 'bundle'")
        return Target(
            name=name,
            kind="app",
            workspace=ws,
            bundle=bundle,
        )

    if browser is None:
        errors.append(
            f"[{name}]: must set either type='app' or browser='safari'|'chrome'"
        )
        return None

    if browser not in _VALID_BROWSERS:
        errors.append(
            f"[{name}]: invalid browser '{browser}' (use 'safari' or 'chrome')"
        )
        return None

    url = table.get("url")
    if not url:
        errors.append(f"[{name}]: {browser} target missing required field 'url'")

    mode = table.get("mode", "tab")
    if mode not in _VALID_MODES:
        errors.append(f"[{name}]: invalid mode '{mode}' (use 'tab' or 'app')")
        mode = "tab"

    # Default the dedup match to the URL when not given explicitly.
    match = table.get("match") or url

    return Target(
        name=name,
        kind=browser,
        workspace=ws,
        browser=browser,
        url=url,
        match=match,
        mode=mode,
    )


def load(path: Path | None = None) -> ConfigResult:
    """Load and validate the config. Raises ConfigError on missing/bad file."""
    p = path or config_path()
    if not p.exists():
        raise ConfigError(f"config not found: {p}")
    try:
        with p.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"could not parse {p}: {exc}") from exc

    result = ConfigResult(path=p)
    for name, table in data.items():
        target = _parse_target(name, table, result.errors)
        if target is not None:
            result.targets[name] = target
    return result
