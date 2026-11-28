"""Build and verify a plain Unreal Engine 4 version 8 localization overlay locally."""

import hashlib
import os
import re
import stat
import struct
from pathlib import Path


_LOCALIZED_MEMBER = re.compile(
    r"BLUEPROTOCOL/Content/(?:(?:Text|Script)/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.(?:uasset|uexp)"
    r"|UI/Startup/UI_StartupCaution1\.(?:uasset|uexp)"
    r"|UI/Option/HUD/UI_OptionMenuHud(?:Left|Right)\.(?:uasset|uexp)"
    r"|UI/Image/TutorialHelp/(?:LiquidMemory_guide_0[6-9]|UI_TutorialHelp0006[2356])\.(?:uasset|uexp)"
    r"|Localization/Game/ja/Game\.locres)"
)
_INT = struct.Struct("<i")
_ENTRY = struct.Struct("<qqqI20sBI")
_FOOTER = struct.Struct("<17xIiqq20s160x")
_CHUNK = 1024 * 1024


def _string(value):
    encoded = value.encode("ascii") + b"\0"
    return _INT.pack(len(encoded)) + encoded


def _record(offset, size, digest):
    # Both length fields describe the same bytes for an uncompressed member.
    return _ENTRY.pack(offset, size, size, 0, digest, 0, 0)


def _inputs(root, names):
    if not names:
        raise ValueError("An overlay needs at least one localized file")
    resolved = {}
    seen = set()
    for name in sorted(names):
        if not _LOCALIZED_MEMBER.fullmatch(name) or name.casefold() in seen:
            raise ValueError(f"Invalid or duplicate localization member {name!r}")
        seen.add(name.casefold())
        source = (root / name).resolve(strict=True)
        if root not in source.parents or not source.is_file():
            raise ValueError(f"Expected {name} in the local input directory")
        resolved[name] = source
    return resolved


def _build(stream, sources):
    index = bytearray(_string("../../../") + _INT.pack(len(sources)))
    entries = []
    for name, source in sources.items():
        start = stream.tell()
        stream.write(bytes(_ENTRY.size))
        digest = hashlib.sha1()
        with source.open("rb") as member:
            while chunk := member.read(_CHUNK):
                digest.update(chunk)
                stream.write(chunk)
        end = stream.tell()
        size = end - start - _ENTRY.size
        checksum = digest.digest()
        stream.seek(start)
        stream.write(_record(0, size, checksum))
        stream.seek(end)
        index.extend(_string(name) + _record(start, size, checksum))
        entries.append((name, size, checksum))
    footer = _FOOTER.pack(0x5A6F12E1, 8, stream.tell(), len(index), hashlib.sha1(index).digest())
    stream.write(index)
    stream.write(footer)
    stream.flush()
    return entries, index, footer


def _verify(stream, entries, index, footer):
    stream.seek(0)
    for name, size, checksum in entries:
        if stream.read(_ENTRY.size) != _record(0, size, checksum):
            raise ValueError(f"Overlay header readback failed for {name}")
        digest = hashlib.sha1()
        remaining = size
        while remaining:
            chunk = stream.read(min(remaining, _CHUNK))
            if not chunk:
                raise ValueError(f"Overlay ended inside {name}")
            digest.update(chunk)
            remaining -= len(chunk)
        if digest.digest() != checksum:
            raise ValueError(f"Overlay payload readback failed for {name}")
    if stream.read(len(index)) != index or stream.read(len(footer) + 1) != footer:
        raise ValueError("Overlay index or footer readback failed")


def write_overlay(source_root: Path, logical_paths: list[str], output: Path) -> None:
    """Write to a new file or an empty temporary file supplied by the caller."""
    sources = _inputs(Path(source_root).resolve(strict=True), logical_paths)
    output = Path(output)
    try:
        stream = output.open("x+b")
    except FileExistsError:
        info = output.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size or info.st_nlink != 1:
            raise ValueError("Choose a new overlay file or an empty temporary file")
        if output.resolve() in sources.values():
            raise ValueError("Overlay output would replace a source file")
        stream = output.open("r+b")
        opened = os.fstat(stream.fileno())
        if not os.path.samestat(info, opened) or opened.st_size:
            stream.close()
            raise ValueError("Overlay output changed while opening")
    with stream:
        try:
            entries, index, footer = _build(stream, sources)
            _verify(stream, entries, index, footer)
        except BaseException:
            stream.seek(0)
            stream.truncate()
            raise
