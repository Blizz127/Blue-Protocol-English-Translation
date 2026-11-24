#!/usr/bin/env python3
"""Scan a proposed public Git commit, its trees and every reachable ancestor."""
import argparse
import ast
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unicodedata
from urllib.parse import urlsplit


DOCS = {"README.md", "LICENSE", "STYLE.md", ".gitignore"}
TOOLS = {"tools/build_patch.py", "tools/native_tables.py", "tools/overlay_archive.py", "tools/scan_public.py"}
SERVICE = "translations/service.json"
NATIVE = "translations/native.json"
INDEXED = {"translations/menu-inline.json", "translations/image-labels.json", "translations/script.json"}
FILES = DOCS | TOOLS | INDEXED | {SERVICE, NATIVE}
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

    def text(self, value, ctx, *, english=False):
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

    def catalog(self, name, raw):
        obj = parse_json(raw)
        collection = "tables" if name == NATIVE else "entries"
        exact(obj, ("schema_version", collection), name)
        require(type(obj["schema_version"]) is int and obj["schema_version"] == 1, name, "unsupported schema")
        records = obj[collection]
        require(isinstance(records, list), name, "catalog collection must be an array")
        seen = set()
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
            else:
                exact(rec, ("key_sha256", "english"), pos)
                key = rec["key_sha256"]
                require(isinstance(key, str) and HEX.fullmatch(key) and key not in seen, pos, "invalid or duplicate key")
                seen.add(key)
                self.english(rec["english"], pos)

    def blob(self, name, raw):
        sha = digest(raw)
        require(sha not in self.denied, name, "forbidden file digest")
        if self.approved is not None:
            require(sha in self.approved.get(name, []), name, "digest absent from trusted release policy")
        try:
            text = raw.decode("utf-8", errors="strict")
            if name not in DOCS | TOOLS:
                self.catalog(name, text)
            else:
                self.text(text, name)
                if name in TOOLS:
                    source = ast.parse(text, filename=name)
                    for node in ast.walk(source):
                        if isinstance(node, ast.Constant):
                            if isinstance(node.value, str):
                                # Paired-file readers use a one-character NUL field terminator.
                                if node.value != chr(0):
                                    self.text(node.value, f"{name} line {node.lineno}")
                            elif isinstance(node.value, bytes):
                                require(len(node.value) < 256, name, "large embedded bytes literal")
                                if node.value.isascii() and node.value.decode("ascii").isprintable():
                                    self.text(node.value.decode("ascii"), f"{name} line {node.lineno}")
        except (UnicodeError, json.JSONDecodeError, SyntaxError) as error:
            raise ScanError(f"{name}: invalid UTF-8, JSON or Python source") from error
        return {"bytes": len(raw), "sha256": sha}


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
