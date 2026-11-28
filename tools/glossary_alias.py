"""Add English word aliases to an exact, locally owned split dictionary."""

from collections.abc import Mapping
from hashlib import sha256
from struct import pack, pack_into, unpack_from
import unicodedata

from native_tables import _Export, _check, _encode, _string, _summary


_WORD_STRUCT_HASH = "cd782535c49d85e77e428e130041b65248d253e555646435244b24c9eba23b3b"


def _hash(text):
    return sha256(text.encode("utf-8")).hexdigest()


def _english(value, optional=False):
    _check(isinstance(value, str), "Expected a glossary label")
    if value == "" and optional:
        return bytes(4)
    _check(value == value.strip() and any(c.isalpha() for c in value) and all(
        (c.isalpha() and unicodedata.name(c, "").startswith("LATIN "))
        or c in " 0123456789.,:;!?-'’“”()–—…" for c in value), "Invalid English glossary label")
    return _encode(value)


def _rows(asset, export):
    size_at, names = _summary(asset, export, expected_class="DataTable")
    export_at, import_count, import_at = unpack_from("<iii", asset, 61)
    h = _Export(asset, names)
    p = _Export(export, names)
    limit = len(export) - 4
    _check(import_at + 28 * import_count == export_at and limit >= 45 and
           p.name(0, limit) == "RowStruct" and p.name(8, limit) == "ObjectProperty" and
           export[16:25] == pack("<iiB", 4, 0, 0) and p.name(29, limit) == "None" and
           export[37:41] == bytes(4), "Unsupported dictionary header")
    row_type, = unpack_from("<i", export, 25)
    _check(-import_count <= row_type < 0, "Missing dictionary row type")
    row_import = import_at + 28 * (-row_type - 1)
    _check(h.name(row_import + 8, export_at) == "ScriptStruct"
           and _hash(h.name(row_import + 20, export_at)) == _WORD_STRUCT_HASH,
           "Unsupported dictionary row structure")
    count, = unpack_from("<i", export, 41)
    _check(0 < count <= (limit - 45) // 16, "Invalid dictionary row count")
    rows = {}
    spellings = set()
    pos = 45
    for _ in range(count):
        start = pos
        name = p.name(pos, limit)
        key = _hash(name)
        index, number = unpack_from("<ii", export, pos)
        _check(key not in rows and name.casefold() not in spellings, "Ambiguous dictionary key")
        spellings.add(name.casefold())
        fields, pos = p.fields(pos + 8, limit)
        _check(tuple(fields) == ("BodyText", "RubyText"), "Unexpected glossary fields")
        values = []
        for field in fields.values():
            _check(field.kind == "StrProperty", "Unexpected glossary field type")
            text, end = _string(export, field.start, field.end)
            _check(end == field.end, "Surplus bytes in glossary field")
            values.append(text)
        rows[key] = (start, pos, index, number, tuple(fields.values()), tuple(values))
    _check(pos == limit, "Invalid dictionary trailer")
    return size_at, names, rows, spellings


def append_glossary_aliases(asset, export, expected_pair, aliases):
    """Append numbered rows; original keys, labels and readings keep their bytes.

    Map each original key's UTF-8 SHA-256 to (body hash, reading hash, English
    body, English reading, number). The number is the serialized name number.
    A caller refers to it by appending an underscore and number minus one to
    the original key read from the player's local files.
    """
    _check(isinstance(asset, bytes) and isinstance(export, bytes) and
           isinstance(expected_pair, (tuple, list)) and tuple(expected_pair) ==
           (sha256(asset).hexdigest(), sha256(export).hexdigest()), "Source glossary pair differs")
    size_at, names, rows, taken = _rows(asset, export)
    _check(isinstance(aliases, Mapping) and aliases and aliases.keys() <= rows.keys(),
           "Unknown or empty dictionary alias selection")
    taken.update(name.casefold() for name in names)
    appended = bytearray()
    expected = {}
    for key, (start, end, index, old_number, fields, values) in rows.items():
        if key not in aliases:
            continue
        edit = aliases[key]
        _check(isinstance(edit, (tuple, list)) and len(edit) == 5, "Invalid dictionary alias")
        body_hash, ruby_hash, body, ruby, number = edit
        _check(old_number == 0 and (_hash(values[0]), _hash(values[1])) == (body_hash, ruby_hash),
               "Original dictionary label or reading differs")
        _check(type(number) is int and 1 <= number <= 0x7fffffff, "Invalid dictionary alias number")
        alias = names[index] + "_" + str(number - 1)
        _check(alias.casefold() not in taken, "Dictionary alias already exists")
        taken.add(alias.casefold())
        expected[_hash(alias)] = (index, number, (body, ruby))
        appended.extend(pack("<ii", index, number))
        cursor = start + 8
        for field, replacement in zip(fields, (_english(body), _english(ruby, optional=True))):
            appended.extend(export[cursor:field.size_at])
            appended.extend(pack("<i", len(replacement)))
            appended.extend(export[field.size_at + 4:field.start])
            appended.extend(replacement)
            cursor = field.end
        appended.extend(export[cursor:end])
    count = len(rows) + len(expected)
    _check(count <= 0x7fffffff, "Too many dictionary rows")
    output = export[:41] + pack("<i", count) + export[45:-4] + appended + export[-4:]
    header = bytearray(asset)
    pack_into("<q", header, size_at, len(output) - 4)
    pack_into("<q", header, 169, len(header) + len(output) - 4)
    result = bytes(header), bytes(output)
    _, result_names, verified, _ = _rows(*result)
    _check(result_names == names and list(verified) == [*rows, *expected]
           and output[45:len(export)-4] == export[45:-4], "Original glossary rows changed")
    for key, (index, number, values) in expected.items():
        _, _, got_index, got_number, _, got_values = verified[key]
        _check((got_index, got_number, got_values) == (index, number, values),
               "Appended glossary row differs")
    return result
