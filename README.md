# Blue Protocol English Translation

Build English text for the Japanese PC release of Blue Protocol (1.08.001) using files from your own copy. The catalogs cover selected menus, tutorials, dialogue, weapon perks and emotes. You can build English overlays for menus, native text and selected dialogue, or translate a compatible service text JSON file. You hear the original Japanese voices.

## Build the English menus

Use Python 3.9 or newer. From your own updated client, extract the original files into a folder named `owned-files`, preserving their directory layout. The menu builder reads four locations under `BLUEPROTOCOL/Content/`.

- `Localization/Game/ja/Game.locres`
- `Blueprints/UI/`
- `Blueprints/Player/`
- `LevelDesign/Widget/`

Keep the matching `.uasset` and `.uexp` files together. The original Japanese menu text lives in the widgets. The builder uses it to match each English entry before writing a localization resource.

```sh
python3 tools/build_menu.py --input owned-files --output english-menus --archive --require-all
```

A complete matching input builds 322 menu entries. The command writes the translated resource and `english-menus/blue_protocol_menus_1_P.pak`. On a setup that supports local overlays, close the game and copy that archive to `BLUEPROTOCOL/Content/Paks/~mods/`. You can use it alongside the native text archive below. Keep a backup if you replace a previous overlay. To undo the change, remove the archive you added and restore the backup. Omit `--require-all` to build the entries present in a partial extraction. Choose a fresh output folder each time.

## Build a native text overlay

You need Python 3.9 or newer and an extracted copy of the game’s effective text files, with later game updates applied in their normal order. Your input folder should contain `BLUEPROTOCOL/Content/Text/` with matching `.uasset` and `.uexp` pairs. Run this command from the repository directory. Choose an output folder that does not yet exist.

```sh
python3 tools/build_patch.py native --input owned-files --output patched-files --archive
```

On Windows, you can use `py -3` in place of `python3`. The tool writes the translated pairs under `patched-files/BLUEPROTOCOL/Content/Text/` and builds `patched-files/blue_protocol_english_1_P.pak`. It checks the original file hashes and reads each rebuilt table back before writing the result. Omit `--archive` if you only need the translated pairs.

To include Adventure Board prompts, add `--board-templates` to the native command. It loads `translations/native-board-templates.json` and fills the board-name slot from the matching row in your own game files. You can supply a different template catalog with `--board-templates PATH`.

For a client setup that supports local overlays, close the game and place the new archive in `BLUEPROTOCOL/Content/Paks/~mods/` within the installation. Keep a copy of any older English overlay you replace. To undo the installation, remove the archive you added and restore the earlier overlay if you used one. The build command leaves your input files in place.

## Build the Chapter 1 dialogue overlay

Four villager lines in two Chapter 1 scripts have English translations. Extract the matching `.uasset` and `.uexp` files from your copy of the Japanese 1.08.001 client, preserving the directory tree under `owned-files/BLUEPROTOCOL/Content/Script/`. From the repository directory, run this command with Python 3.9 or newer.

```sh
python3 tools/build_script.py --input owned-files --output english-dialogue --archive --require-all
```

The builder checks both original file hashes, locates the dialogue calls, and reads back the English lines. It writes the translated pairs and `english-dialogue/blue_protocol_script_1_P.pak`. If your setup supports local overlays, close the game and copy the archive to `BLUEPROTOCOL/Content/Paks/~mods/`. It can be installed alongside the menu and native text archives from this project. Back up any previous copy of the dialogue archive before replacing it. To undo the change, remove the archive you added and restore that backup if you have one.

## Translate a service text file

If your setup uses a JSON list of named tables with `texts` rows containing `id` and `text`, supply your original file and choose a new output filename.

```sh
python3 tools/build_patch.py service --input owned-files/texts.json --output english-texts.json
```

The tool matches the table, the ID including its type, and the SHA-256 of the original UTF-8 text. It reports rows changed, already translated, missing and skipped because the source differs. Use `--strict` to fail when a recognized row has unexpected text. Import the output using the text-loading mechanism for your setup. Keep the original file for rollback.

## Catalogs

`translations/native.json` indexes each native table by its two file hashes and each translated row by its ordinal and source hash. `translations/service.json` indexes service text by table, row ID and source hash. A partial input can build an overlay for the matching tables it contains. Text outside the catalogs keeps its existing value.

The menu builder pairs `menu-inline.json` with the engine lookup hashes in `menu-runtime.json`. The dialogue builder pairs `script.json` with the original package fingerprints and line numbers in `script-sources.json`. Image labels are available as a reference catalog. The three catalogs below use a SHA-256 lookup key computed from a compact UTF-8 JSON array, with unescaped Unicode, no spaces between fields and no trailing newline. The source hash is the lowercase SHA-256 of the exact original UTF-8 text.

| Catalog | Fields in the lookup array, in order |
| --- | --- |
| `menu-inline.json` | Namespace, entry key, source hash |
| `image-labels.json` | Canonical package name, zero-based label index, source hash |
| `script.json` | Asset, function, callee, call ordinal, argument index, source hash |

See the [localization style guide](STYLE.md) and [player-use license](LICENSE).
