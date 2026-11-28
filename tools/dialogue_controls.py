"""Resolve English dialogue templates against controls in the player's own data."""

from hashlib import sha256
from pathlib import Path
import re
import unicodedata

from native_tables import _Export, _summary


WORD_PATH = Path("BLUEPROTOCOL/Content/Word/WordDataTable")
PUNCTUATION_PATH = Path("BLUEPROTOCOL/Content/Blueprints/Manager") / "DT_RichTextShortSyntaxDB"
PUNCTUATION_PAIR = (
    "fd058cf4f908eb007f49cd7f916d2b7903f2aafd415519015594ca2cebc0b4ef",
    "d58b698364f77308c10548889ea558ff71577cb97725d38bf55477f4360e8ba2",
)
QUOTES = {
    "OpenQuote": ("91d7640678cdbcbbba1d3c263cb81578a9dad1262f88e2a56e4594456b1769ad", "“"),
    "CloseQuote": ("b72463c14159de4fb05314bbe87427f188c8e257daa14ceb49223b60b24f5a23", "”"),
}
ALIAS_NUMBER = 271828183


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return sha256(data).hexdigest()


def fields(record, keys):
    require(isinstance(record, dict) and set(record) == set(keys), "Unexpected dialogue catalog fields")


def checked_hash(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "Invalid dialogue fingerprint")
    return value


def member_hashes(record):
    return checked_hash(record["uasset_sha256"]), checked_hash(record["uexp_sha256"])


def local_members(root, name):
    files = tuple((root / name).with_suffix(ext) for ext in (".uasset", ".uexp"))
    require(all(p.is_file() and p.resolve() == p for p in files), "Required local control table is missing or indirect")
    return tuple(p.read_bytes() for p in files)


def english_prose(value):
    return isinstance(value, str) and bool(re.search("[A-Za-z]", value)) and all(
        c in "\r\n" or (c.isprintable() and (not c.isalpha() or unicodedata.name(c, "").startswith("LATIN ")))
        for c in value)


def render(original, row):
    fields(row, ("ordinal", "source_sha256", "english", "controls"))
    require(digest(original.encode()) == checked_hash(row["source_sha256"]), "Different dialogue source")
    tokens = re.findall(r"\[([^\[\]\r\n]+)\]", original)
    require(len(tokens) == original.count("[") == original.count("]") and
            isinstance(row["controls"], list) and 0 < len(tokens) == len(row["controls"]), "Unexpected dialogue controls")
    template = row["english"]
    require(isinstance(template, str), "Missing English dialogue")
    names = re.findall(r"\{([A-Za-z0-9]+)\}", template)
    literal = re.sub(r"\{[A-Za-z0-9]+\}", "", template)
    require(english_prose(literal) and not any(c in literal for c in "[]{}<>") and len(names) == len(tokens),
            "Invalid English dialogue template")
    require(re.findall(r"\r\n|\r|\n", original) == re.findall(r"\r\n|\r|\n", template), "Dialogue line breaks differ")
    result = template
    words = set()
    word_number = 0
    quoted = False
    for token, name, fingerprint in zip(tokens, names, row["controls"]):
        key = checked_hash(fingerprint)
        require(digest(token.encode()) == key, "Different original dialogue control")
        if name in QUOTES:
            expected, replacement = QUOTES[name]
            require(key == expected and (name == "OpenQuote") != quoted, "Unexpected quotation control")
            quoted = not quoted
        else:
            require(name == f"Word{word_number}" and key not in {v[0] for v in QUOTES.values()}, "Unexpected word control")
            word_number += 1
            words.add(key)
            # The local dictionary gets an additional numbered name for the
            # English body. Other lines keep resolving the original word.
            replacement = f"[{token}_{ALIAS_NUMBER - 1}]"
        result = result.replace("{" + name + "}", replacement, 1)
    require(not quoted, "Missing closing quotation control")
    return result, words, any(n in QUOTES for n in names)


class DialogueControls:
    def __init__(self, catalog):
        fields(catalog, ("schema_version", "kind", "tables", "words", "word_editions"))
        require(type(catalog["schema_version"]) is int and catalog["schema_version"] == 1 and
                catalog["kind"] == "local-dialogue-controls", "Unsupported dialogue catalog")
        self.pairs = {}
        for table in catalog["tables"]:
            fields(table, ("uasset_sha256", "uexp_sha256", "rows"))
            pair = member_hashes(table)
            require(pair not in self.pairs and isinstance(table["rows"], list) and table["rows"], "Empty or duplicate table")
            self.pairs[pair] = table["rows"]
        require(bool(self.pairs), "No dialogue templates")
        self.headers = {pair[0] for pair in self.pairs}
        self.words = {}
        for w in catalog["words"]:
            fields(w, ("key_sha256", "body_sha256", "ruby_sha256", "english"))
            key = checked_hash(w["key_sha256"])
            require(key not in self.words and english_prose(w["english"]) and
                    not any(c in w["english"] for c in "<>[]{}\r\n"), "Invalid glossary body")
            self.words[key] = (checked_hash(w["body_sha256"]), checked_hash(w["ruby_sha256"]), w["english"], "")
        self.word_editions = set()
        for edition in catalog["word_editions"]:
            fields(edition, ("uasset_sha256", "uexp_sha256"))
            pair = member_hashes(edition)
            require(pair not in self.word_editions, "Duplicate glossary edition")
            self.word_editions.add(pair)
        require(bool(self.words) == bool(self.word_editions), "Incomplete glossary definition")
        self.seen = set()
        self.used_words = set()
        self.used_quotes = False

    def merge(self, pair, asset, export, ordinary):
        if pair[0] not in self.headers:
            return ordinary
        require(pair in self.pairs and pair not in self.seen, "Unrecognized or repeated original dialogue pair")
        self.seen.add(pair)
        _, names = _summary(asset, export)
        rows, _ = _Export(export, names).rows()
        merged = dict(ordinary or {})
        for entry in self.pairs[pair]:
            i = entry["ordinal"]
            require(type(i) is int and 0 <= i < len(rows) and i not in merged, "Unknown or overlapping dialogue row")
            value, words, quoted = render(rows[i][2], entry)
            require(words <= self.words.keys(), "Dialogue depends on an unknown glossary word")
            self.used_words.update(words)
            self.used_quotes |= quoted
            merged[i] = (entry["source_sha256"], value)
        return merged

    def glossary_output(self, root):
        require(self.seen, "No matching original dialogue table was found")
        if self.used_quotes:
            quote_members = local_members(root, PUNCTUATION_PATH)
            require(tuple(map(digest, quote_members)) == PUNCTUATION_PAIR, "Unknown local quotation table")
        if not self.used_words:
            return {}
        from glossary_alias import append_glossary_aliases
        asset, export = local_members(root, WORD_PATH)
        pair = digest(asset), digest(export)
        require(pair in self.word_editions, "Unknown local glossary edition")
        aliases = {key: (*self.words[key], ALIAS_NUMBER) for key in sorted(self.used_words)}
        changed = append_glossary_aliases(asset, export, pair, aliases)
        return {WORD_PATH.with_suffix(ext): content for ext, content in zip((".uasset", ".uexp"), changed)}
