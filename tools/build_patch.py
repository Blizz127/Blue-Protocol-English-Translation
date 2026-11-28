"""Build English text from local game data into a separate output."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile


CATALOGS = Path(__file__).resolve().parents[1] / "translations"
TEXT_ROOT = Path("BLUEPROTOCOL", "Content", "Text")
ARCHIVE_NAME = "blue_protocol_english_1_P.pak"


def unique_fields(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"Duplicate JSON field {key!r}")
        obj[key] = value
    return obj


def read_json(path):
    with path.open(encoding="utf-8-sig") as stream:
        return json.load(stream, object_pairs_hook=unique_fields)


def array(obj, key):
    if not isinstance(obj, dict) or not isinstance(obj.get(key), list):
        raise ValueError(f"Expected an array in {key!r}")
    return obj[key]


def digest(value):
    return hashlib.sha256(value).hexdigest()


def hashed(obj, key):
    value = obj[key]
    if not isinstance(value, str) or not re.fullmatch("[a-f0-9]{64}", value):
        raise ValueError(f"Invalid SHA-256 in {key!r}")
    return value


def text_value(obj, key):
    value = obj[key]
    if not isinstance(value, str) or "\0" in value:
        raise ValueError(f"Invalid text in {key!r}")
    return value


def identity(table, row):
    if not isinstance(table, str) or type(row["id"]) not in (str, int):
        raise ValueError("Expected a table name and a string or integer row ID")
    return table, row["id"]


def add_unique(index, key, value):
    if key in index:
        raise ValueError(f"Duplicate catalog binding {key!r}")
    index[key] = value


def replacement(row):
    return hashed(row, "source_sha256"), text_value(row, "english")


def build_service(args, catalog):
    index = {}
    for entry in array(catalog, "entries"):
        add_unique(index, identity(entry["table"], entry), replacement(entry))

    tables = read_json(args.input)
    if not isinstance(tables, list):
        raise ValueError("Expected a list of text tables in the input JSON")
    matched = set()
    changed = already = drift = 0
    for table in tables:
        for row in array(table, "texts"):
            key = identity(table["name"], row)
            if key not in index:
                continue
            if key in matched:
                raise ValueError(f"Ambiguous input row {key!r}")
            matched.add(key)
            source_hash, english = index[key]
            original = text_value(row, "text")
            if original == english:
                already += 1
            elif digest(original.encode("utf-8")) == source_hash:
                row["text"] = english
                changed += 1
            else:
                drift += 1

    if drift and args.strict:
        raise ValueError(f"{drift} present service rows differed from the catalog source")
    if not (changed or already):
        raise ValueError("No supported service rows matched this input")
    with tempfile.TemporaryDirectory(dir=args.output.parent) as tmp:
        finished = Path(tmp) / "texts.json"
        with finished.open("w", encoding="utf-8", newline="\n") as out:
            json.dump(tables, out, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            out.write("\n")
        if read_json(finished) != tables:
            raise ValueError("Completed service JSON failed readback")
        # A hard link exposes the complete file and refuses an existing destination.
        os.link(finished, args.output)
    print(f"Changed {changed} service rows. {already} already English, "
          f"{drift} source mismatches skipped, {len(index) - len(matched)} catalog rows absent.")


def exact_fields(obj, fields):
    if not isinstance(obj, dict) or set(obj) != set(fields):
        raise ValueError("Unexpected board template catalog fields")


def native_index(catalog, board_template=None):
    index = {}
    for entry in array(catalog, "tables"):
        if board_template is not None:
            exact_fields(entry, ("uasset_sha256", "uexp_sha256", "rows"))
        header = hashed(entry, "uasset_sha256")
        body = hashed(entry, "uexp_sha256")
        rows = {}
        for row in array(entry, "rows"):
            if board_template is not None:
                exact_fields(row, ("ordinal", "source_sha256"))
            ordinal = row["ordinal"]
            if type(ordinal) is not int or ordinal < 0:
                raise ValueError("Invalid native row ordinal")
            if board_template is None:
                value = replacement(row)
            else:
                value = (hashed(row, "source_sha256"), board_template)
            add_unique(rows, ordinal, value)
        if not rows:
            raise ValueError("Empty native row group")
        add_unique(index.setdefault(header, {}), body, rows)
    return index


def add_board_templates(index, catalog):
    from native_tables import BoardNameTemplate

    exact_fields(catalog, ("schema_version", "kind", "english_template", "tables"))
    if (type(catalog["schema_version"]) is not int or catalog["schema_version"] != 2
            or catalog["kind"] != "local-board-name"):
        raise ValueError("Unsupported board template catalog")
    templates = native_index(catalog, BoardNameTemplate(text_value(catalog, "english_template")))
    if not templates:
        raise ValueError("Empty board template catalog")
    for header, editions in templates.items():
        for body, rows in editions.items():
            literals = index.setdefault(header, {}).setdefault(body, {})
            if literals.keys() & rows.keys():
                raise ValueError("Native and board template catalogs bind the same row")
            literals.update(rows)
    return templates


def native_files(root):
    text_dir = root / TEXT_ROOT
    if not text_dir.is_dir() or text_dir.resolve() != text_dir:
        raise ValueError(f"The input must contain a local {TEXT_ROOT.as_posix()} directory")
    for directory, dirs, files in os.walk(text_dir):
        current = Path(directory)
        dirs[:] = sorted(name for name in dirs if not (current / name).is_symlink())
        for name in sorted(files):
            asset = current / name
            if asset.suffix.lower() == ".uasset" and not asset.is_symlink():
                yield asset


def build_native(args, catalog):
    from native_tables import rebuild_table

    root = args.input.resolve(strict=True)
    if root in args.output.resolve().parents:
        raise ValueError("Choose an output directory outside the input tree")
    index = native_index(catalog)
    template_editions = {}
    template_path = getattr(args, "board_templates", None)
    if template_path is not None:
        template_editions = add_board_templates(index, read_json(template_path))
    dialogue = None
    dialogue_path = getattr(args, "dialogue_controls", None)
    if dialogue_path is not None:
        from dialogue_controls import DialogueControls
        dialogue = DialogueControls(read_json(dialogue_path))
    matched_templates = set()
    logical_paths = []
    matched_rows = drift = 0
    with tempfile.TemporaryDirectory(dir=args.output.parent) as tmp:
        ready = Path(tmp) / "ready"
        ready.mkdir()
        for source in native_files(root):
            asset = source.read_bytes()
            header = digest(asset)
            editions = index.get(header)
            dialogue_header = dialogue is not None and header in dialogue.headers
            if editions is None and not dialogue_header:
                continue
            companion = source.with_suffix(".uexp")
            if not companion.is_file() or companion.is_symlink():
                if dialogue_header:
                    raise ValueError("Missing matching dialogue export")
                if header in template_editions:
                    raise ValueError("Missing matching board template export")
                drift += 1
                continue
            export = companion.read_bytes()
            body = digest(export)
            if header in template_editions:
                pair = (header, body)
                if body not in template_editions[header] or pair in matched_templates:
                    raise ValueError("Unrecognized or ambiguous local board template pair")
                matched_templates.add(pair)
            rows = editions.get(body) if editions is not None else None
            if dialogue_header:
                rows = dialogue.merge((header, body), asset, export, rows)
            if rows is None:
                drift += 1
                continue
            header_out, export_out = rebuild_table(asset, export, rows)
            for original, data in ((source, header_out), (companion, export_out)):
                logical_path = original.relative_to(root)
                target = ready / logical_path
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as out:
                    out.write(data)
                logical_paths.append(logical_path.as_posix())
            matched_rows += len(rows)
        if template_editions and not matched_templates:
            raise ValueError("No approved board template pair matched this input")
        if dialogue is not None:
            for member, data in dialogue.glossary_output(root).items():
                target = ready / member
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as out:
                    out.write(data)
                logical_paths.append(member.as_posix())
        if drift and args.strict:
            raise ValueError(f"{drift} known native headers lacked the matching export")
        if not logical_paths:
            raise ValueError("No supported native table pairs matched the input")
        if args.archive:
            from overlay_archive import write_overlay
            write_overlay(ready, logical_paths, ready / ARCHIVE_NAME)
        # Reserve the user's new directory exclusively before publishing its contents.
        args.output.mkdir()
        moved = []
        try:
            for child in ready.iterdir():
                dest = args.output / child.name
                child.rename(dest)
                moved.append(dest)
        except BaseException:
            for dest in reversed(moved):
                dest.rename(ready / dest.name)
            args.output.rmdir()
            raise
    print(f"Built {len(logical_paths) // 2} native pairs with {matched_rows} bound rows. "
          f"{drift} known headers with changed or missing exports skipped.")
    if args.archive:
        print(f"Wrote {args.output / ARCHIVE_NAME}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="kind", required=True)
    for name, description in (("service", "Build a translated service text JSON file"),
                              ("native", "Build translated split native text tables")):
        sub = commands.add_parser(name, help=description)
        sub.add_argument("--input", type=Path, required=True,
                         help="Owned text JSON" if name == "service" else
                              "Extracted content root containing BLUEPROTOCOL/Content/Text")
        sub.add_argument("--output", type=Path, required=True,
                         help="New file" if name == "service" else "New directory outside the input")
        sub.add_argument("--catalog", type=Path, default=CATALOGS / (name + ".json"))
        sub.add_argument("--strict", action="store_true",
                         help="Fail if a known ID or package header has a changed source")
        if name == "native":
            sub.add_argument("--dialogue-controls", type=Path, nargs="?", metavar="CATALOG",
                             const=CATALOGS / "native-dialogue-controls.json",
                             help="Include supported glossary and quotation dialogue from local game data")
            sub.add_argument("--board-templates", type=Path, nargs="?", metavar="CATALOG",
                             const=CATALOGS / "native-board-templates.json",
                             help="Apply board prompts using names from the matching local text")
            sub.add_argument("--archive", action="store_true",
                             help="Also build an uncompressed local overlay archive")
    args = parser.parse_args()
    if not args.output.parent.is_dir():
        parser.exit(1, "The output parent directory must already exist.\n")
    if os.path.lexists(args.output):
        parser.exit(1, "The output already exists. Choose a new output path.\n")
    try:
        catalog = read_json(args.catalog)
        if (not isinstance(catalog, dict) or type(catalog.get("schema_version")) is not int
                or catalog["schema_version"] != 1):
            raise ValueError("Unsupported translation catalog version")
        if args.kind == "service":
            build_service(args, catalog)
        else:
            build_native(args, catalog)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Could not build the patch: {error}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
