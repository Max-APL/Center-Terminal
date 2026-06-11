import struct
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "assets"
PNG_PATH = ASSETS_DIR / "central_terminal.png"
ICO_PATH = ASSETS_DIR / "central_terminal.ico"


def lerp(a, b, t):
    return int(a + (b - a) * t)


def draw_gradient_round_rect(canvas, box, radius, top, bottom):
    mask = Image.new("L", canvas.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle(box, radius=radius, fill=255)

    gradient = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    pixels = gradient.load()
    x1, y1, x2, y2 = box
    for y in range(y1, y2 + 1):
        t = (y - y1) / max(1, y2 - y1)
        color = (
            lerp(top[0], bottom[0], t),
            lerp(top[1], bottom[1], t),
            lerp(top[2], bottom[2], t),
            lerp(top[3], bottom[3], t),
        )
        for x in range(x1, x2 + 1):
            pixels[x, y] = color

    canvas.alpha_composite(Image.composite(gradient, Image.new("RGBA", canvas.size), mask))


def rounded_rect(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def small_icon(size):
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    margin = max(1, round(size * 0.045))
    tile = (margin, margin, size - margin - 1, size - margin - 1)
    tile_radius = max(3, round(size * 0.22))
    panel = (
        round(size * 0.19),
        round(size * 0.26),
        round(size * 0.81),
        round(size * 0.74),
    )
    panel_radius = max(2, round(size * 0.11))

    rounded_rect(draw, tile, tile_radius, fill=(38, 215, 224, 255))
    if size >= 24:
        rounded_rect(draw, tile, tile_radius, fill=None, outline=(218, 255, 255, 235), width=1)

    rounded_rect(draw, panel, panel_radius, fill=(5, 12, 24, 255))

    prompt = (218, 252, 255, 255)
    accent = (52, 255, 176, 255)
    glyph_width = max(2, round(size * 0.095))
    underscore_width = max(2, round(size * 0.09))

    draw.line(
        (
            (round(size * 0.34), round(size * 0.41)),
            (round(size * 0.45), round(size * 0.50)),
            (round(size * 0.34), round(size * 0.59)),
        ),
        fill=prompt,
        width=glyph_width,
        joint="curve",
    )
    draw.line(
        (
            (round(size * 0.54), round(size * 0.60)),
            (round(size * 0.69), round(size * 0.60)),
        ),
        fill=accent,
        width=underscore_width,
    )

    return canvas


def large_icon(size):
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    scale = size / 1024

    def s(value):
        return int(round(value * scale))

    def sb(box):
        return tuple(s(v) for v in box)

    draw_gradient_round_rect(
        canvas,
        sb((48, 48, 976, 976)),
        s(206),
        (38, 215, 224, 255),
        (18, 196, 147, 255),
    )
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        sb((48, 48, 976, 976)),
        radius=s(206),
        outline=(218, 255, 255, 220),
        width=max(1, s(14)),
    )
    draw.rounded_rectangle(sb((160, 254, 864, 772)), radius=s(96), fill=(5, 12, 24, 255))
    draw.line(sb((270, 400, 418, 512, 270, 624)), fill=(218, 252, 255, 255), width=s(84), joint="curve")
    draw.line(sb((502, 620, 724, 620)), fill=(52, 255, 176, 255), width=s(80))
    return canvas


def build_icon(size):
    if size <= 64:
        return small_icon(size)
    return large_icon(size)


def image_to_png_bytes(image):
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def save_ico(path, frames):
    encoded_frames = [(size, image_to_png_bytes(image)) for size, image in frames]

    header_size = 6
    directory_size = 16 * len(encoded_frames)
    offset = header_size + directory_size

    data = bytearray()
    data += struct.pack("<HHH", 0, 1, len(encoded_frames))

    image_blobs = []
    for size, blob in encoded_frames:
        width = 0 if size == 256 else size
        height = 0 if size == 256 else size
        data += struct.pack("<BBBBHHII", width, height, 0, 0, 1, 32, len(blob), offset)
        image_blobs.append(blob)
        offset += len(blob)

    for blob in image_blobs:
        data += blob

    path.write_bytes(data)


def main():
    ASSETS_DIR.mkdir(exist_ok=True)

    preview = large_icon(1024)
    preview.save(PNG_PATH)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [(size, build_icon(size)) for size in sizes]
    save_ico(ICO_PATH, frames)

    print(f"Generated {PNG_PATH}")
    print(f"Generated {ICO_PATH}")


if __name__ == "__main__":
    main()
