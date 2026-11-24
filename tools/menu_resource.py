"""Merge source-checked menu translations into a local UE localization resource."""

import struct
import zlib
from collections import Counter


RESOURCE_MEMBER = "BLUEPROTOCOL/Content/Localization/Game/ja/Game.locres"
_HEADER = struct.Struct("<16sBqII")
_GUID = bytes.fromhex("0e147475674a03fc4a15909dc3377f1b")


class _Reader:
    def __init__(self, data, start, end):
        self.data = data
        self.position = start
        self.end = end

    def take(self, size):
        start = self.position
        if size > self.end - start:
            raise ValueError("Truncated menu localization field")
        self.position += size
        return self.data[start:self.position]

    def number(self):
        return int.from_bytes(self.take(4), "little")

    def string(self):
        length, = struct.unpack("<i", self.take(4))
        if not length:
            return ""
        if length < 0:
            value = self.take(-2 * length).decode("utf-16-le")
        else:
            value = self.take(length).decode("utf-8")
        if not value.endswith("\0") or "\0" in value[:-1]:
            raise ValueError("Malformed menu string terminator")
        return value[:-1]


def _decode(data):
    if len(data) < _HEADER.size:
        raise ValueError("Truncated menu localization header")
    magic, version, pool_offset, row_count, namespace_count = _HEADER.unpack_from(data)
    if magic != _GUID or version != 3:
        raise ValueError("Expected a version 3 menu localization resource")
    if not _HEADER.size <= pool_offset <= len(data) - 4:
        raise ValueError("Invalid menu string table offset")

    pool = _Reader(data, pool_offset, len(data))
    strings = []
    references = []
    for _ in range(pool.number()):
        strings.append(pool.string())
        references.append(pool.number())
    if pool.position != pool.end:
        raise ValueError("Unexpected data after menu string table")

    directory = _Reader(data, _HEADER.size, pool_offset)
    rows = {}
    namespaces = set()
    for _ in range(namespace_count):
        namespace_hash = directory.number()
        namespace = directory.string()
        if namespace in namespaces:
            raise ValueError("Duplicate menu namespace")
        namespaces.add(namespace)
        for _ in range(directory.number()):
            key_hash = directory.number()
            identity = (namespace, directory.string())
            source_hash = directory.number()
            index = directory.number()
            if identity in rows or index >= len(strings):
                raise ValueError("Invalid or duplicate menu entry")
            references[index] -= 1
            rows[identity] = (namespace_hash, key_hash, source_hash, strings[index])
    if directory.position != directory.end or len(rows) != row_count or any(references):
        raise ValueError("Menu directory, entry count or string references disagree")
    return rows


def _encode_string(value):
    if value.isascii():
        data = value.encode("ascii") + b"\0"
        return struct.pack("<i", len(data)) + data
    data = (value + "\0").encode("utf-16-le")
    return struct.pack("<i", -(len(data) // 2)) + data


def _encode(rows):
    grouped = {}
    indices = {}
    refs = Counter()
    for (namespace, key), (namespace_hash, key_hash, source_hash, text) in rows.items():
        index = indices.setdefault(text, len(indices))
        refs[text] += 1
        group_hash, members = grouped.setdefault(namespace, (namespace_hash, []))
        if group_hash != namespace_hash:
            raise ValueError("Menu entries disagree on the namespace hash")
        members.append((key, key_hash, source_hash, index))

    directory = bytearray()
    for namespace, (namespace_hash, members) in grouped.items():
        directory.extend(struct.pack("<I", namespace_hash) + _encode_string(namespace))
        directory.extend(struct.pack("<I", len(members)))
        for key, key_hash, source_hash, index in members:
            directory.extend(struct.pack("<I", key_hash) + _encode_string(key))
            directory.extend(struct.pack("<II", source_hash, index))
    output = bytearray(_HEADER.pack(_GUID, 3, _HEADER.size + len(directory), len(rows), len(grouped)))
    output.extend(directory)
    output.extend(struct.pack("<I", len(indices)))
    for text in indices:
        output.extend(_encode_string(text) + struct.pack("<I", refs[text]))
    return bytes(output)


def _source_hash(source):
    # The engine feeds four bytes per UTF-16 code unit into the CRC.
    units = source.encode("utf-16-le")
    padded = bytearray(2 * len(units))
    padded[0::4] = units[0::2]
    padded[1::4] = units[1::2]
    return zlib.crc32(padded)


def apply_menu_resource(original, updates):
    """Merge (namespace, key, local source, English, namespace hash, key hash) rows."""
    rows = _decode(original)
    replacements = {}
    for namespace, key, source, english, namespace_hash, key_hash in updates:
        if any(not isinstance(value, str) or "\0" in value for value in (namespace, key, source, english)):
            raise ValueError("Invalid menu text")
        if not key or not source or not english.strip():
            raise ValueError("Missing menu key, source or English text")
        if any(type(n) is not int or not 0 <= n <= 0xffffffff for n in (namespace_hash, key_hash)):
            raise ValueError("Expected unsigned 32-bit menu hashes")
        if not namespace and namespace_hash:
            raise ValueError("The empty menu namespace must have a zero hash")
        identity = (namespace, key)
        if identity in replacements:
            raise ValueError("Duplicate menu update")
        hashes = (namespace_hash, key_hash, _source_hash(source))
        if identity in rows and rows[identity][:3] != hashes:
            raise ValueError("Existing menu source or lookup hash differs from the update")
        replacements[identity] = (*hashes, english)
    if all(rows.get(identity) == row for identity, row in replacements.items()):
        return original
    for identity in sorted(replacements):
        rows[identity] = replacements[identity]
    result = _encode(rows)
    if _decode(result) != rows:
        raise ValueError("Menu localization resource failed readback")
    return result
