"""Translate supported help captions on locally supplied original panels."""
import argparse
import os
from pathlib import Path
from struct import unpack_from

from build_hud import local_member
from build_notice import load_lines, output_locations, write_members
from route_help_texture import render_pair

PREFIX = "BLUEPROTOCOL/Content/UI/Image/TutorialHelp/"
ARCHIVE = "blue_protocol_help_1_P.pak"
SIZE = (600, 240)
MIP_START = 326
MIP_BYTES = SIZE[0] * SIZE[1] * 4
MIP_END = MIP_START + MIP_BYTES

# Original header and export fingerprints, image catalog key and reviewed English digest.
PANELS = {
    "RouteGuide": (
        "3c33c235a6ce33eb6e13170c2b99fc5d33e30393088247313f6d526ad23af6ff",
        "a066873ee0fc10f631d1a797ab57c0f87f792493dc1ec108c927c93c9a084df0",
        "53b65c6c5b6aa107d5679bfef9b1f64f65115e6d67c81bc1532495233da44878",
        "6bf104208abb53096cc12451537d7298a60c2c318b41e40d79cdc196ddb9cac5",
    ),
    "UI_TutorialHelp00062": (
        "dc7f9cfcbdfaa4cdb1583bdc2740eb4ccada66581e38a0e59b3e1f9c4bf12fd4",
        "6c43be70f97b8d6e4bea883857f4d40bbb19fe57c938129106d4c567488e42b1",
        "ac427cebc99d00935c9703de702868230a5d31003c828449e093136b074cbf42",
        "274bfe6cd197c01e2459e95d31203284bf2b7bc98126b6a1cc3120f69b88087d",
    ),
    "UI_TutorialHelp00063": (
        "4fab7b87ed01afa083fadcd8541269b3b01e7c7c7b07d0b7a7018adb8adc7e27",
        "768e0ccfad85f5800182c659d832ec91a30df38b4100af0db33203a6aea8754c",
        "8c67e7a0607f7cd8e89df9141fec68307ddc0381b1c4fb793236c6472688892f",
        "26d946ad7f78c1a178dd2c2c9f4bb34159ee32867e20ae67feea6878d2e5d488",
    ),
    "UI_TutorialHelp00065": (
        "76d12af1a8890cfc0f9fb21cded6e80d137acf4615f7f060bdd75f97a5b13736",
        "fe2513eca716ff252299292448766641c0e65c313e36541625db909485b45c43",
        "92165bc5efc48eeac795009f2d155764cd058510652533d2c24b315c33e2167e",
        "fa2b680f599c04768a4f2855ace219ce54a1e645c10eb21bb7bd97876a952611",
    ),
    "UI_TutorialHelp00066": (
        "6ced93bce854211ca7e005f13253807a597cd7807d4459e60b38145d8e615dec",
        "0445b00be297e942493928ade4df5878ba19eb42b3dea41736ed33d18069bbe4",
        "a8b16d7f433a68bbcff8abac8af76fff6782642ff9f1ef6f9312019c15ec0063",
        "128fdf53e9a69e0681214f0a766c803c5fb60ffe99c884546506b1b116ba58bc",
    ),
    "LiquidMemory_guide_06": (
        "b2099758ccad3577572370d98ac4ca92884384862a5e9aad83658ce135bf73e3",
        "09adaa094b3b1e0e6d60deb673dea6ffe82e5d25a2daff67fe66c841970368e7",
        "13b5d75d219377e0f64cef4f7fb20effb10e20e92385aa1df313596b577a6c6a",
        "60309843b6a7eeca503d2eef76961560c19a15e660b35b5773bbfc1ef1ab22d7",
    ),
    "LiquidMemory_guide_07": (
        "4457278a53b9e305332986cc47d016f5c1e1425413241925bad446e7728de6bc",
        "703201f014992c50447c2f8cc48509139f85362ade4170b076567c5c09c26767",
        "38defdcc1d74a1027bd628d5ef59ba3c414795f0ed661b03ce05a68203578f6d",
        "0bdc01ee55f6d8185933cab8a49cee5e410e003de0f137342608d163776fe637",
    ),
    "LiquidMemory_guide_08": (
        "237d97be1c139b367b0c856b40a9d2275bab1220d4b3b033158c3f5549ac844a",
        "cd3bf01f0d8295fcccdf7ce3b1923c8c704659897fedb068a029b9c4ea65c299",
        "d6518c6cf80fe9a9e00b587b42699779aada92c57f7d880bc0aaae22a11a88f2",
        "98125032edbc4f008a5c7700d2ed95bdf819f4dace5e4140fe68edf574fe6a5e",
    ),
    "LiquidMemory_guide_09": (
        "84ac917194b26783dff28508ef5edf77d89c96687cc43b6ec8df7909bdfa94c4",
        "6abed575a583ddd1955302e62701c0eea07e25df82f986c0057a121690bd3397",
        "ee01c55844b04347d5b2d08c613d935b9da07535260ebce1910078c5168945c1",
        "753c038f65e334a403ac39b75b90eeb4e63198d3f3b08a6a34ab6074353b4d7f",
    ),
}


def available_panels(root, require_all):
    selected = {}
    for name, (header_hash, export_hash, key, text_hash) in PANELS.items():
        stem = PREFIX + name
        header_name = stem + ".uasset"
        export_name = stem + ".uexp"
        has_header = os.path.lexists(root / header_name)
        has_export = os.path.lexists(root / export_name)
        if not (has_header or has_export):
            if require_all and name != "RouteGuide":
                raise ValueError(f"Missing required original pair for {name}")
            continue
        if not (has_header and has_export):
            raise ValueError(f"Supply both original files for {name}")
        header = local_member(root, header_name, header_hash)
        export = local_member(root, export_name, export_hash)
        selected[name] = (header, export, key, text_hash)
    if not selected:
        raise ValueError("No supported original help panel pairs found")
    return selected


def render_export(original, name, english, font):
    from PIL import Image, ImageChops
    from help_lettering import render_body

    if (len(original) != MIP_END + 28 or unpack_from("<ii", original, MIP_START - 16) != (MIP_BYTES, MIP_BYTES)
            or unpack_from("<iii", original, MIP_END) != (*SIZE, 1)):
        raise ValueError(f"Unexpected pixel layout for {name}")
    stock = Image.frombytes("RGBA", SIZE, original[MIP_START:MIP_END], "raw", "BGRA")
    rendered, mask = render_body(stock.copy(), english, font, profile=name)
    if rendered.mode != "RGBA" or rendered.size != SIZE or mask.mode != "L" or mask.size != SIZE:
        raise ValueError(f"Invalid rendered texture or glyph mask for {name}")
    if ImageChops.difference(stock.getchannel("A"), rendered.getchannel("A")).getbbox():
        raise ValueError(f"Original transparency changed for {name}")
    if Image.composite(stock, rendered, mask).tobytes() != stock.tobytes():
        raise ValueError(f"Unexpected changes outside the effect lettering for {name}")
    box = mask.getbbox()
    if box is None or not (39 <= box[0] < box[2] <= 480 and 129 <= box[1] < box[3] <= 156):
        raise ValueError(f"Effect line is outside its reviewed area for {name}")
    mip = rendered.tobytes("raw", "BGRA")
    if mip == original[MIP_START:MIP_END]:
        raise ValueError(f"Expected a translated effect line for {name}")
    export = original[:MIP_START] + mip + original[MIP_END:]
    readback = Image.frombytes("RGBA", SIZE, export[MIP_START:MIP_END], "raw", "BGRA")
    if readback.tobytes() != rendered.tobytes():
        raise ValueError(f"Lossless rendered pixel readback failed for {name}")
    return export


def build(args):
    root, output = output_locations(args.input, args.output)
    selected = available_panels(root, args.require_all)
    lines = load_lines([(row[2], row[3]) for row in selected.values()])
    members = {}
    for (name, (header, original, _, _)), line in zip(selected.items(), lines):
        if name == "RouteGuide":
            header, export = render_pair(header, original, line, args.font)
        else:
            export = render_export(original, name, line, args.font)
        members[PREFIX + name + ".uasset"] = header
        members[PREFIX + name + ".uexp"] = export
    write_members(output, members, ARCHIVE if args.archive else None, "bp-help-")
    print(f"Translated one caption on each of {len(selected)} help panels in {output}")
    if args.archive:
        print(f"Wrote {output / ARCHIVE}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Extracted client root containing BLUEPROTOCOL")
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    parser.add_argument("--font", type=Path, required=True, help="Local Liberation Sans Bold font file")
    parser.add_argument("--archive", action="store_true", help="Also build a local help overlay archive")
    parser.add_argument("--require-all", action="store_true", help="Require all eight Liquid Memory panels")
    try:
        build(parser.parse_args())
    except (ImportError, OSError, ValueError) as error:
        parser.exit(1, f"Could not build the help panels: {error}\n")


if __name__ == "__main__":
    main()
