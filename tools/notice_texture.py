"""Edit the supported startup notice in an already exported local texture pair.

Both operations require the original header and export. The encoder returns a
new export. The caller keeps the original header and supplies its own rendering.
"""
from hashlib import sha256
from struct import unpack_from

from PIL import Image, ImageChops

SIZE = (1920, 1080)
BLOCK_SIZE = 4
BLOCK_BYTES = 16
HEADER_BYTES = 842
EXPORT_BYTES = 2_073_909
HEADER_SHA256 = "6c2ed34c448bfbb50f04bdd4d1ea7a5a54c6831c3d0756573ae16e4409637b60"
EXPORT_SHA256 = "dfa6ac42d36051451bc10a0369fd6ff5d21a2f6128018a798d029806a5fe95d3"
MIP_START = 281
MIP_BYTES = (SIZE[0] // BLOCK_SIZE) * (SIZE[1] // BLOCK_SIZE) * BLOCK_BYTES
MIP_END = MIP_START + MIP_BYTES


def decode_notice(header: bytes, export: bytes) -> Image.Image:
    """Return a fresh RGBA image for the supported original BC3 texture."""
    for label, data, length, digest in (
        ("header", header, HEADER_BYTES, HEADER_SHA256),
        ("export", export, EXPORT_BYTES, EXPORT_SHA256),
    ):
        if not isinstance(data, bytes) or len(data) != length or sha256(data).hexdigest() != digest:
            raise ValueError(f"Unsupported startup notice {label}")

    dimensions = (*SIZE, 1)
    flags, count, stored_size, stream_offset = unpack_from("<IIIq", export, 261)
    if (unpack_from("<III", export, 225) != dimensions
            or unpack_from("<III", export, MIP_END) != dimensions
            or (flags, count, stored_size) != (0x48, MIP_BYTES, MIP_BYTES)
            or stream_offset - len(header) != MIP_START
            or MIP_END + 28 != len(export)):
        raise ValueError("Invalid inline startup notice mip bounds")
    return Image.frombytes("RGBA", SIZE, export[MIP_START:MIP_END], "bcn", 3)


def _encode_block(pixels: bytes, old_pixels: bytes, old_block: bytes) -> bytes:
    # BC3 chooses RGB and alpha separately. Very faint padding can otherwise
    # pull a shared color endpoint away from the visible text in the same block.
    padding = [offset for offset in range(0, len(pixels), 4) if pixels[offset + 3] <= 1]
    choices = [pixels]
    if padding and len(padding) < 16:
        visible = [offset for offset in range(0, len(pixels), 4) if pixels[offset + 3] > 1]
        weights = sum(pixels[offset + 3] for offset in visible)
        mean = []
        for channel in range(3):
            total = sum(pixels[offset + channel] * pixels[offset + 3] for offset in visible)
            mean.append((total + weights // 2) // weights)
        for decrease in (0, 32, 64, 80):
            fill = bytes(max(0, value - decrease) for value in mean)
            trial = bytearray(pixels)
            for offset in padding:
                trial[offset:offset + 3] = fill
            if trial not in choices:
                choices.append(bytes(trial))
    elif len(padding) == 16:
        blank = bytearray(len(pixels))
        blank[3::4] = pixels[3::4]
        if blank != pixels:
            choices.append(bytes(blank))

    # Stack the alternatives vertically. Each four rows encode independently.
    size = (4, 4 * len(choices))
    candidates = Image.frombytes("RGBA", size, b"".join(choices)).tobytes("bcn", 3)
    if len(candidates) != BLOCK_BYTES * len(choices):
        raise ValueError("Unexpected BC3 encoder output size")
    selected = candidates[:BLOCK_BYTES]
    if len(choices) > 1:
        decoded = Image.frombytes("RGBA", size, candidates, "bcn", 3).tobytes()
        samples = [(i, pixels[i], pixels[(i // 4) * 4 + 3] ** 2)
                   for i in range(64) if i % 4 != 3 and pixels[(i // 4) * 4 + 3]]
        best = None
        for index in range(len(choices)):
            entry = candidates[BLOCK_BYTES * index:BLOCK_BYTES * (index + 1)]
            if entry[:8] != candidates[:8]:
                raise ValueError("BC3 color fitting changed the encoded alpha")
            # Squared display error at each target alpha. Prefer the untouched
            # input as compressor source when alternatives tie.
            error = sum(weight * (target - decoded[64 * index + channel]) ** 2
                        for channel, target, weight in samples)
            if best is None or error < best:
                best = error
                selected = entry
    if pixels[3::4] == old_pixels[3::4]:
        selected = old_block[:8] + selected[8:]
    return selected


def encode_notice(header: bytes, export: bytes, rendered: Image.Image) -> bytes:
    """Encode only the BC3 blocks touched by different RGBA samples."""
    original = decode_notice(header, export)
    if not isinstance(rendered, Image.Image) or rendered.mode != "RGBA" or rendered.size != SIZE:
        raise ValueError("The rendered notice must be a 1920 by 1080 RGBA image")

    # A change to RGB beneath fully transparent alpha still changes the data.
    r, g, b, a = ImageChops.difference(original, rendered).split()
    changed = ImageChops.lighter(ImageChops.lighter(r, g), ImageChops.lighter(b, a))
    bounds = changed.getbbox()
    if bounds is None:
        return export

    left, top, right, bottom = bounds
    left = left // BLOCK_SIZE * BLOCK_SIZE
    right = (right + BLOCK_SIZE - 1) // BLOCK_SIZE * BLOCK_SIZE
    result = bytearray(export)
    blocks_per_row = SIZE[0] // BLOCK_SIZE

    for y in range(top // BLOCK_SIZE * BLOCK_SIZE, bottom, BLOCK_SIZE):
        columns, _ = changed.crop((left, y, right, y + BLOCK_SIZE)).getprojection()
        for x in range(left, right, BLOCK_SIZE):
            index = x - left
            if not any(columns[index:index + BLOCK_SIZE]):
                continue
            region = (x, y, x + BLOCK_SIZE, y + BLOCK_SIZE)
            offset = MIP_START + BLOCK_BYTES * (y // BLOCK_SIZE * blocks_per_row + x // BLOCK_SIZE)
            if offset < MIP_START or offset + BLOCK_BYTES > MIP_END:
                raise ValueError("Invalid startup notice block position")
            block = _encode_block(rendered.crop(region).tobytes(), original.crop(region).tobytes(),
                                  export[offset:offset + BLOCK_BYTES])
            result[offset:offset + BLOCK_BYTES] = block
    return bytes(result)
