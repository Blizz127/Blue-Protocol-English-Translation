"""Render selected labels on a locally supplied HUD preset with Pillow, NumPy and OpenCV."""

import hashlib
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


# Each entry gives the source ink search area and the available lettering area.
_REGIONS = {
    "left": {
        1: ((148, 26, 251, 41), (148, 21, 251, 45)),
        2: ((305, 26, 464, 42), (305, 21, 464, 45)),
        3: ((481, 408, 548, 424), (471, 405, 547, 428)),
        4: ((298, 240, 388, 257), (298, 236, 388, 261)),
        5: ((24, 132, 106, 153), (24, 130, 106, 153)),
        6: ((163, 132, 246, 153), (163, 130, 246, 153)),
        7: ((260, 132, 342, 153), (260, 130, 342, 153)),
        9: ((593, 173, 691, 194), (593, 171, 691, 195)),
        10: ((22, 232, 133, 254), (22, 230, 133, 255)),
        12: ((305, 270, 408, 287), (305, 266, 408, 290)),
        13: ((297, 376, 408, 394), (297, 374, 408, 399)),
        17: ((388, 351, 450, 367), (388, 348, 450, 373)),
    },
    "right": {
        1: ((148, 26, 251, 41), (148, 21, 251, 45)),
        2: ((305, 26, 464, 42), (305, 21, 464, 45)),
        3: ((156, 55, 224, 74), (151, 52, 229, 76)),
        4: ((346, 55, 438, 74), (346, 52, 438, 76)),
        5: ((23, 133, 105, 155), (23, 132, 105, 155)),
        6: ((169, 133, 251, 155), (169, 132, 251, 155)),
        7: ((261, 133, 344, 155), (261, 132, 344, 155)),
        9: ((593, 174, 692, 195), (644, 173, 730, 196)),
        10: ((21, 232, 133, 254), (21, 231, 133, 254)),
        12: ((306, 298, 409, 316), (306, 296, 409, 321)),
        13: ((302, 325, 413, 343), (302, 322, 413, 347)),
        17: ((351, 407, 414, 424), (351, 403, 414, 429)),
    },
}

_DARK = {1, 2, 3, 4, 12, 13, 17}
_SOURCE_DIGEST = {
    "left": "50698d546814be15a485a6ba7fca7e7707b4a9f0dd450a9135cf750e07f830ee",
    "right": "31e221cc339818feff8ea8ae1208ac24fa0d39903632580864da1946b7a81f18",
}
_FONT_DIGEST = "3271f41b67a81a806aadbf71762c14a405e617b738d9ceeb81191dd681c66fc4"

# Panel edges, icons and radar arcs keep their original pixels.
_ICONS = {
    "left": ((417, 276, 429, 288), (413, 383, 425, 395), (357, 356, 369, 368),
             (453, 356, 466, 368), (433, 413, 445, 425)),
    "right": ((246, 137, 253, 157), (637, 171, 643, 196), (419, 305, 431, 317),
              (418, 332, 430, 344), (321, 413, 333, 425), (416, 413, 429, 425),
              (561, 413, 573, 425)),
}
_EDGES = {
    "left": ((15, 143, 29, 129), (155, 143, 168, 130), (251, 144, 267, 128),
             (13, 238, 24, 227), (15, 298, 29, 283), (485, 210, 500, 194),
             (586, 179, 600, 164)),
    "right": ((13, 144, 28, 129), (158, 145, 175, 128), (249, 145, 264, 130),
              (11, 236, 22, 225), (14, 299, 29, 282), (435, 108, 451, 91),
              (586, 180, 601, 165)),
}


def _protected(side):
    mask = np.zeros((458, 792), np.uint8)
    for x0, y0, x1, y1 in (*_ICONS[side], (16, 55, 24, 75), (112, 55, 116, 75)):
        mask[y0:y1, x0:x1] = 255
    for x0, y0, x1, y1 in _EDGES[side]:
        cv2.line(mask, (x0, y0), (x1, y1), 255, thickness=3)
    return mask


def _source_ink(rgb, side, number, protected):
    x0, y0, x1, y1 = _REGIONS[side][number][0]
    pixels = rgb[y0:y1, x0:x1]
    bright = pixels.max(axis=2)
    dim = pixels.min(axis=2)
    if number in _DARK:
        core = bright < 130
    else:
        core = (dim > 155) & (bright - dim < 80)
        if side == "right" and number == 9:
            # The overlapping panel tints the left end of this label.
            red, green, blue = pixels.transpose(2, 0, 1)
            core |= (np.arange(x0, x1) < 642) & (red > 150) & (green > 130) & (blue > 30)

    _, components, stats, _ = cv2.connectedComponentsWithStats(core.astype(np.uint8), connectivity=8)
    retain = stats[:, cv2.CC_STAT_AREA] >= 2
    retain[0] = False
    padded = np.pad(retain[components].astype(np.uint8), 1)
    mask = cv2.dilate(padded, np.ones((3, 3), np.uint8))
    mask[protected[y0-1:y1+1, x0-1:x1+1] != 0] = 0
    ys, xs = np.nonzero(mask)
    if not xs.size:
        raise ValueError(f"Cannot locate the source lettering for row {number}")
    origin = (x0 - 1, y0 - 1)
    anchor = (int(xs.min()) + origin[0], int(ys.min() + ys.max() + 1) + 2 * origin[1])
    return mask, origin, anchor


def _letters(text, font_bytes, quarter_points, dark):
    font = ImageFont.truetype(BytesIO(font_bytes), quarter_points)
    stroke = 0 if dark else 4
    left, top, right, bottom = font.getbbox(text, stroke_width=stroke)
    canvas = Image.new("RGBA", (right - left + 16, bottom - top + 16))
    ink = (0, 0, 0, 255) if dark else (255, 255, 255, 255)
    ImageDraw.Draw(canvas).text((8-left, 8-top), text, font=font, fill=ink, stroke_width=stroke,
                                stroke_fill=(0, 0, 0, 210))
    stamp = canvas.resize(((canvas.width+3)//4, (canvas.height+3)//4), Image.Resampling.LANCZOS)
    bounds = stamp.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError("The label has no visible glyphs")
    return stamp.crop(bounds)


def _place(text, font_bytes, side, number, anchor, protected):
    left, top, right, bottom = _REGIONS[side][number][1]
    anchor_x, twice_center = anchor
    for quarter_points in range(64, 39, -2):
        stamp = _letters(text, font_bytes, quarter_points, number in _DARK)
        last_x, last_y = right-stamp.width, bottom-stamp.height
        if last_x < left or last_y < top:
            continue
        near_x = min(max(anchor_x, left), last_x)
        ink = np.asarray(stamp.getchannel("A")) > 0
        positions = ((2*abs(x-near_x) + abs(2*y+stamp.height-twice_center),
                      abs(x-near_x), x, y)
                     for x in range(left, last_x+1) for y in range(top, last_y+1))
        for _, _, x, y in sorted(positions):
            region = protected[y:y+stamp.height, x:x+stamp.width]
            if not np.any(region[ink]):
                return stamp, x, y
    raise ValueError(f"Label does not fit the lettering area for row {number}")


def render(image: Image.Image, labels: dict[int, str], side: str, font: Path) -> tuple[Image.Image, Image.Image]:
    """Return the lettered RGBA preset and an L mask for the old and new glyphs.

    Supply the stock 792 by 458 RGBA image and local Liberation Sans Narrow Bold.
    The supported presets take 11 numbered labels, with row 3 optionally included.
    """
    if side not in _REGIONS or image.mode != "RGBA" or image.size != (792, 458):
        raise ValueError("Expected a stock left or right RGBA preset at 792 by 458")
    all_rows = set(_REGIONS[side])
    if (any(type(i) is not int for i in labels)
            or set(labels) not in (all_rows, all_rows - {3})):
        raise ValueError("Incorrect set of preset label numbers")
    if any(not isinstance(s, str) or not 1 <= len(s) <= 80 or not s.isascii()
           or not s.isprintable() or s != s.strip() for s in labels.values()):
        raise ValueError("Expected nonempty printable English labels")
    if 3 in labels and labels[3] != "FPS Counter":
        raise ValueError("Unexpected frame-rate label")
    dimensions = b"".join(n.to_bytes(8, "little") for n in image.size)
    if hashlib.sha256(dimensions + image.tobytes()).hexdigest() != _SOURCE_DIGEST[side]:
        raise ValueError("The preset pixels differ from the supported source")
    font_bytes = font.read_bytes()
    if hashlib.sha256(font_bytes).hexdigest() != _FONT_DIGEST:
        raise ValueError("The local font differs from the supported Liberation Sans Narrow Bold")

    source = np.asarray(image)
    rgb = np.ascontiguousarray(source[:, :, :3])
    protected = _protected(side)
    permitted = np.zeros(protected.shape, np.uint8)
    stamps = []
    for number in sorted(labels):
        old_ink, (x, y), anchor = _source_ink(rgb, side, number, protected)
        permitted[y:y+old_ink.shape[0], x:x+old_ink.shape[1]] |= old_ink
        stamps.append(_place(labels[number], font_bytes, side, number, anchor, protected))

    old = permitted != 0
    background = source.copy()
    background[old, :3] = cv2.inpaint(rgb, permitted, 3, cv2.INPAINT_NS)[old]
    result = Image.fromarray(background)
    for stamp, x, y in stamps:
        result.alpha_composite(stamp, (x, y))
        ink = np.asarray(stamp.getchannel("A")) > 0
        permitted[y:y+stamp.height, x:x+stamp.width] |= ink
    result.putalpha(image.getchannel("A"))
    return result, Image.fromarray(permitted * 255)
