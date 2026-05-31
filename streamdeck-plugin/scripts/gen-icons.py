#!/usr/bin/env python3
"""Generate the plugin's own manifest icons (NOT the per-button target icons,
which `deck icon` produces at runtime).

Draws a simple flat "deck" mark — a rounded square with a stack of three bars —
at every size Stream Deck asks for. Run with the deck tool's interpreter so
AppKit is importable:

    ~/.local/share/uv/tools/deck/bin/python streamdeck-plugin/scripts/gen-icons.py
"""

import sys
from pathlib import Path

from AppKit import (
    NSBezierPath,
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSColor,
    NSDeviceRGBColorSpace,
    NSGraphicsContext,
    NSMakeRect,
)

ROOT = Path(__file__).resolve().parent.parent / "ai.technologylab.deck.sdPlugin" / "imgs"

# name -> (size, transparent_background)
ICONS = {
    "plugin/marketplace": (288, False),
    "plugin/marketplace@2x": (512, False),
    "plugin/category-icon": (28, True),
    "plugin/category-icon@2x": (56, True),
    "actions/open/icon": (20, True),
    "actions/open/icon@2x": (40, True),
    "actions/open/key": (72, False),
    "actions/open/key@2x": (144, False),
}

BG = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.13, 0.16, 0.22, 1.0)
FG = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.40, 0.78, 0.95, 1.0)


def draw(size: int, transparent: bool) -> bytes:
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, NSDeviceRGBColorSpace, 0, 0
    )
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(ctx)

    s = float(size)
    if not transparent:
        radius = s * 0.18
        bg = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(0, 0, s, s), radius, radius
        )
        BG.set()
        bg.fill()

    # Three stacked bars (a "deck" of cards / windows).
    FG.set()
    margin = s * 0.22
    width = s - 2 * margin
    bar_h = s * 0.13
    gap = s * 0.10
    total = 3 * bar_h + 2 * gap
    y = (s - total) / 2 + total - bar_h
    for _ in range(3):
        r = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(margin, y, width, bar_h), bar_h * 0.4, bar_h * 0.4
        )
        r.fill()
        y -= bar_h + gap

    NSGraphicsContext.restoreGraphicsState()
    png = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
    return bytes(png)


def main() -> int:
    for name, (size, transparent) in ICONS.items():
        out = ROOT / f"{name}.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(draw(size, transparent))
        print(f"wrote {out.relative_to(ROOT.parent)}  ({size}x{size})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
