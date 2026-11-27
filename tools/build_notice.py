"""Build the English startup notice from an extracted local client and two local font files."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


PACKAGE = "BLUEPROTOCOL/Content/UI/Startup/UI_StartupCaution1"
CATALOG = Path(__file__).resolve().parents[1] / "translations" / "image-labels.json"
ARCHIVE = "blue_protocol_notice_1_P.pak"
# Catalog keys are in display order. The text digests identify the reviewed lines.
LINES = (
    ("b449ce07220a9f352f8faa7223e186e2df03c2b6f6268026f6b35b5aa3a66c6e", "6c430fe663f267ddf181831541f115da8f96ac5cf2787fea20368873ba9e78bd"),
    ("ac222d9ccc937a07eb6cd34796853589d832bf6815184225b312abb304db76eb", "583097ec5be69bea7a09e88d54749108b19d3f5a7a9a167b1212b46318b63652"),
    ("8e07790c59be61a5b2e51b6dbe5e35a05791405ba01a4b656f8186687a55cbbf", "895096a2f45e160582f992ee8e7efa845896d25eb3adcccd921d31d0f1037831"),
    ("829a5db62496736125f91a10b0f71544b0a425c7d47f84d29943682913df3632", "59b9835df3c069fe46be36ed2bee26fd54e095d42737ad5c47e6427741a6ac67"),
    ("6092bd0ccf2ce0c1a8371321ee7395a466ae299795125a7fbc0000b150924c40", "69ce56f644c128a59a5ec49ffe2ed6e981c6ec5fa7c79b8159a490e3b10ddc35"),
)


def load_lines():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported image label catalog")
    if not isinstance(data.get("entries"), list):
        raise ValueError("Missing image label entries")
    labels = {}
    for entry in data["entries"]:
        if not isinstance(entry, dict) or entry.keys() != {"key_sha256", "english"}:
            raise ValueError("Invalid image label")
        key, line = entry["key_sha256"], entry["english"]
        if not isinstance(key, str) or not isinstance(line, str) or key in labels:
            raise ValueError("Invalid or duplicate image label")
        labels[key] = line
    result = []
    for key, expected in LINES:
        line = labels.get(key)
        if line is None or hashlib.sha256(line.encode("utf-8")).hexdigest() != expected:
            raise ValueError("The image catalog does not contain the five matching startup lines")
        result.append(line)
    return result


def build(args):
    from notice_lettering import render_notice
    from notice_texture import decode_notice, encode_notice

    root = args.input.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Expected an extracted client directory")
    if os.path.lexists(args.output):
        raise ValueError("Choose a new output directory")
    output = args.output.resolve()
    if root == output or root in output.parents or not output.parent.is_dir():
        raise ValueError("Choose a new output outside the extracted client with an existing parent")
    paths = [PACKAGE + suffix for suffix in (".uasset", ".uexp")]
    inputs = []
    for name in paths:
        source = root / name
        if source.resolve(strict=True) != source or not source.is_file():
            raise ValueError(f"Expected original local file {name}")
        inputs.append(source.read_bytes())
    original = decode_notice(*inputs)
    rendered = render_notice(original, load_lines(), args.title_font, args.body_font)
    result = encode_notice(inputs[0], inputs[1], rendered)
    if result == inputs[1]:
        raise ValueError("The notice export was unchanged")

    with tempfile.TemporaryDirectory(prefix="bp-notice-", dir=output.parent) as temporary:
        staging = Path(temporary)
        for name, expected in zip(paths, (inputs[0], result)):
            member = staging / name
            member.parent.mkdir(parents=True, exist_ok=True)
            member.write_bytes(expected)
            if member.read_bytes() != expected:
                raise OSError(f"Notice member failed readback: {name}")
        if args.archive:
            from overlay_archive import write_overlay
            write_overlay(staging, paths, staging / ARCHIVE)
        output.mkdir()
        moved = []
        try:
            for child in staging.iterdir():
                target = output / child.name
                child.rename(target)
                moved.append(target)
        except BaseException:
            for target in reversed(moved):
                target.rename(staging / target.name)
            output.rmdir()
            raise
    print(f"Built the five English startup lines in {output}")
    if args.archive:
        print(f"Wrote {output / ARCHIVE}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Extracted client root containing BLUEPROTOCOL")
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    parser.add_argument("--title-font", type=Path, required=True, help="Local Liberation Sans Regular font file")
    parser.add_argument("--body-font", type=Path, required=True, help="Local Liberation Sans Bold font file")
    parser.add_argument("--archive", action="store_true", help="Also build the local notice overlay archive")
    try:
        build(parser.parse_args())
    except (ImportError, OSError, ValueError) as error:
        parser.exit(1, f"Could not build the startup notice: {error}\n")


if __name__ == "__main__":
    main()
