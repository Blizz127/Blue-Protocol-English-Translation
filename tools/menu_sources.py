"""Recover catalog identities from a player's effective loose cooked menu packages."""

import hashlib
import json
import os
from pathlib import Path
import struct


# Each directory is relative to the Content directory of a merged, loose tree.
MENU_DIRS = (("Blueprints", "UI"), ("Blueprints", "Player"), ("LevelDesign", "Widget"))
PACKAGE_TAG = bytes.fromhex("c1832a9e")


def _string(blob, pos, limit):
    if pos + 4 > limit:
        raise ValueError("Incomplete string length")
    units, = struct.unpack_from("<i", blob, pos)
    pos += 4
    if units == 0:
        return "", pos
    end = pos + (units if units > 0 else -2 * units)
    if end > limit:
        raise ValueError("String exceeds its container")
    value = blob[pos:end].decode("utf-8" if units > 0 else "utf-16-le")
    if not value.endswith("\0") or "\0" in value[:-1]:
        raise ValueError("Invalid string terminator")
    return value[:-1], end


def _literal(blob, pos, end):
    if pos >= end or blob[pos] not in (0x1F, 0x34):
        raise ValueError("Expected a Kismet string literal")
    wide = blob[pos] == 0x34
    start = pos + 1
    terminator = b"\0\0" if wide else b"\0"
    stop = blob.find(terminator, start, end)
    while wide and stop != -1 and (stop - start) % 2:
        stop = blob.find(terminator, stop + 1, end)
    if stop == -1:
        raise ValueError("Unterminated Kismet string")
    return blob[start:stop].decode("utf-16-le" if wide else "utf-8"), stop + len(terminator)


def _package(header):
    # This unversioned split layout uses a 28-byte import and a 104-byte export.
    if (len(header) < 193 or header[:4] != PACKAGE_TAG or
            struct.unpack_from("<5i", header, 4) != (-7, 0, 0, 0, 0)):
        return None
    name_count, name_start = struct.unpack_from("<2i", header, 41)
    count, exports, import_count, imports, depends = struct.unpack_from("<5i", header, 57)
    if name_start != 193:
        return None
    if (struct.unpack_from("<i", header, 24)[0] != len(header) or
            not name_start <= imports <= exports <= depends <= len(header) or
            import_count * 28 != exports - imports or count * 104 != depends - exports or
            not 0 < name_count <= (imports - name_start) // 8):
        raise ValueError("Invalid cooked package offsets")
    names = []
    pos = name_start
    for _ in range(name_count):
        name, pos = _string(header, pos, imports)
        names.append(name)
        pos += 4
    if pos != imports:
        raise ValueError("Invalid cooked name map")
    spans = []
    for i in range(count):
        record = exports + 104 * i
        class_ref, = struct.unpack_from("<i", header, record)
        size, offset = struct.unpack_from("<qq", header, record + 28)
        is_function = False
        if class_ref < 0:
            if -class_ref > import_count:
                raise ValueError("Invalid export class reference")
            index, suffix = struct.unpack_from("<ii", header, imports + (-class_ref - 1) * 28 + 20)
            if not 0 <= index < len(names) or suffix < 0:
                raise ValueError("Invalid class name")
            is_function = names[index] == "Function" and suffix == 0
        start = offset - len(header)
        if size:
            spans.append((start, start + size, is_function))
        if size < 0:
            raise ValueError("Negative export size")
    return names, spans


def _base_text(data, pos, limit):
    if pos + 5 > limit:
        raise ValueError("Incomplete text history")
    flags, history = struct.unpack_from("<IB", data, pos)
    # Ordinary or immutable Base history. Culture-invariant text has no
    # runtime localization identity.
    if history != 0 or flags not in (0, 8):
        raise ValueError("Unsupported text history")
    namespace, pos = _string(data, pos + 5, limit)
    key, pos = _string(data, pos, limit)
    original, pos = _string(data, pos, limit)
    return (namespace, key, original), pos


def _property_texts(data, start, end, type_name, name_count):
    cursor = start
    while (pos := data.find(type_name, cursor, end)) != -1:
        cursor = pos + len(type_name)
        if pos - 8 < start or pos + 22 > end:
            continue
        name, suffix = struct.unpack_from("<ii", data, pos - 8)
        size, index, guid = struct.unpack_from("<iiB", data, pos + 8)
        limit = pos + 17 + size
        if not 0 <= name < name_count or suffix < 0 or guid or index or size < 5 or limit > end:
            continue
        try:
            record, p = _base_text(data, pos + 17, limit)
        except ValueError:
            continue
        if p == limit and record[1]:
            yield record


def _display_names(data, start, end, tag, types, name_count):
    cursor = start
    while (pos := data.find(tag, cursor, end)) != -1:
        cursor = pos + len(tag)
        if pos + 49 > end or data[pos + 24:pos + 41] != types:
            continue
        size, index = struct.unpack_from("<ii", data, pos + 16)
        limit = pos + 41 + size
        if index or size < 8 or limit > end:
            continue
        removed, = struct.unpack_from("<i", data, pos + 41)
        p = pos + 45 + 8 * removed
        if removed < 0 or p + 4 > limit:
            continue
        count, = struct.unpack_from("<i", data, p)
        p += 4
        if not 0 <= count <= (limit - p) // 25:
            continue
        entries = []
        for _ in range(count):
            if p + 8 > limit:
                break
            name, suffix = struct.unpack_from("<ii", data, p)
            if not 0 <= name < name_count or suffix < 0:
                break
            try:
                record, p = _base_text(data, p + 8, limit)
            except ValueError:
                break
            if record[1]:
                entries.append(record)
        else:
            if p == limit:
                yield from entries


def _function_texts(data, start, end):
    cursor = start
    # EX_TextConst, LocalizedText followed by source, key and namespace literals.
    while (pos := data.find(b"\x29\x01", cursor, end)) != -1:
        cursor = pos + 2
        try:
            source, p = _literal(data, cursor, end)
            key, p = _literal(data, p, end)
            namespace, p = _literal(data, p, end)
        except ValueError:
            continue
        if key:
            yield namespace, key, source
            cursor = p


def _records(header, companion):
    package = _package(header)
    if package is None:
        return
    names, spans = package
    type_name = struct.pack("<ii", names.index("TextProperty"), 0) if "TextProperty" in names else None
    map_tag = None
    if type_name and all(n in names for n in ("DisplayNameMap", "MapProperty", "NameProperty")):
        map_tag = struct.pack("<4i", names.index("DisplayNameMap"), 0, names.index("MapProperty"), 0)
        map_types = struct.pack("<ii", names.index("NameProperty"), 0) + type_name + b"\0"
    if not type_name and not any(is_function for _, _, is_function in spans):
        return
    raw = companion.read_bytes()
    if raw[-4:] != PACKAGE_TAG:
        raise ValueError("Missing split-package trailer")
    last_end = 0
    for start, end, is_function in sorted(spans):
        if not last_end <= start <= end <= len(raw) - 4:
            raise ValueError("Invalid split export range")
        last_end = end
        if type_name:
            yield from _property_texts(raw, start, end, type_name, len(names))
        if map_tag:
            yield from _display_names(raw, start, end, map_tag, map_types, len(names))
        if is_function:
            yield from _function_texts(raw, start, end)


def _pairs(root):
    if root.is_symlink():
        raise ValueError("The loose source root must be a normal directory")
    for scope in MENU_DIRS:
        directory = root
        for name in ("BLUEPROTOCOL", "Content", *scope):
            directory = directory / name
            if directory.is_symlink() or not directory.is_dir():
                break
        else:
            for current, dirs, files in os.walk(directory):
                base = Path(current)
                dirs[:] = sorted(name for name in dirs if not (base / name).is_symlink())
                for filename in sorted(files):
                    asset = base / filename
                    if asset.suffix.lower() != ".uasset" or asset.is_symlink() or not asset.is_file():
                        continue
                    companion = asset.with_suffix(".uexp")
                    if companion.is_file() and not companion.is_symlink():
                        yield asset, companion


def find_menu_sources(root: Path, wanted: set[str]) -> dict[str, tuple[str, str, str]]:
    """Return exact matches as {catalog digest: (namespace, runtime key, source)}.

    root contains BLUEPROTOCOL/Content from the player's effective loose tree.
    Missing, unsupported or nonmatching identities are omitted. A requested
    identity with conflicting originals raises ValueError. The input is read-only.
    """
    found = {}
    originals = {}
    conflicts = set()
    for header, export in _pairs(root):
        try:
            for namespace, key, source in _records(header.read_bytes(), export):
                identity = (namespace, key)
                source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
                if originals.setdefault(identity, source_hash) != source_hash:
                    conflicts.add(identity)
                fields = json.dumps([namespace, key, source_hash], ensure_ascii=False, separators=(",", ":"))
                digest = hashlib.sha256(fields.encode("utf-8")).hexdigest()
                if digest in wanted:
                    found[digest] = (namespace, key, source)
        except ValueError as error:
            raise ValueError(f"{header.name}: {error}") from error
    if any((namespace, key) in conflicts for namespace, key, _ in found.values()):
        raise ValueError("Conflicting source text for a requested runtime localization key")
    return found
