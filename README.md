# Penforge profiles

3D-printer profiles for the Penforge app: printers with their print
settings (processes) and filaments, generated from the profile collections of
[OrcaSlicer](https://github.com/OrcaSlicer/OrcaSlicer) and PrusaSlicer
([PrusaSlicer-settings-prusa-fff](https://github.com/prusa3d/PrusaSlicer-settings-prusa-fff),
[PrusaSlicer-settings-non-prusa-fff](https://github.com/prusa3d/PrusaSlicer-settings-non-prusa-fff)).

This repository is data only. Penforge downloads `index.json` and the printer and filament files it needs from
`https://raw.githubusercontent.com/mKenfenheuer/penforge-profiles/main/` at runtime and reads them as data; nothing
from this repository ships inside the app. Because the source collections are licensed under the GNU Affero General
Public License 3.0, so is this repository (see [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md)).

Contents of the current revision: see `index.json` (`sources` names the exact upstream revisions).

## Reporting a wrong profile

Open an issue in this repository and include:

- the `id` of the printer or filament (for example `anycubic/kobra-s1-max-0-4`) and its `version` from `index.json`,
- the profile inside the file (process or filament variant name), the setting key, the value you see and the value
  you expect,
- if you know it, whether the upstream profile (the file named in `source`) has the same value.

Most values come unchanged from the upstream collections. A wrong value there is best fixed upstream (OrcaSlicer or
PrusaSlicer-settings); the next regeneration then picks it up. Problems the generator introduces (wrong grouping,
missing processes, wrong compatibility) are fixed here.

## Regenerating

Requirements: `git` and Python 3.9 or newer (standard library only).

```sh
python3 -I tools/build.py --fetch    # sparse, shallow checkouts of the pinned sources into .sources/ (git-ignored)
python3 -I tools/build.py            # writes index.json, printers/, filaments/
python3 -I tools/build.py --verify   # checks every index entry (sha256, bytes, canonical JSON, no scripts)
```

To move to newer upstream data, change `tag` and `commit` of a source in `tools/sources.json`, run the three
commands and commit the result. The generator compares every file with the `index.json` already in the repository:
unchanged files keep their `version`, changed files get the next one, new files start at 1, and the index `version`
goes up when anything changed. Running it twice in a row changes nothing.

`tools/catalog-ids.json` holds the numeric IDs of Penforge's previously bundled catalogue (written once with
`tools/build.py --import-catalog <dir>`); the generator copies them into `catalogID`. Profiles that are not in it get
no `catalogID`.

# Format

## Penforge profile catalogue: repository format 1

Public repository: https://github.com/mKenfenheuer/penforge-profiles (branch `main`)
App base URL: https://raw.githubusercontent.com/mKenfenheuer/penforge-profiles/main/

Licence: AGPL-3.0 (derived from the OrcaSlicer and PrusaSlicer-settings profile collections).
Penforge (closed source) only downloads and reads these files as data at runtime; nothing from them
ships inside the app.

### Layout

```
/index.json
/printers/<manufacturer>/<printer>.json
/filaments/<manufacturer>/<filament>.json
/LICENSE            AGPL-3.0 full text
/NOTICE.md          sources, revisions, authors, what was changed
/README.md          what this is, format, how to regenerate, how Penforge uses it
/tools/build.py     generator (reproducible from the pinned sources)
/tools/sources.json pinned sources: repository URL, tag, commit
```

`<manufacturer>` and `<printer>`/`<filament>` are lowercase ASCII slugs: letters, digits and `-` only
(umlauts transliterated, `+` → `plus`, everything else → `-`, repeated `-` collapsed). Example:
`printers/anycubic/kobra-s1-max-0-4.json`, `filaments/generic/pla.json`,
`filaments/bambu-lab/pla-basic.json`.

All JSON is UTF-8, pretty-printed with 2 spaces, keys sorted, trailing newline, so diffs stay small
and the generator output is byte-for-byte reproducible.

### index.json

```json
{
  "format": 1,
  "version": 7,
  "generated": "2026-11-20T10:00:00Z",
  "sources": [
    { "name": "OrcaSlicer", "repository": "https://github.com/SoftFever/OrcaSlicer",
      "tag": "v2.3.1", "commit": "<40 hex>", "path": "resources/profiles", "license": "AGPL-3.0" }
  ],
  "printers": [
    {
      "id": "anycubic/kobra-s1-max-0-4",
      "catalogID": 1234,
      "manufacturer": "Anycubic",
      "model": "Kobra S1 Max",
      "name": "Anycubic Kobra S1 Max 0.4 nozzle",
      "nozzle": 0.4,
      "path": "printers/anycubic/kobra-s1-max-0-4.json",
      "version": 2,
      "sha256": "<64 hex of the file bytes>",
      "bytes": 48213,
      "source": "OrcaSlicer"
    }
  ],
  "filaments": [
    {
      "id": "generic/pla",
      "manufacturer": "Generic",
      "name": "Generic PLA",
      "type": "PLA",
      "printers": [],
      "path": "filaments/generic/pla.json",
      "version": 1,
      "sha256": "<64 hex>",
      "bytes": 9120,
      "source": "OrcaSlicer"
    }
  ]
}
```

- `id`: stable identifier = path without `printers/`/`filaments/` and without `.json`. Never reused for
  something else.
- `catalogID` (optional): the numeric ID the same profile had in Penforge's previously bundled
  catalogue, so existing user profiles and projects that reference it keep resolving. Omitted for new
  entries. Process presets carry their own `catalogID` inside the printer file.
- `printers` on a filament: ids of printers that filament has variants for; empty = generic, any printer.
- `version` per entry: integer starting at 1, incremented by the generator whenever the file's bytes
  change (compared with the previous index.json in the repository). Unchanged files keep their version.
- `version` of the index: incremented whenever any entry is added, removed or changes version.
- `sha256` and `bytes` describe the exact file served, so the app verifies every download.

### printers/&lt;manufacturer&gt;/&lt;printer&gt;.json

One file per printer model and nozzle diameter, settings fully resolved (no `inherits`).

```json
{
  "format": 1,
  "id": "anycubic/kobra-s1-max-0-4",
  "manufacturer": "Anycubic",
  "model": "Kobra S1 Max",
  "name": "Anycubic Kobra S1 Max 0.4 nozzle",
  "nozzle": 0.4,
  "settingsFormat": "orca",
  "settings": { "printer_model": "Anycubic Kobra S1 Max", "nozzle_diameter": ["0.4"], "...": "..." },
  "processes": [
    {
      "name": "0.20mm Standard @Anycubic Kobra S1 Max 0.4 nozzle",
      "catalogID": 5678,
      "default": true,
      "settings": { "layer_height": "0.2", "...": "..." }
    }
  ],
  "source": { "name": "OrcaSlicer", "file": "resources/profiles/Anycubic/machine/Anycubic Kobra S1 Max 0.4 nozzle.json" }
}
```

- `settingsFormat`: `"orca"` (OrcaSlicer/Bambu Studio JSON keys and value encoding: strings and arrays of
  strings, exactly as the source after resolving inheritance) or `"prusa"` (PrusaSlicer INI keys, values
  as strings).
- `settings`: the machine profile, inheritance resolved, without `inherits`, `instantiation`,
  `setting_id`, `filament_ids`, and with `post_process` removed (Penforge never takes scripts from
  downloaded profiles).
- `processes`: every process preset compatible with this printer, resolved the same way. `default`
  marks the one the source vendor marks as default (or the most standard 0.20 mm preset).

### filaments/&lt;manufacturer&gt;/&lt;filament&gt;.json

One file per filament product; printer-specific variants inside.

```json
{
  "format": 1,
  "id": "generic/pla",
  "manufacturer": "Generic",
  "name": "Generic PLA",
  "type": "PLA",
  "settingsFormat": "orca",
  "settings": { "...": "fully resolved base profile" },
  "variants": [
    {
      "name": "Generic PLA @Anycubic Kobra S1 Max 0.4 nozzle",
      "catalogID": 9012,
      "printers": ["anycubic/kobra-s1-max-0-4"],
      "settings": { "nozzle_temperature": ["215"] }
    }
  ],
  "source": { "name": "OrcaSlicer", "file": "..." }
}
```

- `settings`: the base (printer-independent) profile, fully resolved. If the source has no generic base,
  the most common variant's resolved settings.
- `variants[].settings`: only keys whose resolved value differs from `settings`; the full profile of a
  variant is `settings` overlaid with `variants[].settings`.

### Incremental updates in the app

1. Fetch `index.json` (conditional request with ETag / If-Modified-Since). If its `version` equals the
   installed one, stop.
2. For each entry the user has installed: if `version` or `sha256` differs, download the new file into a
   staging folder and verify `sha256` and `bytes`. Nothing installed changes yet.
3. Tell the user that updates are available (a quiet notice, not a modal; a badge on the settings
   section). The update view lists each changed printer/filament with its version change and a diff:
   per profile (machine, each process, each filament variant) the settings that were added, removed
   or changed, old value → new value, using the app's own setting titles where it knows the key.
   Profiles added to or removed from a file show up as such.
4. The user installs all, some, or none. Installing moves the staged file into place atomically and
   records the new version; skipped updates stay offered until a newer version replaces them.
5. Entries not installed yet are downloaded on demand, when the user picks that printer or filament;
   that download installs directly (there is nothing to diff).
6. Entries removed from the index stay usable from the cache for profiles that already use them.

`index.json` also changes in place, so the app keeps the index it last installed next to the one it
just fetched; the listing of available printers/filaments uses the fetched one.

## Details and clarifications of format 1

These rules describe how the generator fills the format where the source data needs a decision.

- **One file per printer preset.** Normally that is one file per model and nozzle diameter. Where the source has
  several presets for the same model and nozzle (high-flow nozzles such as `HF0.4`, dual-extruder modes, Volcano
  hotends), each preset gets its own file. `id` comes from the preset name without the manufacturer prefix and
  without the word "nozzle".
- **Printer `catalogID`.** The previous catalogue numbered printer *models*; the app identified a printer by that
  number plus the nozzle diameter. Every nozzle variant of a model therefore carries the model's number. The pair
  (`catalogID`, `nozzle`) is unique.
- **Filament `catalogID` in index.json.** When a filament file's `settings` come from a printer-independent profile
  (OrcaSlicer's filament library, `… @System`), the index entry carries that profile's old number as `catalogID`.
  Variants carry their own.
- **Filament `printers` in index.json.** Empty when the product has a printer-independent profile, even if the
  file also has printer-specific variants: the filament fits any printer, and a printer listed in a variant uses
  that variant. Otherwise the union of the variants' printers.
- **`null` in `variants[].settings`.** The printer-independent profile can set keys that a printer-specific variant
  does not set at all (the vendors' own base profiles are older than the filament library). Such a key appears
  with the value `null`, which means *remove the key* when overlaying. Overlay rule: copy `settings`, then for each
  key of the variant set its value, or delete the key when the value is `null`.
- **Base of a product without a printer-independent profile.** The variant closest to the per-key majority of all
  variants (the most typical one), limited to the keys that every variant sets, so that overlaying reproduces every
  variant exactly without `null`. That variant is still listed under `variants`.
- **PrusaSlicer filaments** get the suffix `-prusaslicer` in their id (`filaments/generic/pla-prusaslicer.json`),
  because their settings are in PrusaSlicer format and must not collide with the OrcaSlicer product of the same
  name.
- **`default`** is present on every process, `true` on exactly one per printer.
- **`source`** of a PrusaSlicer profile names the INI bundle and its section:
  `{ "name": "PrusaSlicer-settings-prusa-fff", "file": "PrusaResearch/2.5.16.ini", "section": "printer:…" }`.
- **`sources[].tag`** is `null` for repositories without release tags (the PrusaSlicer-settings repositories); the
  `commit` pins them.
- **PrusaSlicer values** are stored as PrusaSlicer reads them: a single quoted string is unquoted and unescaped,
  other values are unescaped C-style (`\n` becomes a line break), and lists of quoted strings (`"a";"b"`) stay as
  written.

### Compatibility of processes and filaments

The slicers decide at runtime which presets fit a printer. The generator approximates that once:

- A process or vendor filament is matched only against the printers of its own vendor folder, as the slicers do for
  system presets. Filaments of OrcaSlicer's filament library are matched against every OrcaSlicer printer.
- A non-empty `compatible_printers` list wins; otherwise `compatible_printers_condition` is evaluated against the
  printer's resolved settings with an evaluator of the slicers' expression language (comparisons, `=~` regular
  expressions, `and`/`or`/`not`, indexed values such as `nozzle_diameter[0]`, missing keys as empty). A condition
  it cannot evaluate counts as compatible. With neither, the profile fits every printer of its vendor.
- `compatible_prints` and `compatible_prints_condition` (filament against process) are not evaluated.
- Presets on OrcaSlicer's `blacklist.json` are left out.
- From PrusaSlicer only printers that OrcaSlicer does not have are taken (for example the older Prusa i3 models,
  BIBO, Caribou), with their processes and filaments; the newest bundle of each vendor is used.
