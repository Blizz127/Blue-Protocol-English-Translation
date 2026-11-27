"""Translate the two HUD preset diagrams from locally extracted Japanese client files."""
import argparse
from hashlib import sha256
from pathlib import Path
from struct import unpack_from

from build_notice import load_lines, output_locations, write_members

PACKAGE = "BLUEPROTOCOL/Content/UI/Option/HUD/UI_OptionMenuHud"
ARCHIVE = "blue_protocol_hud_1_P.pak"
SIZE = (792, 458)
MIP_START = 285
MIP_BYTES = SIZE[0] * SIZE[1] * 4
MIP_END = MIP_START + MIP_BYTES
# Each side has its own stock package header and export.
STOCK = {
    "Left": (
        "4ed9f40812523734e88cca78e6b9b9fecfe5aade0d1e6ceb781cd6912f8d90fc",
        "63e2c9cc63b68f4b3a6b438df6a3946cd285d7a44170528d8e94f175185c0af4",
    ),
    "Right": (
        "059f2a82f9d9db397247afb1dd5aeac8888b08c8a9cd67be8e5f199038d95bec",
        "9c59394af2cbb07e9f9e0329a2dfad7271def8d8d68451e773f6398ac06e3423",
    ),
}
# Each row binds its diagram position to the signed-off text and its two catalog identities.
# Columns are the row number, English text digest, left key and right key.
LABELS = (
    (1, "bb8cf80a391ef64d0b4552cee52d1abe3127e1c9d790ac304b3fb815b9db6f58",
     "a6a3d12cf46908c76dceefccea1a981f7ab3276adfaa378aafd5a7dd84428b91",
     "62d65e4f1199e0fce7c72c230b1b2ac5026fe4585d668d7ce80fba9b74829487"),
    (2, "96f3a1639575313931780b7eb7a76f13e1319ef6379a5b91d921bffd9d4cadf5",
     "7192c56edeaeca643dcc2b6cd6765f2fde364b04aabcb11877157ec173dcff90",
     "b11cd2dff8a39ce78a0c6f98c2907b3247544f88908266c81ad0056b518adbb5"),
    (3, "bdc6ce64a0ce68362109b189fb11077ea70bfbd2aa0973d53e142ad444590e55",
     "8ffe8133b6aad633360606950a7188207e827cedbfd8d69483d319d5743c4c2f",
     "70e63a4f698584f24d3daca662bbc0178ca6a3cacf1f16a64bf5e1601a48f401"),
    (4, "77e13944c3f2944a5056fcfef970b7228305a0f1d8403dbefda71ae26ad6b6fd",
     "7b08cfa2eb7b22697eedbb7b00f4ea12ccdac8bf5b2244b85084690df54b7cfa",
     "82e56ad88b0f5efc2a535c64a69033bbaeb4487f50bac4904858d01d0f94a190"),
    (5, "de8e456e653aab148fe7eb6f858c74cfa2c5e20ea40d69beeb767e43391be5e5",
     "510cb42ad1c00dd3bae62fb022c7fab19cd57328746cc55b8d719cba139dd54c",
     "eec7073f867b81eeb604b996ad5f0b1481369d226194fb5886bb2c2d319aad44"),
    (6, "f385a4fc51ee052f23872ec7ea1207d38857165daf951fbd0aec424ac0436cf9",
     "7fb3f1b517eced9e954e62269a8b629a82c1b4ce770ddc0856b8ef522ed84183",
     "9c8c3f1c1dacc9f7481e91f24aacf36ec191a95357e9c14ec0f68ebfae73a65e"),
    (7, "cd1452ba27df78d31d9d608c74532d19924084037ed5e8294fa3f67e00f2f272",
     "2af62d4be10d80e042b61ca35b84ee9d3ee49cfae44396cb3657d95f683d2a7a",
     "89a14433bf858e9046c4ef570bc1abb89a1510c4f01c755f42e6a80730be20e2"),
    (9, "0fcd75494406c2fab36873e2dd855f31bb5e243803af086d9dfe0489af0920ae",
     "b5d51497507a2cad98bc989e875f7bf5695898a9f522667aca863f443f97018f",
     "b071d7b76860f4880170f8ceef76242058f1bb36caf78a4af3f3e8bd17f0bc5c"),
    (10, "b1b086e014f189bf68a02149a05afa09db0fdd1444e2326a8bdcdd84d177863a",
     "1300eabda6f1072961f6386bbacd045b9009b9dc609590d19be8e586df6da133",
     "0f0ca751cd3dfe8f3ef29a5d96fed61a0cd1921d9510f86e3dc9306a6a0fb402"),
    (12, "f34bbcbc4eaf14082e49f4bd177988c16d456426f0a8d60e35f95f32d02fd894",
     "c9833f437eaf38c40dce8ce51d91b651a7962c9fcd72cedb01df9b08da8e2cbf",
     "f9d6049cfea2fdb6cfbbeed46491ff67aba42fc16badefb508c2674f7700d6bc"),
    (13, "8749543b7d8b166d5aebc955fbde47bdcc3f2e58d930967adb25bdb454314e0b",
     "4fe6ecdd149dc4be4a04322f465dc6f4ada226e63e918eac6e42c09a7293a2d3",
     "97d90ae625404aec7440820b4b26dd08fe099ba14c824efe0fe38f55eec150f7"),
    (17, "f999b89a4e9f6db40f9d26d26f29c7f3d20d0d1dfeb44b6c3ffe700fa0c2d397",
     "e939fa4b2bd0b7007638b5e620eb374d815790583ef1d814eefea22e500fbce9",
     "f68f693a9d991c7ea83986650f118677af8a5ca706b79280b54f06f8621714b1"),
)


def local_member(root, name, expected):
    path = root / name
    if path.resolve(strict=True) != path or not path.is_file():
        raise ValueError(f"Expected the original local file {name}")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected:
        raise ValueError(f"Unsupported source fingerprint for {name}")
    return raw


def rebuild(side, source, labels, font):
    from PIL import Image, ImageChops
    from hud_lettering import render

    if (len(source) != MIP_END + 28 or unpack_from("<ii", source, MIP_START - 16) != (MIP_BYTES, MIP_BYTES)
            or unpack_from("<iii", source, MIP_END) != (*SIZE, 1)):
        raise ValueError(f"Unexpected {side} HUD pixel layout")
    original = Image.frombytes("RGBA", SIZE, source[MIP_START:MIP_END], "raw", "BGRA")
    painted, mask = render(original.copy(), labels, side.lower(), font)
    if painted.size != SIZE or painted.mode != "RGBA" or mask.size != SIZE or mask.mode != "L":
        raise ValueError(f"Invalid {side} HUD rendering")
    if ImageChops.difference(original.getchannel("A"), painted.getchannel("A")).getbbox():
        raise ValueError(f"HUD rendering changed original transparency on the {side} diagram")
    inverse = Image.composite(original, painted, mask)
    if inverse.tobytes() != original.tobytes():
        raise ValueError(f"HUD rendering changed pixels outside the lettering on the {side} diagram")
    mip = painted.tobytes("raw", "BGRA")
    if mip == source[MIP_START:MIP_END]:
        raise ValueError(f"Expected new lettering on the {side} diagram")
    result = source[:MIP_START] + mip + source[MIP_END:]
    readback = Image.frombytes("RGBA", SIZE, result[MIP_START:MIP_END], "raw", "BGRA")
    if readback.tobytes() != painted.tobytes():
        raise ValueError(f"HUD lossless pixel readback failed for the {side} diagram")
    return result


def build(args):
    root, output = output_locations(args.input, args.output)
    members = {}
    for column, side in enumerate(("Left", "Right"), start=2):
        header_name = PACKAGE + side + ".uasset"
        export_name = PACKAGE + side + ".uexp"
        header_pin, export_pin = STOCK[side]
        header = local_member(root, header_name, header_pin)
        original = local_member(root, export_name, export_pin)
        lines = load_lines([(row[column], row[1]) for row in LABELS])
        labels = {row[0]: line for row, line in zip(LABELS, lines)}
        members[header_name] = header
        members[export_name] = rebuild(side, original, labels, args.font)

    write_members(output, members, ARCHIVE if args.archive else None, "bp-hud-")
    print(f"Translated {len(LABELS)} labels on each HUD preset diagram in {output}")
    if args.archive:
        print(f"Wrote {output / ARCHIVE}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Extracted client root containing BLUEPROTOCOL")
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    parser.add_argument("--font", type=Path, required=True, help="Local Liberation Sans Narrow Bold font file")
    parser.add_argument("--archive", action="store_true", help="Also build a local HUD overlay archive")
    try:
        build(parser.parse_args())
    except (ImportError, OSError, ValueError) as error:
        parser.exit(1, f"Could not build the HUD diagrams: {error}\n")


if __name__ == "__main__":
    main()
