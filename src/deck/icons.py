"""Icon resolution for Stream Deck buttons.

`deck icon <target>` emits a `data:image/png;base64,…` URL that the Stream Deck
plugin feeds straight into `setImage`. Two sources:

  * **web targets** -> the site's favicon. DuckDuckGo's icon service
    (`https://icons.duckduckgo.com/ip3/<host>.ico`) returns a real PNG with no
    redirect, so a single stdlib `urllib` GET is enough; we fall back to the
    site's own `/favicon.ico` if that 404s.
  * **app targets** -> the macOS app icon via `NSWorkspace.iconForFile_`, drawn
    into a `size×size` PNG with `NSBitmapImageRep` (PyObjC AppKit). Going through
    NSWorkspace handles modern asset-catalog icons that ship no `.icns`.

Results are cached as PNG under ``~/.cache/deck/icons/<target>.png`` (honoring
XDG_CACHE_HOME); `--refresh` rebuilds. Stream Deck presses must feel instant, so
the second call for a target is a pure file read.
"""

import base64
import os
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .config import Target
from .logging import get_logger

_log = get_logger()

_DUCKDUCKGO = "https://icons.duckduckgo.com/ip3/{host}.ico"
_USER_AGENT = "deck/0.1 (+https://github.com/technologylab-ai)"
DEFAULT_SIZE = 288


class IconError(Exception):
    """Raised when an icon cannot be produced for a target."""


def cache_dir() -> Path:
    """Icon cache directory, honoring XDG_CACHE_HOME."""
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "deck" / "icons"


def _cache_path(target: Target) -> Path:
    return cache_dir() / f"{target.name}.png"


def png_bytes(target: Target, size: int = DEFAULT_SIZE, refresh: bool = False) -> bytes:
    """Return PNG bytes for a target, using (and filling) the on-disk cache."""
    cache = _cache_path(target)
    if not refresh and cache.exists():
        return cache.read_bytes()

    if target.kind == "app":
        data = _app_icon_png(target, size)
    else:
        data = _favicon_png(target)

    if not data:
        raise IconError(f"could not produce an icon for '{target.name}'")

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(data)
    return data


def data_url(target: Target, size: int = DEFAULT_SIZE, refresh: bool = False) -> str:
    """Return a `data:image/png;base64,…` URL for a target (Stream Deck setImage)."""
    data = png_bytes(target, size=size, refresh=refresh)
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{b64}"


# --------------------------------------------------------------------------- #
# web targets — favicon
# --------------------------------------------------------------------------- #


def _favicon_png(target: Target) -> bytes | None:
    host = urlparse(target.url or "").hostname
    if not host:
        raise IconError(f"target '{target.name}' has no resolvable URL host")

    # DuckDuckGo returns a real PNG (200 image/png) with no redirect.
    candidates = [
        _DUCKDUCKGO.format(host=host),
        f"https://{host}/favicon.ico",
    ]
    for url in candidates:
        data = _http_get(url)
        if data:
            return data
    return None


def _http_get(url: str, timeout: float = 5.0) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = resp.read()
            return data or None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _log.debug("favicon GET %s failed: %s", url, exc)
        return None


# --------------------------------------------------------------------------- #
# app targets — NSWorkspace icon
# --------------------------------------------------------------------------- #


def _app_icon_png(target: Target, size: int) -> bytes | None:
    if not target.bundle:
        raise IconError(f"app target '{target.name}' has no bundle id")

    # Import AppKit lazily so non-app icon paths (and `deck --help`) don't pay
    # the PyObjC import cost. Cocoa is available transitively via the
    # ScriptingBridge dependency and pinned explicitly in pyproject.toml.
    try:
        from AppKit import (  # noqa: PLC0415
            NSBitmapImageFileTypePNG,
            NSBitmapImageRep,
            NSCompositingOperationSourceOver,
            NSDeviceRGBColorSpace,
            NSGraphicsContext,
            NSMakeRect,
            NSWorkspace,
            NSZeroRect,
        )
    except ImportError as exc:  # pragma: no cover - environment without pyobjc
        raise IconError(f"AppKit unavailable: {exc}") from exc

    ws = NSWorkspace.sharedWorkspace()
    url = ws.URLForApplicationWithBundleIdentifier_(target.bundle)
    if url is None:
        raise IconError(f"bundle '{target.bundle}' not installed")
    app_path = url.path()

    icon = ws.iconForFile_(app_path)
    if icon is None:
        return None

    # Render into an explicit size×size RGBA bitmap. Drawing through a bitmap
    # graphics context (rather than initWithFocusedViewRect_) keeps the output
    # at exactly `size` pixels regardless of Retina backing scale.
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0
    )
    rep.setSize_((size, size))

    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(ctx)
    icon.drawInRect_fromRect_operation_fraction_(
        NSMakeRect(0, 0, size, size),
        NSZeroRect,
        NSCompositingOperationSourceOver,
        1.0,
    )
    NSGraphicsContext.restoreGraphicsState()

    png = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    if png is None:
        return None
    return bytes(png)
