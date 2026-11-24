"""Rebuild one split cooked Blue Protocol text table using verified row ordinals."""

from dataclasses import dataclass
from hashlib import sha256
from struct import pack, pack_into, unpack_from


PACKAGE_TAG = pack("<I", 0x9E2A83C1)


def _check(condition, reason):
    if not condition:
        raise ValueError(reason)


def _string(data, offset, limit):
    _check(offset + 4 <= limit, "Truncated string length")
    units, = unpack_from("<i", data, offset)
    start = offset + 4
    if not units:
        return "", start
    end = start + (units if units > 0 else -2 * units)
    _check(end <= limit, "String extends past its containing field")
    value = data[start:end].decode("utf-8" if units > 0 else "utf-16-le")
    _check(value.endswith("\0") and "\0" not in value[:-1], "Invalid string terminator")
    return value[:-1], end


def _encode(text):
    _check(isinstance(text, str) and "\0" not in text, "Invalid replacement string")
    if text.isascii():
        data = (text + "\0").encode("ascii")
        return pack("<i", len(data)) + data
    data = (text + "\0").encode("utf-16-le")
    return pack("<i", -(len(data) // 2)) + data


def _summary(asset, export):
    # The accepted cooked layout has an unversioned summary, one export and
    # its external payload immediately following the header in virtual space.
    _check(len(asset) >= 193 and asset[:4] == PACKAGE_TAG, "Unknown package header")
    _check(unpack_from("<5i", asset, 4) == (-7, 0, 0, 0, 0), "Unsupported package version")
    folder, flags_offset = _string(asset, 28, len(asset))
    _check((folder, flags_offset) == ("None", 37) and
           unpack_from("<I", asset, flags_offset)[0] == 0x80000000, "Unsupported package flags")
    name_count, names_start = unpack_from("<ii", asset, 41)
    export_count, export_start, import_count, import_start = unpack_from("<4i", asset, 57)
    _check(unpack_from("<i", asset, 24)[0] == len(asset) and names_start == 193 and
           names_start < import_start < export_start and export_start + 44 <= len(asset) and
           export_count == 1 and import_count > 0, "Unsupported split-package layout")
    _check(0 < name_count <= (import_start - names_start) // 8, "Invalid name count")
    serial_size, serial_offset = unpack_from("<qq", asset, export_start + 28)
    bulk_offset, = unpack_from("<q", asset, 169)
    _check(len(export) >= 16 and export[-4:] == PACKAGE_TAG and
           serial_size == len(export) - 4 and serial_offset == len(asset) and
           bulk_offset == serial_offset + serial_size, "Split-package sizes do not match")
    names = []
    cursor = names_start
    for _ in range(name_count):
        value, end = _string(asset, cursor, import_start)
        names.append(value)
        cursor = end + 4  # Two cooked name hashes, retained in the original name map.
    _check(cursor == import_start and "SBTextTableAsset" in names, "Unsupported name map")
    return export_start + 28, names


@dataclass(frozen=True)
class _Property:
    kind: str
    inner: str
    size_at: int
    start: int
    end: int


class _Export:
    def __init__(self, export, names):
        self.data = export
        self.names = names

    def name(self, offset, limit):
        _check(offset + 8 <= limit, "Truncated name reference")
        index, suffix = unpack_from("<ii", self.data, offset)
        _check(0 <= index < len(self.names) and suffix >= 0, "Invalid name reference")
        name = self.names[index]
        return f"{name}_{suffix - 1}" if suffix else name

    def property(self, offset, limit):
        name = self.name(offset, limit)
        kind = self.name(offset + 8, limit)
        _check(offset + 24 <= limit, "Truncated property header")
        size, index = unpack_from("<ii", self.data, offset + 16)
        _check(size >= 0 and index == 0, "Invalid property size or array index")
        cursor = offset + 24
        inner = ""
        if kind in ("StructProperty", "ArrayProperty", "MapProperty"):
            inner = self.name(cursor, limit)
            if kind == "MapProperty":
                self.name(cursor + 8, limit)
            cursor += {"StructProperty": 24, "ArrayProperty": 8, "MapProperty": 16}[kind]
        else:
            _check(kind in ("StrProperty", "NameProperty", "IntProperty"), "Unsupported property type")
        _check(cursor < limit and self.data[cursor] == 0, "Unsupported property GUID")
        start = cursor + 1
        _check(start + size <= limit, "Property extends past its container")
        return name, _Property(kind, inner, offset + 16, start, start + size)

    def fields(self, cursor, limit):
        fields = {}
        while self.name(cursor, limit) != "None":
            name, field = self.property(cursor, limit)
            _check(name not in fields, "Duplicate row property")
            fields[name] = field
            cursor = field.end
        return fields, cursor + 8

    def rows(self):
        limit = len(self.data) - 8
        _check(self.data[limit:limit + 4] == bytes(4), "Unsupported object trailer")
        if self.name(0, limit) == "None" and limit == 8:
            return [], ()
        name, array = self.property(0, limit)
        _check((name, array.kind, array.inner) == ("TextTable", "ArrayProperty", "StructProperty")
               and array.end + 8 == limit and self.name(array.end, limit) == "None",
               "Unsupported text array")
        _check(array.start + 4 <= array.end, "Missing array count")
        count, = unpack_from("<i", self.data, array.start)
        name, elements = self.property(array.start + 4, array.end)
        _check((name, elements.kind, elements.inner) == ("TextTable", "StructProperty", "SBTextData")
               and elements.end == array.end and 0 <= count <= (elements.end - elements.start) // 8,
               "Invalid text array elements")
        cursor = elements.start
        rows = []
        for _ in range(count):
            fields, cursor = self.fields(cursor, elements.end)
            ident, text = fields.get("Id"), fields.get("Text")
            _check(ident and (ident.kind, ident.inner) == ("StructProperty", "SBTextId")
                   and text and text.kind == "StrProperty", "Unexpected text row layout")
            id_fields, end = self.fields(ident.start, ident.end)
            row_name = id_fields.get("IdString")
            _check(end == ident.end and row_name and row_name.kind == "NameProperty"
                   and row_name.end - row_name.start == 8, "Unexpected row ID layout")
            row_id = self.name(row_name.start, row_name.end)
            value, end = _string(self.data, text.start, text.end)
            _check(end == text.end, "Surplus bytes in row text")
            rows.append((row_id, text, value))
        _check(cursor == elements.end, "Table row count disagrees with its length")
        return rows, (array.size_at, elements.size_at)


def rebuild_table(asset: bytes, export: bytes, replacements: dict[int, tuple[str, str]]) -> tuple[bytes, bytes]:
    """Patch {ordinal: (original UTF-8 SHA-256, English)} into an owned table pair.

    The caller identifies the exact original pair by file hashes. Ordinals are
    zero-based and count every row, including repeated IDs. Both returned byte
    streams are parsed again before delivery. A mismatch raises ValueError.
    """
    serial_size_at, names = _summary(asset, export)
    rows, array_sizes = _Export(export, names).rows()
    _check(all(type(i) is int and 0 <= i < len(rows) for i in replacements), "Unknown row ordinal")
    result = bytearray()
    cursor = 0
    expected = []
    for ordinal, (row_id, field, original) in enumerate(rows):
        value = original
        if ordinal in replacements:
            source_hash, value = replacements[ordinal]
            _check(sha256(original.encode("utf-8")).hexdigest() == source_hash,
                   f"Source text hash mismatch at row {ordinal}")
            if value != original:
                payload = _encode(value)
                result.extend(export[cursor:field.size_at])
                result.extend(pack("<i", len(payload)))
                result.extend(export[field.size_at + 4:field.start])
                result.extend(payload)
                cursor = field.end
        expected.append((row_id, value))
    result.extend(export[cursor:])
    delta = len(result) - len(export)
    for offset in array_sizes:
        size, = unpack_from("<i", export, offset)
        _check(size + delta < 2**31, "Rebuilt table exceeds the property size limit")
        pack_into("<i", result, offset, size + delta)
    header = bytearray(asset)
    pack_into("<q", header, serial_size_at, len(result) - 4)
    pack_into("<q", header, 169, len(header) + len(result) - 4)
    output = bytes(header), bytes(result)
    _, names = _summary(*output)
    verified, _ = _Export(output[1], names).rows()
    _check([(row_id, value) for row_id, _, value in verified] == expected, "Rebuilt table readback failed")
    return output
