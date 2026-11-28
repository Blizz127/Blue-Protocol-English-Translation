"""Read a local Route Guide image and store its translated lettering losslessly."""

from hashlib import sha256
from struct import pack, pack_into, unpack_from
from zlib import crc32

from PIL import Image


SIZE = (600, 240)
HEADER_SHA256 = "3c33c235a6ce33eb6e13170c2b99fc5d33e30393088247313f6d526ad23af6ff"
EXPORT_SHA256 = "a066873ee0fc10f631d1a797ab57c0f87f792493dc1ec108c927c93c9a084df0"
PIXELS_SHA256 = "dc43a5f330f186b514dde0f24b9c211301d7628f2783911c696613bf998982bf"
BLOCK_START = 281
BLOCK_BYTES = SIZE[0] * SIZE[1] // 2
BGRA_BYTES = SIZE[0] * SIZE[1] * 4


def _string(text):
    value = text.encode("ascii") + bytes(1)
    return pack("<i", len(value)) + value


def _format_name(text):
    # Unreal serializes two 16-bit hashes after an ANSI name. Its older
    # case-insensitive CRC uses a forward table with a right-shifting state.
    insensitive = 0
    for byte in text.upper().encode("ascii"):
        entry = ((insensitive ^ byte) & 255) << 24
        for _ in range(8):
            polynomial = 0x04C11DB7 if entry & 0x80000000 else 0
            entry = ((entry << 1) ^ polynomial) & 0xFFFFFFFF
        insensitive = (insensitive >> 8) ^ entry
    sensitive = crc32(text.encode("utf-32-le"))
    return _string(text) + pack("<HH", insensitive & 0xFFFF, sensitive & 0xFFFF)


def decode_route(header, export):
    """Read the one supported original and verify the decoded pixel fingerprint."""
    if sha256(header).hexdigest() != HEADER_SHA256 or sha256(export).hexdigest() != EXPORT_SHA256:
        raise ValueError("Unsupported Route Guide texture pair")
    end = BLOCK_START + BLOCK_BYTES
    if (header[512:528] != _format_name("PF_DXT1")
            or export[237:249] != _string("PF_DXT1")
            or unpack_from("<IIIq", export, 261) != (0x48, BLOCK_BYTES, BLOCK_BYTES, len(header) + BLOCK_START)
            or unpack_from("<III", export, end) != (*SIZE, 1)):
        raise ValueError("Unexpected Route Guide name or mip layout")
    image = Image.frombytes("RGBA", SIZE, export[BLOCK_START:end], "bcn", 1)
    if sha256(image.tobytes()).hexdigest() != PIXELS_SHA256:
        raise ValueError("Unexpected Route Guide decoded pixels")
    return image


def _relocate(data, offset, delta, fmt):
    value, = unpack_from(fmt, data, offset)
    pack_into(fmt, data, offset, value + delta)


def _encode(header, export, rendered):
    # A raw BGRA mip preserves every decoded pixel. Both the name map and
    # the platform format string grow by four bytes. All offsets below refer
    # to the input until those strings are replaced.
    name = _format_name("PF_B8G8R8A8")
    platform_format = _string("PF_B8G8R8A8")
    header_growth = len(name) - len(_format_name("PF_DXT1"))
    string_growth = len(platform_format) - len(_string("PF_DXT1"))
    export_growth = string_growth + BGRA_BYTES - BLOCK_BYTES
    total_growth = header_growth + export_growth

    new_header = bytearray(header)
    # Header size, export table, import table, dependencies, asset registry,
    # and preload dependency offsets follow the changed name map.
    for offset in (24, 61, 69, 73, 165, 189):
        _relocate(new_header, offset, header_growth, "<i")
    _relocate(new_header, 169, total_growth, "<q")  # End of package data
    _relocate(new_header, 745, export_growth, "<q")  # Export serial size
    _relocate(new_header, 753, header_growth, "<q")  # Export serial offset
    new_header[512:528] = name

    prefix = bytearray(export[:BLOCK_START])
    _relocate(prefix, 217, total_growth, "<q")  # Next platform record
    pack_into("<iiq", prefix, 265, BGRA_BYTES, BGRA_BYTES, len(new_header) + BLOCK_START + string_growth)
    prefix[237:249] = platform_format
    payload = rendered.tobytes("raw", "BGRA")
    tail = export[BLOCK_START + BLOCK_BYTES:]
    return bytes(new_header), bytes(prefix) + payload + tail


def render_pair(header, original, english, font):
    """Return a new cooked header and export from a local original pair."""
    from help_lettering import render_route

    stock = decode_route(header, original)
    rendered, mask = render_route(stock.copy(), english, font)
    if (rendered.size != SIZE or rendered.mode != "RGBA"
            or mask.size != SIZE or mask.mode != "L" or not mask.getbbox()
            or mask.point([0] + [255] * 254 + [0]).getbbox()):
        raise ValueError("Invalid Route Guide lettering mask or image")
    left, top, right, bottom = mask.getbbox()
    if not (4 <= left < right <= 288 and 69 <= top < bottom <= 88):
        raise ValueError("Route Guide lettering exceeds the reviewed caption area")
    if rendered.getchannel("A").tobytes() != stock.getchannel("A").tobytes():
        raise ValueError("Route Guide lettering changed original transparency")
    if Image.composite(stock, rendered, mask).tobytes() != stock.tobytes() or rendered.tobytes() == stock.tobytes():
        raise ValueError("Route Guide lettering is empty or exceeds its glyph mask")
    return _encode(header, original, rendered)
