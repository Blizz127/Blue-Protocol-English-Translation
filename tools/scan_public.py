#!/usr/bin/env python3
"""Scan a proposed public Git commit, its trees and every reachable ancestor."""
import argparse
import ast
import hashlib
import ipaddress
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tokenize
import unicodedata
from urllib.parse import urlsplit


DOCS = {"README.md", "LICENSE", "STYLE.md", ".gitignore"}
HUD_TOOLS = {"tools/build_hud.py", "tools/hud_lettering.py"}
HUD_FPS_KEYS = {
    "8ffe8133b6aad633360606950a7188207e827cedbfd8d69483d319d5743c4c2f",
    "70e63a4f698584f24d3daca662bbc0178ca6a3cacf1f16a64bf5e1601a48f401",
}
HELP_TOOLS = {"tools/build_help.py", "tools/help_lettering.py"}
ROUTE_CODEC = "tools/route_help_texture.py"
ROUTE_TOOLS = HELP_TOOLS | {ROUTE_CODEC}
ROUTE_LABEL = ("53b65c6c5b6aa107d5679bfef9b1f64f65115e6d67c81bc1532495233da44878",
               "This tab lists your active and completed quests.")
HELP_LABELS = {
    ("13b5d75d219377e0f64cef4f7fb20effb10e20e92385aa1df313596b577a6c6a", "Increased GC from Mission Rewards"),
    ("38defdcc1d74a1027bd628d5ef59ba3c414795f0ed661b03ce05a68203578f6d", "Weapon Crafting Luno Discount"),
    ("d6518c6cf80fe9a9e00b587b42699779aada92c57f7d880bc0aaae22a11a88f2", "Increased Team EXP"),
    ("ee01c55844b04347d5b2d08c613d935b9da07535260ebce1910078c5168945c1", "Increased EXP from Enemies"),
    ("ac427cebc99d00935c9703de702868230a5d31003c828449e093136b074cbf42", "Increased Gathering Yield"),
    ("8c67e7a0607f7cd8e89df9141fec68307ddc0381b1c4fb793236c6472688892f", "Reduced Gathering Time"),
    ("92165bc5efc48eeac795009f2d155764cd058510652533d2c24b315c33e2167e", "Increased Item Sale Value"),
    ("a8b16d7f433a68bbcff8abac8af76fff6782642ff9f1ef6f9312019c15ec0063", "Increased Enemy Drop Rate"),
}
TOOLS = HUD_TOOLS | ROUTE_TOOLS | {
    "tools/build_patch.py", "tools/native_tables.py", "tools/overlay_archive.py", "tools/scan_public.py",
    "tools/build_menu.py", "tools/menu_sources.py", "tools/menu_resource.py", "tools/build_script.py",
    "tools/build_notice.py", "tools/notice_lettering.py", "tools/notice_texture.py",
}
SERVICE = "translations/service.json"
NATIVE = "translations/native.json"
BOARD_TEMPLATES = "translations/native-board-templates.json"
BOARD_CATALOG_SHA256 = "b6114645fd6272eea3c29d8dfee9d2cc069f9925a498b601a2419dec4b3f52c3"
BOARD_POSITIONS_SHA256 = "82bfa767aff27c9cd9e902841a1033325e3e7e863774fdeed432a04eb8a8688f"
MENU = "translations/menu-inline.json"
MENU_RUNTIME = "translations/menu-runtime.json"
SCRIPT = "translations/script.json"
SCRIPT_SOURCES = "translations/script-sources.json"
IMAGE_LABELS = "translations/image-labels.json"
INDEXED = {MENU, IMAGE_LABELS, SCRIPT}
FILES = DOCS | TOOLS | INDEXED | {SERVICE, NATIVE, BOARD_TEMPLATES, MENU_RUNTIME, SCRIPT_SOURCES}
HEX = re.compile(r"[0-9a-f]{64}\Z")
OBJECT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
TABLE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")
STRING_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:\-]*\Z")
SOURCE_SCRIPT = re.compile(r"[\u1100-\u11ff\u3040-\u30ff\u3131-\u318e\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7a3\uf900-\ufaff\uff66-\uff9f]")
LOCATIONS = re.compile(r"(?i)(?:/(?:home|users|root|srv|mnt|private/var)/[\w.@-]+|\b[a-z]:[\\/]+users[\\/]+[^\s\\/]+|(?:^|[\s/])~/(?:\.ssh|\.config|\.local)/|\\\\[\w.-]+\\[\w.$-]+)")
DOMAINS = re.compile(r"(?i)\b[\w.-]+\.(?:lan|internal|localhost|localdomain|local|ts\.net)\b")
ADDRESS = re.compile(r"(?<![\w.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![\w.])")
IPV6 = re.compile(r"(?<![\w:])(?:[0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}(?![\w:])")
URL = re.compile(r"(?i)\b(?:https?|ssh|git|s3|r2|ftp|file)://[^\s<>\"'`\\)\]]+")
PUBLIC_HOSTS = {"github.com", "spdx.org", "opensource.org"}
SECRET = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|"
    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\b(?:gh[pousr]_|github_pat_|glpat-|xox[baprs]-|sk-live-|sk_live_|sk-proj-|AIza)[a-zA-Z0-9_-]{12,}|"
    r"\beyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]{6,}|"
    r"\b(?:ssh-rsa|ssh-ed25519|ecdsa-sha2-[\w-]+)\s+[A-Za-z0-9+/]{24,}|"
    r"(?i:\b(?:password|passwd|api[ _-]?key|access[ _-]?key(?:[ _-]?id)?|(?:auth|refresh|access|bearer)[ _-]?token|client[ _-]?secret|secret[ _-]?key|private[ _-]?key)"
    r"\s*[\"']?\s*[:=]\s*[\"']?[a-z0-9+/._=\-]{8,}|\b(?:bearer|basic)\s+[a-z0-9+/._=\-]{16,}|"
    r"[?&](?:access_token|signature|x-amz-signature|x-goog-signature|sig)=[^&\s]{8,})"
)
OPAQUE = re.compile(r"(?<![a-zA-Z0-9+/=_-])[a-zA-Z0-9+/_-]{64,}={0,2}(?![a-zA-Z0-9+/=_-])")
HEX_BYTES = re.compile(r"(?:\\x[0-9a-fA-F]{2}){12,}")
DATA_URI = re.compile(r"(?i)\bdata:[\w.+/-]+(?:;[^,\s]+)?,")
HIDDEN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u206f\ud800-\udfff\ufeff]")
MAX_BYTES = 100 * 1024 * 1024


class ScanError(ValueError):
    pass


def require(condition, context, reason):
    if not condition:
        raise ScanError(f"{context}: {reason}")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def parse_json(raw):
    def build(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ScanError("duplicate JSON field")
            obj[key] = value
        return obj

    def invalid_constant(_):
        raise ScanError("invalid JSON number")

    return json.loads(raw, object_pairs_hook=build, parse_constant=invalid_constant)


def git(repo, *args):
    # The commit is addressed in this repository, even when invoked from a hook.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_NO_REPLACE_OBJECTS="1", GIT_TERMINAL_PROMPT="0", GIT_NO_LAZY_FETCH="1", LC_ALL="C")
    cmd = ["git", "--no-replace-objects", "-C", str(repo), *args]
    result = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise ScanError(f"Git could not read the requested object or repository ({args[0]})")
    return result.stdout


def exact(obj, keys, context):
    require(isinstance(obj, dict) and obj.keys() == set(keys), context, "unexpected record fields")


def load_policy(raw):
    obj = parse_json(raw)
    require(isinstance(obj, dict), "policy", "expected a JSON object")
    required = {"schema_version", "approved_files", "forbidden_literals"}
    optional = {"forbidden_sha256", "allowed_url_hosts"}
    require(required <= obj.keys() <= required | optional, "policy", "unexpected fields")
    require(type(obj["schema_version"]) is int and obj["schema_version"] == 1, "policy", "unsupported schema")
    approved = obj["approved_files"]
    require(isinstance(approved, dict) and approved, "policy", "empty approval set")
    for name, pins in approved.items():
        require(name in FILES, "policy", "approval outside the public file allowlist")
        require(isinstance(pins, list) and pins and all(isinstance(s, str) and HEX.fullmatch(s) for s in pins), "policy", "invalid file approval")
    for key in ("forbidden_literals", "forbidden_sha256", "allowed_url_hosts"):
        values = obj.get(key, [])
        require(isinstance(values, list) and all(isinstance(s, str) and s.strip() for s in values), "policy", "invalid list")
    require(all(HEX.fullmatch(s) for s in obj.get("forbidden_sha256", [])), "policy", "invalid forbidden digest")
    return obj


def is_ip(s):
    try:
        ipaddress.ip_address(s)
    except ValueError:
        return False
    return True


class Checks:
    def __init__(self, policy):
        self.literals = [s.casefold() for s in policy.get("forbidden_literals", [])]
        self.hosts = PUBLIC_HOSTS | {s.lower() for s in policy.get("allowed_url_hosts", [])}
        self.approved = policy.get("approved_files")
        self.denied = set(policy.get("forbidden_sha256", []))
        self.catalog_keys = {}
        self.image_pairs = {}
        self.route_sources = set()

    def text(self, value, ctx, *, english=False, python_source=False):
        require(not HIDDEN.search(value), ctx, "hidden control or invalid Unicode")
        normalized = unicodedata.normalize("NFKC", value)
        folded = normalized.casefold()
        require(not any(s in folded for s in self.literals), ctx, "private policy literal")
        require(not SECRET.search(normalized), ctx, "credential-shaped text")
        require(not LOCATIONS.search(normalized), ctx, "machine-specific path")
        require(not DOMAINS.search(normalized), ctx, "private host")
        require(not SOURCE_SCRIPT.search(normalized), ctx, "source-language text")
        require(not HEX_BYTES.search(normalized) and not DATA_URI.search(normalized), ctx, "encoded payload")
        for match in ADDRESS.finditer(normalized):
            require(not is_ip(match[0]), ctx, "literal network address")
        # Python slice expressions can look identical to IPv6. For Python,
        # check addresses in parsed strings and comments where text can occur.
        if not python_source:
            for match in IPV6.finditer(normalized):
                require(not is_ip(match[0]), ctx, "literal network address")
        for match in URL.finditer(normalized):
            parsed = urlsplit(match[0])
            require(parsed.scheme.lower() in {"https", "http"} and parsed.hostname in self.hosts and
                    parsed.username is None and parsed.password is None, ctx, "unapproved URL")
        for match in OPAQUE.finditer(normalized):
            token = match[0]
            # Hashes and code identifiers occur in documentation and source. Text
            # values have dedicated hash fields for all source references.
            plain_hash = not english and len(token) in {64, 128} and re.fullmatch(r"[0-9A-Fa-f]+", token)
            require(plain_hash, ctx, "opaque text payload")

    def english(self, value, ctx):
        require(isinstance(value, str), ctx, "English value must be a string")
        self.text(value, ctx, english=True)

    def board_templates(self, obj):
        name = BOARD_TEMPLATES
        exact(obj, ("schema_version", "kind", "english_template", "tables"), name)
        require(type(obj["schema_version"]) is int and obj["schema_version"] == 2
                and obj["kind"] == "local-board-name", name, "unsupported template format")
        english = obj["english_template"]
        self.english(english, name)
        slot = "{BoardName}"
        require(english.count(slot) == 1, name, "expected exactly one board-name slot")
        literal = english.replace(slot, "")
        require(re.search("[A-Za-z]", literal) and all(c == "\n" or 32 <= ord(c) <= 126 for c in literal)
                and not any(c in literal for c in "<>{}"), name, "unexpected template text or markup")
        require(isinstance(obj["tables"], list) and obj["tables"], name, "expected template tables")
        pairs, positions, roster = set(), set(), []
        for table in obj["tables"]:
            exact(table, ("uasset_sha256", "uexp_sha256", "rows"), name)
            pair = (table["uasset_sha256"], table["uexp_sha256"])
            require(all(isinstance(h, str) and HEX.fullmatch(h) for h in pair), name, "invalid table fingerprint")
            require(pair not in pairs, name, "duplicate template table")
            pairs.add(pair)
            require(isinstance(table["rows"], list) and table["rows"], name, "empty or invalid template table")
            for row in table["rows"]:
                exact(row, ("ordinal", "source_sha256"), name)
                ordinal, source = row["ordinal"], row["source_sha256"]
                require(type(ordinal) is int and ordinal >= 0, name, "invalid template ordinal")
                require(isinstance(source, str) and HEX.fullmatch(source), name, "invalid source fingerprint")
                position = (*pair, ordinal)
                require(position not in positions, name, "duplicate template ordinal")
                positions.add(position)
                roster.append((*position, source))
        encoded = json.dumps(sorted(roster), separators=(",", ":")).encode("ascii")
        require(digest(encoded) == BOARD_POSITIONS_SHA256, name, "unexpected template positions")
        return positions

    def catalog(self, name, raw):
        obj = parse_json(raw)
        if name == BOARD_TEMPLATES:
            return self.board_templates(obj)
        collection = "tables" if name == NATIVE else "entries"
        exact(obj, ("schema_version", collection), name)
        require(type(obj["schema_version"]) is int and obj["schema_version"] == 1, name, "unsupported schema")
        records = obj[collection]
        require(isinstance(records, list), name, "catalog collection must be an array")
        seen = set()
        script_pairs = {}
        script_lines = set()
        previous_key = ""
        for idx, rec in enumerate(records):
            pos = f"{name} record {idx}"
            if name == NATIVE:
                exact(rec, ("uasset_sha256", "uexp_sha256", "rows"), pos)
                pair = tuple(rec[k] for k in ("uasset_sha256", "uexp_sha256"))
                require(all(isinstance(s, str) and HEX.fullmatch(s) for s in pair), pos, "invalid table fingerprint")
                require(pair not in seen, pos, "duplicate table")
                seen.add(pair)
                require(isinstance(rec["rows"], list) and rec["rows"], pos, "empty or invalid table")
                ordinals = set()
                for ridx, row in enumerate(rec["rows"]):
                    at = f"{pos} row {ridx}"
                    exact(row, ("ordinal", "source_sha256", "english"), at)
                    ordinal = row["ordinal"]
                    require(type(ordinal) is int and ordinal >= 0 and ordinal not in ordinals, at, "invalid or duplicate ordinal")
                    ordinals.add(ordinal)
                    require(isinstance(row["source_sha256"], str) and HEX.fullmatch(row["source_sha256"]), at, "invalid fingerprint")
                    self.english(row["english"], at)
            elif name == SERVICE:
                exact(rec, ("table", "id", "source_sha256", "english"), pos)
                table, key = rec["table"], rec["id"]
                require(isinstance(table, str) and TABLE_NAME.fullmatch(table), pos, "invalid table identifier")
                require(type(key) is int or isinstance(key, str) and STRING_ID.fullmatch(key), pos, "invalid row identifier")
                self.text(table, pos)
                if isinstance(key, str):
                    self.text(key, pos)
                identity = (table, key)
                require(identity not in seen, pos, "duplicate row")
                seen.add(identity)
                require(isinstance(rec["source_sha256"], str) and HEX.fullmatch(rec["source_sha256"]), pos, "invalid fingerprint")
                self.english(rec["english"], pos)
            elif name == SCRIPT_SOURCES:
                fields = ("key_sha256", "asset_path_sha256", "uasset_sha256", "uexp_sha256")
                exact(rec, (*fields, "source_line"), pos)
                require(all(isinstance(rec[f], str) and HEX.fullmatch(rec[f]) for f in fields), pos,
                        "invalid script fingerprint")
                key, path, header, export = (rec[f] for f in fields)
                line = rec["source_line"]
                require(key > previous_key, pos, "expected unique, sorted script keys")
                require(type(line) is int and 1 <= line <= 0x7fffffff, pos, "invalid script line number")
                require(script_pairs.setdefault(path, (header, export)) == (header, export), pos,
                        "conflicting fingerprints for one script")
                require((path, line) not in script_lines, pos, "duplicate line in one script")
                script_lines.add((path, line))
                seen.add(key)
                previous_key = key
            elif name == MENU_RUNTIME:
                exact(rec, ("key_sha256", "unreal_key_hash"), pos)
                key, runtime_hash = rec["key_sha256"], rec["unreal_key_hash"]
                require(isinstance(key, str) and HEX.fullmatch(key) and key > previous_key, pos,
                        "expected unique, sorted SHA-256 menu keys")
                require(type(runtime_hash) is int and 0 <= runtime_hash <= 0xffffffff, pos,
                        "expected an unsigned 32-bit runtime key hash")
                previous_key = key
                seen.add(key)
            else:
                exact(rec, ("key_sha256", "english"), pos)
                key = rec["key_sha256"]
                require(isinstance(key, str) and HEX.fullmatch(key) and key not in seen, pos, "invalid or duplicate key")
                seen.add(key)
                self.english(rec["english"], pos)
        return seen

    def blob(self, name, raw):
        sha = digest(raw)
        require(sha not in self.denied, name, "forbidden file digest")
        if self.approved is not None:
            require(sha in self.approved.get(name, []), name, "digest absent from trusted release policy")
        try:
            text = raw.decode("utf-8", errors="strict")
            if name not in DOCS | TOOLS:
                keys = self.catalog(name, text)
                if name == BOARD_TEMPLATES:
                    require(sha == BOARD_CATALOG_SHA256, name, "unreviewed template catalog digest")
                if name in {MENU, MENU_RUNTIME, SCRIPT, SCRIPT_SOURCES, BOARD_TEMPLATES}:
                    self.catalog_keys[sha] = keys
                if name == IMAGE_LABELS:
                    self.image_pairs[sha] = {(row["key_sha256"], row["english"])
                                             for row in parse_json(raw)["entries"]}
            else:
                self.text(text, name, python_source=name in TOOLS)
                if name in TOOLS:
                    source = ast.parse(text, filename=name)
                    if name in ROUTE_TOOLS and has_route_source(name, source):
                        self.route_sources.add((name, sha))
                    for token in tokenize.generate_tokens(io.StringIO(text).readline):
                        if token.type == tokenize.COMMENT:
                            self.text(token.string, f"{name} line {token.start[0]}")
                    for node in ast.walk(source):
                        if isinstance(node, ast.Constant):
                            if isinstance(node.value, str):
                                # Paired-file readers use a one-character NUL field terminator.
                                if node.value != chr(0):
                                    self.text(node.value, f"{name} line {node.lineno}")
                            elif isinstance(node.value, bytes):
                                require(len(node.value) < 256, name, "large embedded bytes literal")
                                for part in re.findall(rb"[ -~]+", node.value):
                                    self.text(part.decode("ascii"), f"{name} line {node.lineno}")
        except (UnicodeError, json.JSONDecodeError, SyntaxError) as error:
            raise ScanError(f"{name}: invalid UTF-8, JSON or Python source") from error
        return {"bytes": len(raw), "sha256": sha}


    def help_tree(self, entries):
        if not ROUTE_TOOLS.intersection(entries):
            return
        require(HELP_TOOLS.issubset(entries), "Help tools", "missing companion tool")
        require(IMAGE_LABELS in entries, IMAGE_LABELS, "missing help label catalog")
        pairs = self.image_pairs[entries[IMAGE_LABELS]["sha256"]]
        require(HELP_LABELS <= pairs, IMAGE_LABELS, "missing matching help image label")
        active = {name for name in ROUTE_TOOLS.intersection(entries)
                  if (name, entries[name]["sha256"]) in self.route_sources}
        if active or ROUTE_CODEC in entries:
            require(active == ROUTE_TOOLS, "Route Guide", "missing matching builder, lettering or texture reader")
            require(ROUTE_LABEL in pairs, IMAGE_LABELS, "missing matching Route Guide description")


def has_route_source(name, source):
    if name == "tools/build_help.py":
        return any((isinstance(node, ast.ImportFrom) and node.module == "route_help_texture"
                    and any(alias.name == "render_pair" for alias in node.names))
                   or (isinstance(node, ast.Import) and
                       any(alias.name == "route_help_texture" for alias in node.names))
                   for node in ast.walk(source))
    function = "render_pair" if name == ROUTE_CODEC else "render_route"
    return any(isinstance(node, ast.FunctionDef) and node.name == function for node in source.body)


def signature(lines):
    first, *continuations = lines
    armor = [first, *(x.removeprefix(" ") for x in continuations)]
    return (len(armor) >= 3 and armor[0] in {"-----BEGIN PGP SIGNATURE-----", "-----BEGIN SSH SIGNATURE-----"} and
            armor[-1] == armor[0].replace("BEGIN", "END") and
            all(not s or re.fullmatch(r"[A-Za-z0-9+/=]+", s) for s in armor[1:-1]))


def commit_object(repo, oid, checks):
    obj = git(repo, "cat-file", "commit", oid).decode("utf-8", errors="strict")
    metadata, sep, message = obj.partition("\n\n")
    ctx = "commit " + oid[:12]
    require(sep, ctx, "missing commit header")
    checks.text(message, ctx)
    headers = []
    for line in metadata.split("\n"):
        if line.startswith(" "):
            require(headers, ctx, "invalid commit header continuation")
            headers[-1][1].append(line)
        else:
            field, space, value = line.partition(" ")
            require(space, ctx, "invalid commit header")
            headers.append((field, [value]))
    tree, parents = None, []
    for field, values in headers:
        if field in {"gpgsig", "gpgsig-sha256"}:
            require(signature(values), ctx, "unrecognized commit signature")
        else:
            require(len(values) == 1, ctx, "unexpected multiline header")
            value = values[0]
            if field in {"tree", "parent"}:
                require(OBJECT.fullmatch(value), ctx, "invalid Git object ID")
                if field == "tree":
                    require(tree is None, ctx, "multiple trees")
                    tree = value
                else:
                    parents.append(value)
            elif field in {"author", "committer"}:
                checks.text(value, ctx)
            else:
                require(field == "encoding" and value.upper() in {"UTF-8", "UTF8"}, ctx, "unsupported commit header")
    require(tree is not None, ctx, "missing tree")
    return tree, parents


def scan(repo, commit, policy):
    checks = Checks(policy)
    resolved = git(repo, "rev-parse", "--verify", "--end-of-options", commit + "^{commit}").decode("ascii").strip()
    require(OBJECT.fullmatch(resolved), "commit", "unable to resolve revision")
    pending, commits, trees, blobs = [resolved], set(), {}, {}
    tip_tree = None
    literal_positions = {}
    hud_catalogs = set()
    while pending:
        oid = pending.pop()
        if oid in commits:
            continue
        tree, parents = commit_object(repo, oid, checks)
        commits.add(oid)
        pending.extend(parents)
        if oid == resolved:
            tip_tree = tree
        if tree in trees:
            continue
        entries = {}
        listing = git(repo, "ls-tree", "-r", "-t", "-z", "--full-tree", tree)
        for record in listing.split(b"\0"):
            if not record:
                continue
            header, raw_name = record.split(b"\t", 1)
            mode, kind, obj = header.decode("ascii").split()
            name = raw_name.decode("utf-8", errors="strict")
            if kind == "tree":
                require(mode == "040000" and name in {"tools", "translations"}, "tree " + tree[:12], "unapproved directory")
                continue
            require(name in FILES, "tree " + tree[:12], "unapproved filename")
            require(name not in entries and kind == "blob" and (mode == "100644" or mode == "100755" and name in TOOLS), name, "unsupported file mode/type")
            key = (name, obj)
            if key not in blobs:
                size = int(git(repo, "cat-file", "-s", obj))
                require(size <= MAX_BYTES, name, "oversized file")
                raw = git(repo, "cat-file", "blob", obj)
                require(len(raw) == size, name, "blob readback mismatch")
                blobs[key] = checks.blob(name, raw)
            entries[name] = dict(mode=mode, git_blob=obj, **blobs[key])
        if HUD_TOOLS.intersection(entries):
            require(HUD_TOOLS.issubset(entries), "HUD tools", "missing companion tool")
            require(IMAGE_LABELS in entries, IMAGE_LABELS, "missing HUD label catalog")
            image_catalog = entries[IMAGE_LABELS]["git_blob"]
            if image_catalog not in hud_catalogs:
                catalog = parse_json(git(repo, "cat-file", "blob", image_catalog))
                fps_keys = {row["key_sha256"] for row in catalog["entries"] if row["english"] == "FPS Counter"}
                require(HUD_FPS_KEYS <= fps_keys, IMAGE_LABELS, "missing matching FPS label for a HUD preset")
                hud_catalogs.add(image_catalog)
        checks.help_tree(entries)
        if BOARD_TEMPLATES in entries:
            require(NATIVE in entries, BOARD_TEMPLATES, "missing native catalog")
            native = entries[NATIVE]["git_blob"]
            if native not in literal_positions:
                catalog = parse_json(git(repo, "cat-file", "blob", native))
                literal_positions[native] = {
                    (table["uasset_sha256"], table["uexp_sha256"], row["ordinal"])
                    for table in catalog["tables"] for row in table["rows"]
                }
            template_positions = checks.catalog_keys[entries[BOARD_TEMPLATES]["sha256"]]
            require(template_positions.isdisjoint(literal_positions[native]),
                    BOARD_TEMPLATES, "template position also present in native catalog")
        for bindings, english in ((MENU_RUNTIME, MENU), (SCRIPT_SOURCES, SCRIPT)):
            if bindings in entries:
                require(english in entries, bindings, "missing translation catalog")
                binding_keys = checks.catalog_keys[entries[bindings]["sha256"]]
                english_keys = checks.catalog_keys[entries[english]["sha256"]]
                require(binding_keys == english_keys, bindings, "binding and English key sets differ")
        trees[tree] = entries
    return {"schema_version": 1, "status": "PASS", "commit": resolved, "tree": tip_tree,
            "reachable_commits": len(commits), "distinct_trees": len(trees), "distinct_path_blobs": len(blobs),
            "provenance_policy_checked": bool(policy), "files": dict(sorted(trees[tip_tree].items()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="standalone Git working tree")
    parser.add_argument("--commit", required=True, help="release commit or revision")
    parser.add_argument("--receipt", required=True, type=Path, help="JSON output outside the working tree")
    parser.add_argument("--policy", type=Path, help="external reviewed release policy")
    args = parser.parse_args()
    repo = Path(os.fsdecode(git(args.repo, "rev-parse", "--show-toplevel")).rstrip("\n")).resolve()
    output = args.receipt.resolve()
    require(not output.is_relative_to(repo), "receipt", "output must be outside the working tree")
    policy, raw_policy = {}, None
    if args.policy is not None:
        external = args.policy.resolve()
        require(not external.is_relative_to(repo) and external != output, "policy", "choose a separate external policy")
        raw_policy = external.read_bytes()
        policy = load_policy(raw_policy)
    report = scan(repo, args.commit, policy)
    if raw_policy is not None:
        report["policy_sha256"] = digest(raw_policy)
    raw = (json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
        temp = f.name
    os.replace(temp, output)
    print(f"PASS {report['commit']} ({report['reachable_commits']} commits, {len(report['files'])} files)")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, UnicodeError, RecursionError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
