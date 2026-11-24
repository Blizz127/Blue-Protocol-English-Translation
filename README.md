# Blue Protocol English Translation

Build English text for the Japanese PC release of Blue Protocol (1.08.001) using files from your own copy. The catalogs cover selected menus, tutorials, dialogue, weapon perks and emotes. You can build a native text overlay, translate a compatible service text JSON file, or use the catalog entries in a localization tool. You hear the original Japanese voices.

## Build a native text overlay

You need Python 3.9 or newer and an extracted copy of the game’s effective text files, with later game updates applied in their normal order. Your input folder should contain `BLUEPROTOCOL/Content/Text/` with matching `.uasset` and `.uexp` pairs. Run this command from the repository directory. Choose an output folder that does not yet exist.

```sh
python3 tools/build_patch.py native --input owned-files --output patched-files --archive
```

On Windows, you can use `py -3` in place of `python3`. The tool writes the translated pairs under `patched-files/BLUEPROTOCOL/Content/Text/` and builds `patched-files/blue_protocol_english_1_P.pak`. It checks the original file hashes and reads each rebuilt table back before writing the result. Omit `--archive` if you only need the translated pairs.

For a client setup that supports local overlays, close the game and place the new archive in `BLUEPROTOCOL/Content/Paks/~mods/` within the installation. Keep a copy of any older English overlay you replace. To undo the installation, remove the archive you added and restore the earlier overlay if you used one. The build command leaves your input files in place.

## Translate a service text file

If your setup uses a JSON list of named tables with `texts` rows containing `id` and `text`, supply your original file and choose a new output filename.

```sh
python3 tools/build_patch.py service --input owned-files/texts.json --output english-texts.json
```

The tool matches the table, the ID including its type, and the SHA-256 of the original UTF-8 text. It reports rows changed, already translated, missing and skipped because the source differs. Use `--strict` to fail when a recognized row has unexpected text. Import the output using the text-loading mechanism for your setup. Keep the original file for rollback.

## Catalogs

`translations/native.json` indexes each native table by its two file hashes and each translated row by its ordinal and source hash. `translations/service.json` indexes service text by table, row ID and source hash. A partial input can build an overlay for the matching tables it contains. Text outside the catalogs keeps its existing value.

Three reference catalogs supply English for localization tools that can identify the original UI or script entry. The player patcher currently builds the native and service catalogs. The other catalogs use a SHA-256 lookup key computed from a compact UTF-8 JSON array, with unescaped Unicode, no spaces between fields and no trailing newline. In the lists below, the source hash is the lowercase SHA-256 of the exact original text encoded as UTF-8.

| Catalog | Fields in the lookup array, in order |
| --- | --- |
| `menu-inline.json` | Namespace, entry key, source hash |
| `image-labels.json` | Canonical package name, zero-based label index, source hash |
| `script.json` | Asset, function, callee, call ordinal, argument index, source hash |

See the [localization style guide](STYLE.md) and [player-use license](LICENSE).
