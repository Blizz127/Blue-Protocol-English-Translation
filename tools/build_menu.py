"""Build a Japanese-locale menu text resource from an owned, extracted client."""

import argparse
import os
from pathlib import Path
import re
import tempfile

from build_patch import CATALOGS, add_unique, array, hashed, read_json, text_value
from menu_resource import RESOURCE_MEMBER, apply_menu_resource
from menu_sources import find_menu_sources


ARCHIVE_NAME = "blue_protocol_menus_1_P.pak"


def read_catalog(path, field):
    data = read_json(path)
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("Unsupported menu catalog version")
    result = {}
    for row in array(data, "entries"):
        digest = hashed(row, "key_sha256")
        if field == "english":
            value = text_value(row, field)
            if not value.strip():
                raise ValueError("Empty menu translation")
        else:
            value = row[field]
            if type(value) is not int or not 0 <= value <= 0xffffffff:
                raise ValueError("Expected an unsigned 32-bit runtime key hash")
        add_unique(result, digest, value)
    if not result:
        raise ValueError("Empty menu catalog")
    return result


def build(args):
    root = args.input.resolve(strict=True)
    output = args.output
    if os.path.lexists(output):
        raise ValueError("Choose a new output directory")
    if root in output.resolve().parents or not output.parent.is_dir():
        raise ValueError("Choose an output outside the input tree with an existing parent")
    resource = root / RESOURCE_MEMBER
    if resource.resolve() != resource or not resource.is_file():
        raise ValueError(f"Missing original local {RESOURCE_MEMBER}")

    english = read_catalog(args.catalog, "english")
    runtime = read_catalog(args.runtime_hashes, "unreal_key_hash")
    if english.keys() != runtime.keys():
        raise ValueError("The two menu catalogs cover different lookup keys")
    sources = find_menu_sources(root, set(english))
    if not sources:
        raise ValueError("No matching menu text found in the extracted widgets")
    missing = len(english) - len(sources)
    if missing and args.require_all:
        raise ValueError(f"Missing {missing} of {len(english)} exact menu source bindings")
    updates = []
    for lookup, (namespace, key, source) in sources.items():
        if namespace or not re.fullmatch(r"[a-fA-F0-9]{32}", key):
            raise ValueError("Unexpected menu key format")
        updates.append((namespace, key, source, english[lookup], 0, runtime[lookup]))
    rebuilt = apply_menu_resource(resource.read_bytes(), updates)

    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        staging = Path(tmp) / "ready"
        member = staging / RESOURCE_MEMBER
        member.parent.mkdir(parents=True)
        member.write_bytes(rebuilt)
        if member.read_bytes() != rebuilt:
            raise OSError("Menu resource failed file readback")
        if args.archive:
            from overlay_archive import write_overlay
            write_overlay(staging, [RESOURCE_MEMBER], staging / ARCHIVE_NAME)
        output.mkdir()
        moved = []
        try:
            for child in staging.iterdir():
                dest = output / child.name
                child.rename(dest)
                moved.append(dest)
        except BaseException:
            for dest in reversed(moved):
                dest.rename(staging / dest.name)
            output.rmdir()
            raise
    print(f"Built {len(sources)} menu entries from verified local text. {missing} catalog entries absent.")
    if args.archive:
        print(f"Wrote {output / ARCHIVE_NAME}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path,
                        help="Extracted content root containing BLUEPROTOCOL/Content")
    parser.add_argument("--output", required=True, type=Path, help="New output directory")
    parser.add_argument("--catalog", type=Path, default=CATALOGS / "menu-inline.json")
    parser.add_argument("--runtime-hashes", type=Path, default=CATALOGS / "menu-runtime.json")
    parser.add_argument("--require-all", action="store_true",
                        help="Require every catalog entry to match in the local widgets")
    parser.add_argument("--archive", action="store_true",
                        help="Also build a local text overlay archive")
    try:
        build(parser.parse_args())
    except (KeyError, OSError, TypeError, ValueError) as error:
        parser.exit(1, f"Could not build the menu patch: {error}\n")


if __name__ == "__main__":
    main()
