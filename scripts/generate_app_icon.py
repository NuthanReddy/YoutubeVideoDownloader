"""Generate project app icon assets (PNG + multi-size ICO) with no external deps.

The icon is a rounded square with a warm diagonal gradient (orange -> red ->
magenta) and a white "download" glyph: a down arrow above a short tray bar.

Why a multi-size ICO matters: Windows' taskbar and Explorer pick the icon image
whose size best matches the slot they are drawing (typically 16/32/48 px). A
single 256x256 PNG-only ICO forces a low-quality downscale -- and Tk's
``iconbitmap`` cannot reliably load PNG-compressed ICO entries at all, which is
why the app used to fall back to the generic Python icon on the taskbar. So we
emit crisp per-size images and store the small ones as uncompressed BMP/DIB
(maximum compatibility) and the large ones as PNG (compact).
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "assets"
PNG_PATH = ASSETS_DIR / "app_icon.png"
ICO_PATH = ASSETS_DIR / "app_icon.ico"

# The master PNG used for iconphoto / non-Windows platforms.
MASTER_SIZE = 256
# Sizes baked into the .ico. Small sizes -> BMP, large -> PNG (see _build_ico).
ICO_SIZES = (16, 32, 48, 64, 128, 256)
BMP_MAX_SIZE = 64  # sizes <= this are stored as BMP/DIB inside the ICO

# Diagonal gradient colour stops (t = 0 at top-left, 1 at bottom-right).
_GRADIENT = (
    (0.00, (255, 182, 20)),   # amber / orange
    (0.30, (255, 100, 16)),   # orange-red
    (0.52, (255, 40, 26)),    # vivid red
    (0.74, (249, 26, 82)),    # rose
    (1.00, (235, 20, 130)),   # magenta / pink
)
_WHITE = (255, 255, 255)

# Tile geometry (normalised 0..1). Fills the canvas edge-to-edge with rounded
# corners, matching the reference art.
_TILE_MARGIN = 0.0
_TILE_RADIUS = 0.20

# Download glyph geometry (normalised, y grows downward).
_SHAFT = (0.388, 0.185, 0.612, 0.405)                       # x0, y0, x1, y1
_HEAD = ((0.238, 0.400), (0.762, 0.400), (0.500, 0.686))    # left, right, apex
_TRAY = (0.234, 0.760, 0.766, 0.845)                        # x0, y0, x1, y1
_TRAY_RADIUS = 0.022


def _gradient_color(t: float) -> tuple[int, int, int]:
    if t <= _GRADIENT[0][0]:
        return _GRADIENT[0][1]
    if t >= _GRADIENT[-1][0]:
        return _GRADIENT[-1][1]
    for i in range(len(_GRADIENT) - 1):
        t0, c0 = _GRADIENT[i]
        t1, c1 = _GRADIENT[i + 1]
        if t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return (
                round(c0[0] + (c1[0] - c0[0]) * f),
                round(c0[1] + (c1[1] - c0[1]) * f),
                round(c0[2] + (c1[2] - c0[2]) * f),
            )
    return _GRADIENT[-1][1]


def _in_rounded_rect(
    u: float, v: float, x0: float, y0: float, x1: float, y1: float, r: float
) -> bool:
    if u < x0 or u > x1 or v < y0 or v > y1:
        return False
    dx = max(x0 + r - u, u - (x1 - r), 0.0)
    dy = max(y0 + r - v, v - (y1 - r), 0.0)
    return dx * dx + dy * dy <= r * r


def _in_triangle(
    u: float,
    v: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
    cx: float,
    cy: float,
) -> bool:
    d1 = (u - bx) * (ay - by) - (ax - bx) * (v - by)
    d2 = (u - cx) * (by - cy) - (bx - cx) * (v - cy)
    d3 = (u - ax) * (cy - ay) - (cx - ax) * (v - ay)
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def _sample(u: float, v: float) -> tuple[int, int, int, int]:
    """Return the straight (non-premultiplied) RGBA for one normalised point."""

    if not _in_rounded_rect(
        u, v, _TILE_MARGIN, _TILE_MARGIN, 1.0 - _TILE_MARGIN, 1.0 - _TILE_MARGIN,
        _TILE_RADIUS,
    ):
        return (0, 0, 0, 0)

    sx0, sy0, sx1, sy1 = _SHAFT
    (hlx, hly), (hrx, hry), (hax, hay) = _HEAD
    tx0, ty0, tx1, ty1 = _TRAY

    in_glyph = (
        (sx0 <= u <= sx1 and sy0 <= v <= sy1)
        or _in_triangle(u, v, hlx, hly, hrx, hry, hax, hay)
        or _in_rounded_rect(u, v, tx0, ty0, tx1, ty1, _TRAY_RADIUS)
    )
    if in_glyph:
        return (_WHITE[0], _WHITE[1], _WHITE[2], 255)

    t = (u + v) * 0.5
    r, g, b = _gradient_color(t)
    return (r, g, b, 255)


def _render_rgba(size: int, supersample: int) -> bytes:
    """Render ``size`` x ``size`` RGBA (row-major, top-to-bottom) with
    supersampled antialiasing using alpha-weighted (premultiplied) averaging so
    edges stay clean instead of darkening against transparent pixels."""

    ss = supersample
    span = size * ss
    inv = 1.0 / span
    out = bytearray(size * size * 4)
    samples = ss * ss

    for oy in range(size):
        base_sy = oy * ss
        for ox in range(size):
            base_sx = ox * ss
            sum_a = sum_r = sum_g = sum_b = 0.0
            for j in range(ss):
                v = (base_sy + j + 0.5) * inv
                for i in range(ss):
                    u = (base_sx + i + 0.5) * inv
                    r, g, b, a = _sample(u, v)
                    if a:
                        af = a / 255.0
                        sum_a += af
                        sum_r += r * af
                        sum_g += g * af
                        sum_b += b * af
            idx = (oy * size + ox) * 4
            if sum_a > 0.0:
                out[idx] = round(sum_r / sum_a)
                out[idx + 1] = round(sum_g / sum_a)
                out[idx + 2] = round(sum_b / sum_a)
                out[idx + 3] = round(sum_a / samples * 255)
            # else leave as transparent zeros
    return bytes(out)


def _encode_png(size: int, rgba: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    stride = size * 4
    raw = b"".join(b"\x00" + rgba[y * stride : (y + 1) * stride] for y in range(size))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, level=9))
    png += chunk(b"IEND", b"")
    return png


def _encode_bmp(size: int, rgba: bytes) -> bytes:
    """Encode a 32-bit BGRA BMP/DIB icon image (BITMAPINFOHEADER + XOR + AND)."""

    header = struct.pack(
        "<IiiHHIIiiII",
        40,           # biSize
        size,         # biWidth
        size * 2,     # biHeight (XOR + AND mask)
        1,            # biPlanes
        32,           # biBitCount
        0,            # biCompression = BI_RGB
        0,            # biSizeImage (0 allowed for BI_RGB)
        0, 0, 0, 0,   # resolution / palette fields
    )

    # XOR bitmap: bottom-up rows, BGRA per pixel.
    xor = bytearray(size * size * 4)
    for y in range(size):
        src_row = (size - 1 - y) * size * 4
        dst_row = y * size * 4
        for x in range(size):
            s = src_row + x * 4
            d = dst_row + x * 4
            xor[d] = rgba[s + 2]      # B
            xor[d + 1] = rgba[s + 1]  # G
            xor[d + 2] = rgba[s]      # R
            xor[d + 3] = rgba[s + 3]  # A

    # AND mask: 1 bpp, rows padded to 32 bits, bottom-up. 1 = transparent.
    row_bytes = ((size + 31) // 32) * 4
    and_mask = bytearray(row_bytes * size)
    for y in range(size):
        src_row = (size - 1 - y) * size * 4
        dst_row = y * row_bytes
        for x in range(size):
            if rgba[src_row + x * 4 + 3] == 0:
                and_mask[dst_row + (x >> 3)] |= 0x80 >> (x & 7)

    return header + bytes(xor) + bytes(and_mask)


def _build_ico(images: list[tuple[int, bytes, bool]]) -> bytes:
    """Assemble an ICO from ``(size, payload, is_png)`` entries."""

    count = len(images)
    directory = bytearray(struct.pack("<HHH", 0, 1, count))
    offset = 6 + count * 16
    body = bytearray()
    for size, payload, _is_png in images:
        directory += struct.pack(
            "<BBBBHHII",
            size & 0xFF,      # width (0 => 256)
            size & 0xFF,      # height (0 => 256)
            0,                # colour count
            0,                # reserved
            1,                # planes
            32,               # bit count
            len(payload),     # bytes in resource
            offset,           # offset from file start
        )
        body += payload
        offset += len(payload)
    return bytes(directory) + bytes(body)


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    # Master PNG (256) for iconphoto / non-Windows use.
    master_rgba = _render_rgba(MASTER_SIZE, supersample=3)
    PNG_PATH.write_bytes(_encode_png(MASTER_SIZE, master_rgba))

    images: list[tuple[int, bytes, bool]] = []
    for size in ICO_SIZES:
        if size == MASTER_SIZE:
            rgba = master_rgba
        else:
            rgba = _render_rgba(size, supersample=4 if size <= 128 else 3)
        if size <= BMP_MAX_SIZE:
            images.append((size, _encode_bmp(size, rgba), False))
        else:
            images.append((size, _encode_png(size, rgba), True))

    ICO_PATH.write_bytes(_build_ico(images))

    print(f"Generated: {PNG_PATH}")
    print(
        f"Generated: {ICO_PATH} ({len(ICO_SIZES)} sizes: "
        f"{', '.join(str(s) for s in ICO_SIZES)})"
    )


if __name__ == "__main__":
    main()
