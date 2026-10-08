"""Proper PNG decoder supporting standard PNG unfiltering."""

import os
import struct
import zlib


def paeth_predictor(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    elif pb <= pc:
        return b
    else:
        return c


def decode_png(path):
    with open(path, "rb") as f:
        data = f.read()
    w, h = struct.unpack(">II", data[16:24])
    color_type = data[25]
    bpp = 4 if color_type == 6 else 3

    idat = b""
    pos = 8
    while pos < len(data):
        length = int.from_bytes(data[pos : pos + 4], "big")
        chunk = data[pos + 4 : pos + 8]
        if chunk == b"IDAT":
            idat += data[pos + 8 : pos + 8 + length]
        pos += 12 + length

    decompressed = zlib.decompress(idat)
    row_bytes_len = w * bpp
    stride = 1 + row_bytes_len

    raw_rows = []
    prev_row = bytearray(row_bytes_len)

    for y in range(h):
        filter_type = decompressed[y * stride]
        curr_raw = bytearray(decompressed[y * stride + 1 : (y + 1) * stride])
        reconstructed = bytearray(row_bytes_len)

        for i in range(row_bytes_len):
            filt_x = curr_raw[i]
            recon_a = reconstructed[i - bpp] if i >= bpp else 0
            recon_b = prev_row[i]
            recon_c = prev_row[i - bpp] if i >= bpp else 0

            if filter_type == 0:  # None
                val = filt_x
            elif filter_type == 1:  # Sub
                val = (filt_x + recon_a) & 0xFF
            elif filter_type == 2:  # Up
                val = (filt_x + recon_b) & 0xFF
            elif filter_type == 3:  # Average
                val = (filt_x + ((recon_a + recon_b) // 2)) & 0xFF
            elif filter_type == 4:  # Paeth
                val = (filt_x + paeth_predictor(recon_a, recon_b, recon_c)) & 0xFF
            else:
                val = filt_x

            reconstructed[i] = val

        prev_row = reconstructed
        raw_rows.append(reconstructed)

    pixels = []
    for y in range(h):
        row_pixels = []
        for x in range(w):
            if bpp == 4:
                r, g, b, a = raw_rows[y][x * 4 : x * 4 + 4]
            else:
                r, g, b = raw_rows[y][x * 3 : x * 3 + 3]
                a = 255
            row_pixels.append((r, g, b, a))
        pixels.append(row_pixels)

    return w, h, pixels


def save_scaled_png(pixels, orig_w, orig_h, target_size, out_path):
    raw_rows = []
    for y in range(target_size):
        src_y = int(y * orig_h / target_size)
        row = bytearray([0])
        for x in range(target_size):
            src_x = int(x * orig_w / target_size)
            r, g, b, a = pixels[src_y][src_x]
            row.extend([r, g, b, a])
        raw_rows.append(bytes(row))

    raw_data = b"".join(raw_rows)
    compressed = zlib.compress(raw_data, 9)

    png_sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", target_size, target_size, 8, 6, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data)
    ihdr_chunk = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)

    idat_crc = zlib.crc32(b"IDAT" + compressed)
    idat_chunk = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", idat_crc)

    iend_crc = zlib.crc32(b"IEND")
    iend_chunk = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(png_sig + ihdr_chunk + idat_chunk + iend_chunk)
    print(f"Generated: {out_path} ({target_size}x{target_size})")


def save_svg(pixels, orig_w, orig_h, out_path):
    rects = []
    for y, row in enumerate(pixels):
        for x, (r, g, b, a) in enumerate(row):
            if a > 0:
                hex_color = f"#{r:02x}{g:02x}{b:02x}"
                opacity = f' opacity="{a/255.0:.2f}"' if a < 255 else ""
                rects.append(
                    f'<rect x="{x}" y="{y}" width="1" height="1" fill="{hex_color}"{opacity} />'
                )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {orig_w} {orig_h}" shape-rendering="crispEdges" width="100%" height="100%">
  {''.join(rects)}
</svg>"""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"Generated: {out_path}")


if __name__ == "__main__":
    orig_w, orig_h, pixels = decode_png("icon.png")

    print(f"Decoded {orig_w}x{orig_h} image successfully.")

    # Extension icons
    save_scaled_png(pixels, orig_w, orig_h, 16, "extension/icons/icon16.png")
    save_scaled_png(pixels, orig_w, orig_h, 48, "extension/icons/icon48.png")
    save_scaled_png(pixels, orig_w, orig_h, 128, "extension/icons/icon128.png")
    save_svg(pixels, orig_w, orig_h, "extension/icons/icon.svg")

    # Android mipmap launcher icons
    android_res = "android/app/src/main/res"
    save_scaled_png(pixels, orig_w, orig_h, 48, f"{android_res}/mipmap-mdpi/ic_launcher.png")
    save_scaled_png(pixels, orig_w, orig_h, 72, f"{android_res}/mipmap-hdpi/ic_launcher.png")
    save_scaled_png(pixels, orig_w, orig_h, 96, f"{android_res}/mipmap-xhdpi/ic_launcher.png")
    save_scaled_png(pixels, orig_w, orig_h, 144, f"{android_res}/mipmap-xxhdpi/ic_launcher.png")
    save_scaled_png(pixels, orig_w, orig_h, 192, f"{android_res}/mipmap-xxxhdpi/ic_launcher.png")
    save_scaled_png(pixels, orig_w, orig_h, 512, f"{android_res}/drawable/ic_launcher.png")
