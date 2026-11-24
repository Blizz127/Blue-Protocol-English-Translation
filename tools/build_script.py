"""Build translated dialogue from the matching script packages in an owned client."""

import argparse
import json
import os
from pathlib import Path
import re
from struct import pack, pack_into
import tempfile

from build_patch import CATALOGS, add_unique, array, digest, hashed, read_json, text_value
from native_tables import _Export, _string, _summary
from overlay_archive import write_overlay


SCRIPT_ROOT = Path("BLUEPROTOCOL", "Content", "Script")
ARCHIVE_NAME = "blue_protocol_script_1_P.pak"
FUNCTION = re.compile(r"[ \t]*function[ \t]+([A-Za-z_]\w*)[ \t]*\([^()]*\)[ \t]*")
CALL = re.compile(r'[ \t]*(?P<name>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\("(?P<body>(?:[^"\\]|\\.)*)"\)[ \t]*;?[ \t]*')


def read_index(catalog_path, sources_path):
    def rows(path):
        data = read_json(path)
        if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
            raise ValueError("Unsupported script catalog version")
        return array(data, "entries")

    english = {}
    for row in rows(catalog_path):
        value = text_value(row, "english")
        if (not value.strip() or '"' in value or any(not char.isprintable() for char in value)
                or re.search(r"\\(?!n)", value)):
            raise ValueError("Expected a plain English dialogue literal with optional line breaks")
        add_unique(english, hashed(row, "key_sha256"), value)

    groups = {}
    registered = set()
    for row in rows(sources_path):
        key = hashed(row, "key_sha256")
        line = row["source_line"]
        if key not in english or key in registered or type(line) is not int or line < 1:
            raise ValueError("Invalid or duplicate script source binding")
        path_hash = hashed(row, "asset_path_sha256")
        pins = hashed(row, "uasset_sha256"), hashed(row, "uexp_sha256")
        pair, bindings = groups.setdefault(path_hash, (pins, {}))
        if pair != pins:
            raise ValueError("Conflicting package hashes for the same script")
        add_unique(bindings, line, (key, english[key]))
        registered.add(key)
    if not registered or registered != english.keys():
        raise ValueError("Script catalogs must cover the same nonempty set of keys")
    return groups


def code_field(asset, export):
    serial_at, names = _summary(asset, export, "SBScriptAsset")
    parser = _Export(export, names)
    limit = len(export) - 8
    name, field = parser.property(0, limit)
    if (name != "Code" or field.kind != "StrProperty" or field.end + 8 != limit
            or parser.name(field.end, limit) != "None" or export[limit:limit + 4] != bytes(4)):
        raise ValueError("Unexpected script property or object trailer")
    code, end = _string(export, field.start, field.end)
    if end != field.end:
        raise ValueError("Unexpected data after the script string")
    return serial_at, field, code


def translated_code(logical, code, bindings):
    # The binding pins the entire pair. Derive the within-file identity again
    # from each local function, call ordinal, and original quoted literal.
    function = None
    ordinals = {}
    applied = set()
    lines = code.splitlines(keepends=True)
    for number, line in enumerate(lines, start=1):
        body = line.rstrip("\r\n")
        declaration = FUNCTION.fullmatch(body)
        if declaration:
            function = declaration[1]
            ordinals = {}
        elif body.strip() == "end":
            function = None
        call = CALL.fullmatch(body)
        if function and call:
            callee, literal = call["name"], call["body"]
            ordinal = ordinals.get(callee, 0) + 1
            ordinals[callee] = ordinal
            if number in bindings:
                key, english = bindings[number]
                identifier = [logical, function, callee, ordinal, 0, digest(literal.encode())]
                lookup = digest(json.dumps(identifier, ensure_ascii=False, separators=(",", ":")).encode())
                if lookup != key or literal.count(r"\n") != english.count(r"\n"):
                    raise ValueError(f"Script identity or line breaks differ at line {number}")
                start, end = call.span("body")
                lines[number - 1] = line[:start] + english + line[end:]
                applied.add(number)
    if applied != bindings.keys():
        raise ValueError("Some bound dialogue calls are absent")
    return "".join(lines)


def rebuild(asset, export, logical, bindings):
    serial_at, field, original = code_field(asset, export)
    translated = translated_code(logical, original, bindings)
    body = (translated + chr(0)).encode("utf-16-le")
    value = pack("<i", -(len(body) // 2)) + body
    patched_export = bytearray(export[:field.start] + value + export[field.end:])
    pack_into("<i", patched_export, field.size_at, len(value))
    patched_asset = bytearray(asset)
    pack_into("<q", patched_asset, serial_at, len(patched_export) - 4)
    pack_into("<q", patched_asset, 169, len(asset) + len(patched_export) - 4)
    result = bytes(patched_asset), bytes(patched_export)
    if code_field(*result)[2] != translated:
        raise ValueError("Rebuilt script failed readback")
    return result


def build(args):
    root = args.input.resolve(strict=True)
    output = args.output
    script_root = root / SCRIPT_ROOT
    if not script_root.is_dir() or script_root.resolve() != script_root:
        raise ValueError(f"The input must contain a local {SCRIPT_ROOT.as_posix()} directory")
    if os.path.lexists(output) or root in output.resolve().parents or not output.parent.is_dir():
        raise ValueError("Choose a new output outside the input tree with an existing parent")
    groups = read_index(args.catalog, args.sources)
    paths = []
    applied = 0
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        staging = Path(tmp) / "ready"
        for directory, dirs, files in os.walk(script_root):
            current = Path(directory)
            dirs[:] = sorted(name for name in dirs if not (current / name).is_symlink())
            for filename in sorted(files):
                asset = current / filename
                if asset.suffix != ".uasset":
                    continue
                logical = asset.relative_to(root).with_suffix("").as_posix()
                group = groups.get(digest(logical.encode()))
                if group is None:
                    continue
                export = asset.with_suffix(".uexp")
                if any(p.is_symlink() or not p.is_file() for p in (asset, export)):
                    raise ValueError(f"Expected an intact local pair for {logical}")
                header, data = asset.read_bytes(), export.read_bytes()
                pins, bindings = group
                if (digest(header), digest(data)) != pins:
                    raise ValueError(f"The original script package differs at {logical}")
                rebuilt = rebuild(header, data, logical, bindings)
                for source, contents in zip((asset, export), rebuilt):
                    name = source.relative_to(root)
                    target = staging / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as stream:
                        stream.write(contents)
                    if target.read_bytes() != contents:
                        raise OSError(f"Script package failed file readback at {name}")
                    paths.append(name.as_posix())
                applied += len(bindings)

        missing = sum(len(lines) for _, lines in groups.values()) - applied
        if not applied or (missing and args.require_all):
            raise ValueError(f"Matched {applied} dialogue entries; {missing} entries absent")
        if args.archive:
            write_overlay(staging, paths, staging / ARCHIVE_NAME)
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
    print(f"Built {applied} dialogue entries in {len(paths) // 2} scripts; {missing} entries absent.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Extracted client content root")
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    parser.add_argument("--catalog", type=Path, default=CATALOGS / "script.json")
    parser.add_argument("--sources", type=Path, default=CATALOGS / "script-sources.json")
    parser.add_argument("--require-all", action="store_true", help="Require all dialogue entries")
    parser.add_argument("--archive", action="store_true", help="Also write a local overlay archive")
    try:
        build(parser.parse_args())
    except (KeyError, TypeError, ValueError, OSError) as error:
        parser.exit(1, f"Could not build the script patch: {error}\n")


if __name__ == "__main__":
    main()
