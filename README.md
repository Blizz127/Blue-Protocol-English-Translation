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

## Build the English startup notice

The notice builder draws five English labels on the startup artwork from your own client. Start with these two files from your existing extraction in the `owned-files/` folder.

- `BLUEPROTOCOL/Content/UI/Startup/UI_StartupCaution1.uasset`
- `BLUEPROTOCOL/Content/UI/Startup/UI_StartupCaution1.uexp`

Use Python 3.11 or newer for the notice builder. It was tested with Pillow 13.0.0 and FreeType 2.14.3. On Windows, you can install the tested Pillow version in a separate environment using PowerShell.

```powershell
py -3.11 -m venv .notice-venv
.\.notice-venv\Scripts\python.exe -m pip install Pillow==13.0.0
```

Use that same `.\.notice-venv\Scripts\python.exe` in place of `python3` in the build command below. Supply these two Liberation Sans font files from your computer. The builder checks the SHA-256 of each file, so a different version with the same filename can fail the check.

| Option | Font file | Required SHA-256 |
| --- | --- | --- |
| `--title-font` | `LiberationSans-Regular.ttf` | `075e71be4c58beda172ecb574a799308f04c3d054c6a5b7434954d3b0f1b28d8` |
| `--body-font` | `LiberationSans-Bold.ttf` | `b72c65e551d653b54217ffad0d1454ce0657e4e8d4a28bcc79e0acd2598f4bf3` |

Replace each `PATH` with the path to the matching font file and choose a new output folder.

```sh
python3 tools/build_notice.py --input owned-files --output english-notice --title-font PATH --body-font PATH --archive
```

On a setup that supports local overlays, close the game and copy `english-notice/blue_protocol_notice_1_P.pak` to `BLUEPROTOCOL/Content/Paks/~mods/` in your installation. To undo the change, remove the archive you added. If you replace an earlier notice archive, keep a backup to restore.

## Translate the HUD preset diagrams

The left and right preset previews in HUD settings each have 19 labels. This tool translates 12 labels on each diagram, including the FPS counter, quest list, chat logs and ST gauge. The other seven keep the Japanese lettering from your client.

Extract both original file pairs into `owned-files/BLUEPROTOCOL/Content/UI/Option/HUD/` from your copy of the Japanese 1.08.001 client. The filenames are `UI_OptionMenuHudLeft.uasset`, `UI_OptionMenuHudLeft.uexp`, `UI_OptionMenuHudRight.uasset` and `UI_OptionMenuHudRight.uexp`.

Supply a local copy of `LiberationSansNarrow-Bold.ttf` with SHA-256 `3271f41b67a81a806aadbf71762c14a405e617b738d9ceeb81191dd681c66fc4`. This build was tested with Python 3.12 and OpenCV 5.1.0, wheel build 95. Run them in an environment where you want the image libraries installed. Replace the font filename with its path on your computer.

```sh
python3 -m pip install Pillow==13.0.0 numpy==2.5.1 'opencv-python-headless~=5.1.0'
python3 tools/build_hud.py --input owned-files --output english-hud --font LiberationSansNarrow-Bold.ttf --archive
```

The command checks the four stock files, draws on their original pixels and writes the translated pairs to a new folder. On a setup that supports local overlays, close the game and copy `english-hud/blue_protocol_hud_1_P.pak` to `BLUEPROTOCOL/Content/Paks/~mods/`. Keep a backup if you replace an older HUD overlay. To undo the change, remove the added archive and restore that backup if you made one.

## Translate Route Guide and Liquid Memory help captions

On page two of the Chapter 1 Route Guide, the translated quest-tab description reads **This tab lists your active and completed quests.** The help builder also draws the English effect line on nine Liquid Memory panels. Each panel keeps its original Japanese heading and illustration. The early Asterleeds gathering-yield panel reads **Increased Gathering Yield**.

From your Japanese 1.08.001 client, extract matching `.uasset` and `.uexp` pairs into `owned-files/BLUEPROTOCOL/Content/UI/Image/TutorialHelp/`. For the Route Guide alone, supply `RouteGuide.uasset` and `RouteGuide.uexp`. For the gathering-yield panel alone, use `UI_TutorialHelp00062.uasset` and `UI_TutorialHelp00062.uexp`. The tool also recognizes `UI_TutorialHelp00063`, `UI_TutorialHelp00064` (Reduced Shop Costs), `UI_TutorialHelp00065`, `UI_TutorialHelp00066` and `LiquidMemory_guide_06` through `LiquidMemory_guide_09`.

Use Python 3.12, Pillow 13.0.0 and the same local `LiberationSans-Bold.ttf` used for the startup notice. Pass the path to your font file.

```sh
python3 -m pip install Pillow==13.0.0
python3 tools/build_help.py --input owned-files --output english-help --font LiberationSans-Bold.ttf --archive
```

The default builds every supported complete pair in the folder. Add `--require-all` to require the eight previously supported Liquid Memory pairs. The shop discount panel and Route Guide are included whenever you supply their matching pairs. An incomplete pair or a mismatched source file stops the build. For a client that supports local overlays, close the game and copy `english-help/blue_protocol_help_1_P.pak` to `BLUEPROTOCOL/Content/Paks/~mods/`. Back up any earlier help archive you replace. To undo the change, remove the added archive and restore that backup if you made one.

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

The menu builder pairs `menu-inline.json` with the engine lookup hashes in `menu-runtime.json`. The dialogue builder pairs `script.json` with the original package fingerprints and line numbers in `script-sources.json`. The notice builder uses the five startup labels in `image-labels.json`, and the HUD builder uses the 24 preset-diagram labels. The help builder uses the Route Guide description and nine Liquid Memory effect captions. The three catalogs below use a SHA-256 lookup key computed from a compact UTF-8 JSON array, with unescaped Unicode, no spaces between fields and no trailing newline. The source hash is the lowercase SHA-256 of the exact original UTF-8 text.

| Catalog | Fields in the lookup array, in order |
| --- | --- |
| `menu-inline.json` | Namespace, entry key, source hash |
| `image-labels.json` | Canonical package name, zero-based label index, source hash |
| `script.json` | Asset, function, callee, call ordinal, argument index, source hash |

See the [localization style guide](STYLE.md) and [player-use license](LICENSE).
