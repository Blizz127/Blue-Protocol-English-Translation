"""Letter the body of a supported local help panel using a local font."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont


# Each original image and its corresponding approved English body have separate fingerprints.
_PROFILES = {
    "LiquidMemory_guide_06": ("14844557fe1b26bffb15dc1cdc0102cd32aa1a62249b8daf79ac57734f06e4e6",
                             "60309843b6a7eeca503d2eef76961560c19a15e660b35b5773bbfc1ef1ab22d7"),
    "LiquidMemory_guide_07": ("6d5631541826c256560f38558886509e8de0d296cf14204daedd6474e344dc38",
                             "0bdc01ee55f6d8185933cab8a49cee5e410e003de0f137342608d163776fe637"),
    "LiquidMemory_guide_08": ("6d22f38ccf7f407bf6d8854a1cd765e76b6cf54932206ade51312961bd13f283",
                             "98125032edbc4f008a5c7700d2ed95bdf819f4dace5e4140fe68edf574fe6a5e"),
    "LiquidMemory_guide_09": ("bd833068c32b18dcf166c0237f9d0f7eaaac0e32745c7cde3b0d2e08231affb8",
                             "753c038f65e334a403ac39b75b90eeb4e63198d3f3b08a6a34ab6074353b4d7f"),
    "UI_TutorialHelp00062": ("013149ecbc500d739f3ad1512332e71bbe1f23008ea1160129eec627281f47f1",
                            "274bfe6cd197c01e2459e95d31203284bf2b7bc98126b6a1cc3120f69b88087d"),
    "UI_TutorialHelp00063": ("194ef92848db91790a27b5b248ebff8c072dea7d2220e70252e20d6d0abdc82a",
                            "26d946ad7f78c1a178dd2c2c9f4bb34159ee32867e20ae67feea6878d2e5d488"),
    "UI_TutorialHelp00064": ("353804956380542e4efd24f5f91a0f9166929506e44ad55b0cc91ce5c5a42a2c",
                            "0d9320e1c5d35f54d6bad5c6c301080f134baf926cacef29878c6cd8f3b78e4b"),
    "UI_TutorialHelp00065": ("f91cc61051f51fb750c69b8aa843edd3e39f05940aa2894155589bda5af66baf",
                            "fa2b680f599c04768a4f2855ace219ce54a1e645c10eb21bb7bd97876a952611"),
    "UI_TutorialHelp00066": ("8625c95ad2c849b3c4d1265d1cf9e90899e63133a7a6dedba86fa0f3243957f3",
                            "128fdf53e9a69e0681214f0a766c803c5fb60ffe99c884546506b1b116ba58bc"),
}
_FONT = "b72c65e551d653b54217ffad0d1454ce0657e4e8d4a28bcc79e0acd2598f4bf3"
_BODY = (39, 129, 480, 156)
_BINARY = [0] + [255] * 255


def _letter_mask(text, font_data):
    face = ImageFont.truetype(BytesIO(font_data), 88)
    left, top, right, bottom = face.getbbox(text)
    # Render at four times native scale, leaving room for filtered edge coverage.
    large = Image.new("L", (right - left + 32, bottom - top + 32))
    ImageDraw.Draw(large).text((16 - left, 16 - top), text, font=face, fill=255)
    small = large.resize(((large.width + 3) // 4, (large.height + 3) // 4),
                         Image.Resampling.LANCZOS)
    bounds = small.getbbox()
    if bounds is None:
        raise ValueError("Empty lettering")
    return small.crop(bounds)


def render_body(stock_rgba: Image.Image, english: str, font: Path,
                profile: str = "auto") -> tuple[Image.Image, Image.Image]:
    """Return the lettered RGBA image and binary L old/new glyph mask.

    The default identifies the panel from its pixels. An explicit profile is
    the stock asset basename. Supply local Liberation Sans Bold as the font.
    """
    if stock_rgba.mode != "RGBA" or stock_rgba.size != (600, 240):
        raise ValueError("Expected an original 600 by 240 RGBA help panel")
    dimensions = b"".join(n.to_bytes(8, "little") for n in stock_rgba.size)
    source_hash = sha256(dimensions + stock_rgba.tobytes()).hexdigest()
    name = next((key for key, pair in _PROFILES.items() if pair[0] == source_hash), None)
    if name is None or profile not in ("auto", name):
        raise ValueError("Unsupported stock help panel or mismatched profile")
    if not isinstance(english, str) or sha256(english.encode("utf-8")).hexdigest() != _PROFILES[name][1]:
        raise ValueError("The English label does not match this panel")
    font_data = font.read_bytes()
    if sha256(font_data).hexdigest() != _FONT:
        raise ValueError("The local font differs from the supported Liberation Sans Bold")

    left, top, right, bottom = _BODY
    # Uniform pixels along both edges provide a local sample of the panel under its text.
    above = stock_rgba.crop((left, top - 1, right, top)).getcolors(1)
    below = stock_rgba.crop((left, bottom, right, bottom + 1)).getcolors(1)
    if not above or above != below:
        raise ValueError("Could not establish the local panel background")
    background = above[0][1]
    body = stock_rgba.crop(_BODY)
    flat = Image.new("RGBA", body.size, background)
    difference = ImageChops.difference(body.convert("RGB"), flat.convert("RGB"))
    red, green, blue = difference.split()
    old = ImageChops.lighter(ImageChops.lighter(red, green), blue).point(_BINARY)
    bounds = old.getbbox()
    letters = _letter_mask(english, font_data)
    if bounds is None or letters.width > body.width or letters.height > body.height:
        raise ValueError("The English lettering does not fit the original label region")

    x = min(bounds[0], body.width - letters.width)
    y = max(0, min((bounds[1] + bounds[3] - letters.height) // 2, body.height - letters.height))
    body.paste(flat, mask=old)
    body.paste((255, 255, 255, 255), (x, y, x + letters.width, y + letters.height), letters)
    result = stock_rgba.copy()
    result.paste(body, (left, top))
    new = Image.new("L", body.size)
    new.paste(letters.point(_BINARY), (x, y))
    support = Image.new("L", stock_rgba.size)
    support.paste(ImageChops.lighter(old, new), (left, top))
    return result, support


def render_route(stock_rgba: Image.Image, english: str, font: Path) -> tuple[Image.Image, Image.Image]:
    """Letter the description beneath the quest tabs and return its old/new glyph mask."""
    if stock_rgba.mode != "RGBA" or stock_rgba.size != (600, 240):
        raise ValueError("Expected the original quest help picture")
    dimensions = b"".join(n.to_bytes(8, "little") for n in stock_rgba.size)
    if sha256(dimensions + stock_rgba.tobytes()).hexdigest() != (
            "c694970436314c952a88dd5f9bc829ca257b9fa601a85ecdab59673327c25afd"):
        raise ValueError("Unsupported quest help picture")
    if sha256(english.encode("utf-8")).hexdigest() != (
            "6bf104208abb53096cc12451537d7298a60c2c318b41e40d79cdc196ddb9cac5"):
        raise ValueError("The quest description differs from the reviewed caption")
    font_data = font.read_bytes()
    if sha256(font_data).hexdigest() != _FONT:
        raise ValueError("The local font differs from the supported Liberation Sans Bold")

    # Each column of the dark strip supplies its own backing above and below the line.
    # Limit the retouch to pixels around the original bright strokes.
    from PIL import ImageFilter
    result = stock_rgba.copy()
    support = Image.new("L", result.size)
    old_box = (6, 69, 196, 86)
    crop = stock_rgba.crop(old_box)
    strokes = crop.getchannel("R").point(lambda value: 255 if value > 85 else 0)
    old = strokes.filter(ImageFilter.MaxFilter(5))
    before = stock_rgba.crop((old_box[0], 68, old_box[2], 69))
    after = stock_rgba.crop((old_box[0], 86, old_box[2], 87))
    backing = Image.new("RGBA", crop.size)
    for y in range(crop.height):
        row = Image.blend(before, after, (y + 1) / (crop.height + 1))
        backing.paste(row, (0, y))
    result.paste(backing, old_box, old)
    support.paste(old, old_box)

    # Draw the new face at four times its final size for subpixel edge coverage.
    face = ImageFont.truetype(BytesIO(font_data), 44)
    letters = Image.new("L", (1120, 72))
    ImageDraw.Draw(letters).text((0, 0), english, fill=255, font=face, anchor="lt")
    ink = letters.resize((280, 18), Image.Resampling.LANCZOS)
    if not ink.getbbox() or ink.getbbox()[2] >= ink.width:
        raise ValueError("English quest description exceeds the photographed text strip")
    origin = (7, 72)
    result.paste((255, 251, 239, 255), (origin[0], origin[1], origin[0] + ink.width,
                                        origin[1] + ink.height), ink)
    new = Image.new("L", result.size)
    new.paste(ink.point(_BINARY), origin)
    return result, ImageChops.lighter(support, new)
