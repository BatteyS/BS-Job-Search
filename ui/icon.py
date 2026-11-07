"""Job Search's icon, drawn in code: a gold briefcase on espresso, in the page's colors.

    python ui/icon.py out.png 512          # one PNG, that many pixels square
    python ui/icon.py --iconset Folder.iconset   # the sizes macOS's iconutil takes

The page serves it for a phone's home screen (/apple-touch-icon.png, and the
web app manifest's icons), ui/build_demo.py puts it beside each demo, and
install.sh turns an iconset of it into Job Search's Desktop icon. Drawn rather
than kept as an image, so the repository holds no binary file for it, and each
size is drawn at that size, sharp.

For a phone the square is filled to the edge: iOS rounds an icon's corners
itself, and Android crops a "maskable" icon to its own shape, so the briefcase
stays within the middle 60%, inside the safe zone both keep. A Mac draws an
icon as it is, so its iconset is the rounded tile of Apple's icon grid, with
clear margins (`tile=True`).
"""

from __future__ import annotations

import functools
import math
import os
import struct
import sys
import zlib

TOP = (0x2C, 0x24, 0x1C)      # the page's background (style.css), a little lighter at the top
BOTTOM = (0x17, 0x12, 0x0D)
GOLD = (0xF2, 0xC1, 0x4E)     # the page's accent

# The iconset iconutil makes a Mac icon from: name -> pixels.
ICONSET = {"icon_16x16.png": 16, "icon_16x16@2x.png": 32, "icon_32x32.png": 32,
           "icon_32x32@2x.png": 64, "icon_128x128.png": 128, "icon_128x128@2x.png": 256,
           "icon_256x256.png": 256, "icon_256x256@2x.png": 512, "icon_512x512.png": 512}


def _box(x: float, y: float, cx: float, cy: float, hx: float, hy: float, r: float) -> float:
    """Signed distance from (x, y) to a rounded rectangle: negative inside."""
    qx, qy = abs(x - cx) - hx + r, abs(y - cy) - hy + r
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r


def _cover(d: float) -> float:
    """How much of a pixel a shape covers, from its distance in pixels: a one-pixel ramp
    across the edge, which is the antialiasing."""
    return min(1.0, max(0.0, 0.5 - d))


# Apple's icon grid: an 824-point tile, corners rounded at 185, on a 1024 canvas.
TILE, TILE_RADIUS = 824 / 1024, 185 / 1024


@functools.lru_cache(maxsize=None)
def png(size: int, tile: bool = False) -> bytes:
    """The icon, `size` pixels square, as PNG bytes: filled to the edge, or with
    `tile` the Mac's rounded tile on a clear canvas."""
    s = float(size)
    k = TILE if tile else 1.0          # the briefcase shrinks with the tile
    c = 0.5 * s

    def at(u: float, v: float, hx: float, hy: float, r: float) -> tuple:
        return (c + (u - 0.5) * s * k, c + (v - 0.5) * s * k, hx * s * k, hy * s * k, r * s * k)
    # The briefcase: body, handle (a rounded ring), the seam across the body,
    # and the clasp on the seam.
    body = at(0.5, 0.56, 0.30, 0.205, 0.06)
    handle_out = at(0.5, 0.335, 0.11, 0.075, 0.05)
    handle_in = at(0.5, 0.355, 0.065, 0.05, 0.025)
    seam = at(0.5, 0.52, 0.31, 0.017, 0.0)
    clasp = at(0.5, 0.52, 0.05, 0.045, 0.015)
    square = (c, c, 0.5 * s * TILE, 0.5 * s * TILE, s * TILE_RADIUS)
    rows = []
    for py in range(size):
        y = py + 0.5
        t = (y - c) / (s * k) + 0.5
        bg = tuple(TOP[i] + (BOTTOM[i] - TOP[i]) * t for i in range(3))
        row = bytearray(b"\x00")   # PNG filter type 0 for the row
        for px in range(size):
            x = px + 0.5
            ring = min(_cover(_box(x, y, *handle_out)), 1.0 - _cover(_box(x, y, *handle_in)))
            case = _cover(_box(x, y, *body)) * (1.0 - _cover(_box(x, y, *seam)))
            a = max(ring, case, _cover(_box(x, y, *clasp)))
            row += bytes(round(bg[i] + (GOLD[i] - bg[i]) * a) for i in range(3))
            if tile:
                row.append(round(255 * _cover(_box(x, y, *square))))
        rows.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(
            ">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    kind = 6 if tile else 2            # 8-bit RGBA, or RGB
    header = struct.pack(">IIBBBBB", size, size, 8, kind, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def write_iconset(folder: str) -> None:
    os.makedirs(folder, exist_ok=True)
    for name, size in ICONSET.items():
        with open(os.path.join(folder, name), "wb") as fh:
            fh.write(png(size, tile=True))


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--iconset":
        write_iconset(argv[1])
        return 0
    if len(argv) == 2 and argv[1].isdigit():
        with open(argv[0], "wb") as fh:
            fh.write(png(int(argv[1])))
        return 0
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
