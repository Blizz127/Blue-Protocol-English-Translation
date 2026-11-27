"""Render the five English startup notice lines on a matching locally owned texture."""

import hashlib
import io
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont


CANVAS = (1920, 1080)
SOURCE_DIGEST = "19f0f1928eb1d956e84b17be5630e023a6beb2491bd8ba699f2a5ebd4a3dc546"
RESULT_DIGEST = "94337907aba42cfb2b3b5afa395d148e37a26f41ab94738293a94b502f89ad27"
TITLE_FONT_DIGEST = "075e71be4c58beda172ecb574a799308f04c3d054c6a5b7434954d3b0f1b28d8"
BODY_FONT_DIGEST = "b72c65e551d653b54217ffad0d1454ce0657e4e8d4a28bcc79e0acd2598f4bf3"
NONZERO = [0] + [255] * 255

# Each pair gives the region containing the original lettering and the approved
# English ink bounds. The surrounding frame and rules stay on the player's image.
LINES = (
    ((805, 190, 1150, 235), (829, 192, 1126, 235)),
    ((510, 344, 1468, 386), (522, 354, 1455, 384)),
    ((444, 409, 1533, 452), (499, 418, 1478, 448)),
    ((316, 473, 1660, 514), (412, 479, 1564, 509)),
    ((426, 535, 1548, 575), (656, 539, 1318, 569)),
)


def _image_digest(image):
    digest = hashlib.sha256()
    for dimension in image.size:
        digest.update(dimension.to_bytes(8, "little"))
    digest.update(image.tobytes())
    return digest.hexdigest()


def _font(path, expected_digest, size):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError(f"Font file differs from the required face: {path.name}")
    return ImageFont.truetype(io.BytesIO(raw), size)


def _lettering(text, font):
    # Rasterize at four times the target resolution with a two-pixel margin.
    left, top, right, bottom = font.getbbox(text)
    image = Image.new("RGBA", (right - left + 16, bottom - top + 16))
    ImageDraw.Draw(image).text((8 - left, 8 - top), text, font=font, fill=(222, 223, 222, 255))
    small = image.resize(((image.width + 3) // 4, (image.height + 3) // 4), Image.Resampling.LANCZOS)
    bounds = small.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError("A notice line rendered no visible lettering")
    return small.crop(bounds)


def _protected_rules(original):
    red, green, blue, _ = original.split()
    rgb = ImageChops.lighter(ImageChops.lighter(red, green), blue).point(NONZERO)
    rows = rgb.tobytes()
    columns = rgb.transpose(Image.Transpose.TRANSPOSE).tobytes()
    width, height = original.size
    source = original.load()
    protected = Image.new("L", original.size)
    keep = protected.load()

    # Follow transparent RGB linework inward from the edges of each text region.
    # The original may store the frame's color even where it draws zero alpha.
    def protect_run(points):
        for x, y in points:
            r, g, b, alpha = source[x, y]
            if alpha or not (r or g or b):
                break
            keep[x, y] = 255

    for (left, top, right, bottom), _ in LINES:
        for y in range(top, bottom):
            start = y * width
            if rows.count(255, start, start + left) >= 100 and rows.count(255, start + right, start + width) >= 100:
                protect_run((x, y) for x in range(left, right))
                protect_run((x, y) for x in range(right - 1, left - 1, -1))
        for x in range(left, right):
            start = x * height
            if columns.count(255, start, start + top) >= 100:
                protect_run((x, y) for y in range(top, bottom))
    return protected


def _clear_original_lettering(original, protected):
    regions = Image.new("L", original.size)
    for bounds, _ in LINES:
        regions.paste(255, bounds)
    visible = ImageChops.multiply(original.getchannel("A").point(NONZERO), regions)
    # A four-by-four texture block touched by ink can also contain invisible
    # color from that ink. Clear its footprint only inside the lettering regions.
    blocks = visible.resize((original.width // 4, original.height // 4), Image.Resampling.BOX).point(NONZERO)
    footprint = blocks.resize(original.size, Image.Resampling.NEAREST)
    remove = ImageChops.subtract(ImageChops.multiply(footprint, regions), protected)
    result = original.copy()
    result.paste((0, 0, 0, 0), (0, 0), remove)
    return result


def render_notice(original: Image.Image, labels: list[str], title_font: Path, body_font: Path) -> Image.Image:
    """Return a new RGBA notice using the verified source, local fonts and five approved English labels."""
    if original.mode != "RGBA" or original.size != CANVAS or _image_digest(original) != SOURCE_DIGEST:
        raise ValueError("Expected the original 1920 by 1080 RGBA startup notice")
    if len(labels) != len(LINES) or any(
        not isinstance(text, str) or not 1 <= len(text) <= 160 or not text.isascii() or not text.isprintable()
        for text in labels
    ):
        raise ValueError("Expected one English title followed by four single-line English notices")

    title = _font(title_font, TITLE_FONT_DIGEST, 166)
    body = _font(body_font, BODY_FONT_DIGEST, 112)
    protected = _protected_rules(original)
    result = _clear_original_lettering(original, protected)

    for index, (text, (_, bounds)) in enumerate(zip(labels, LINES)):
        ink = _lettering(text, title if index == 0 else body)
        left, top, right, bottom = bounds
        if ink.size != (right - left, bottom - top):
            raise ValueError(f"Line {index + 1} differs from the verified lettering dimensions")
        if ImageChops.multiply(ink.getchannel("A"), protected.crop(bounds)).getbbox():
            raise ValueError(f"Line {index + 1} touches a protected rule")
        result.alpha_composite(ink, (left, top))

    if _image_digest(result) != RESULT_DIGEST:
        raise ValueError("The rendered notice differs from the verified English result")
    return result
