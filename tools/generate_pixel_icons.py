"""Generates crisp 11x11 pixel art icons in SVG and PNG format for the extension and UI."""

import os
import struct
import zlib

# 11x11 Pixel grid representation:
# 'B' = Deep purple background #8a05ff
# 'G' = Neon mint green #61cf92
# 'L' = Soft lavender #c084fc
# '.' = Dark border/background #0a0a0c

GRID_11 = [
    "BBBBBBBBBBB",
    "BB..G.G..BB",
    "BB...G...BB",
    "BB..GGG..BB",
    "BG.GGGGG.GB",
    "BG..GGG..GB",
    "BGL..G..LGB",
    "BLL.....LLB",
    "BLGGGGGGGLB",
    "B.GGGGGGG.B",
    "BBBBBBBBBBB",
]

# Cleaner alternative: Pixel Download Arrow over Purple Shield/Grid
# Row 0-10 (11x11)
PIXEL_MAP = [
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 1, 1, 1, 2, 2, 2, 1, 1, 1, 0],
    [0, 1, 3, 1, 0, 2, 0, 1, 3, 1, 0],
    [0, 1, 1, 0, 0, 2, 0, 0, 1, 1, 0],
    [0, 2, 0, 0, 0, 2, 0, 0, 0, 2, 0],
    [0, 2, 2, 0, 0, 2, 0, 0, 2, 2, 0],
    [0, 0, 2, 2, 2, 2, 2, 2, 2, 0, 0],
    [0, 0, 0, 2, 2, 2, 2, 2, 0, 0, 0],
    [0, 0, 0, 0, 2, 2, 2, 0, 0, 0, 0],
    [0, 2, 2, 2, 2, 2, 2, 2, 2, 2, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
]

PALETTE = {
    0: (14, 14, 18, 255),    # #0e0e12 Dark base
    1: (138, 5, 255, 255),   # #8a05ff Purple
    2: (97, 207, 146, 255),  # #61cf92 Green
    3: (192, 132, 252, 255), # #c084fc Lavender
}

def create_png(matrix, size, out_path):
    # Scale 11x11 up to `size`x`size` using nearest-neighbor
    grid_h = len(matrix)
    grid_w = len(matrix[0])
    
    raw_rows = []
    for y in range(size):
        src_y = int(y * grid_h / size)
        row = bytearray([0]) # PNG filter byte 0 (None)
        for x in range(size):
            src_x = int(x * grid_w / size)
            val = matrix[src_y][src_x]
            r, g, b, a = PALETTE[val]
            row.extend([r, g, b, a])
        raw_rows.append(bytes(row))
    
    raw_data = b"".join(raw_rows)
    compressed = zlib.compress(raw_data, 9)
    
    # Construct standard PNG chunks
    png_sig = b"\x89PNG\r\n\x1a\n"
    
    # IHDR: width(4), height(4), bit depth(1=8), color type(1=6 RGBA), comp(1=0), filter(1=0), interlace(1=0)
    ihdr_data = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data)
    ihdr_chunk = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
    
    # IDAT
    idat_crc = zlib.crc32(b"IDAT" + compressed)
    idat_chunk = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", idat_crc)
    
    # IEND
    iend_crc = zlib.crc32(b"IEND")
    iend_chunk = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
    
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(png_sig + ihdr_chunk + idat_chunk + iend_chunk)
    print(f"Generated {out_path} ({size}x{size})")

def create_svg(matrix, out_path):
    grid_h = len(matrix)
    grid_w = len(matrix[0])
    rects = []
    hex_palette = {
        0: "#0e0e12",
        1: "#8a05ff",
        2: "#61cf92",
        3: "#c084fc"
    }
    for y, row in enumerate(matrix):
        for x, val in enumerate(row):
            if val != 0:
                color = hex_palette[val]
                rects.append(f'<rect x="{x}" y="{y}" width="1" height="1" fill="{color}" />')
    
    svg_content = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {grid_w} {grid_h}" shape-rendering="crispEdges" width="100%" height="100%">
  <rect width="{grid_w}" height="{grid_h}" fill="#0e0e12" rx="1.5" />
  {''.join(rects)}
</svg>'''
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg_content)
    print(f"Generated {out_path}")

if __name__ == "__main__":
    icons_dir = os.path.join("extension", "icons")
    create_png(PIXEL_MAP, 16, os.path.join(icons_dir, "icon16.png"))
    create_png(PIXEL_MAP, 48, os.path.join(icons_dir, "icon48.png"))
    create_png(PIXEL_MAP, 128, os.path.join(icons_dir, "icon128.png"))
    create_svg(PIXEL_MAP, os.path.join(icons_dir, "icon.svg"))
