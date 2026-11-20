# Notice

This repository contains printer, process and filament profiles derived from the profile collections listed below.
The derived data is distributed under the GNU Affero General Public License, version 3 (see [LICENSE](LICENSE)),
the licence of the sources. The generator in `tools/` is part of this repository and under the same licence.

## Sources

The exact revisions are pinned in `tools/sources.json` and repeated in `sources` of `index.json`. Every generated
file names the upstream file (and for PrusaSlicer the INI section) it starts from in `source`.

### OrcaSlicer

- Repository: https://github.com/OrcaSlicer/OrcaSlicer (formerly SoftFever/OrcaSlicer)
- Revision: tag `v2.5.1`, commit `eef7710cb102fdb51a9bcdbd9efd61047f44774a`
- Path: `resources/profiles` (vendor folders and the OrcaFilamentLibrary)
- Licence: GNU Affero General Public License, version 3 (`LICENSE.txt` in the repository)
- Copyright: the OrcaSlicer authors and contributors (project by SoftFever). OrcaSlicer is based on Bambu Studio by
  Bambu Lab, which is based on PrusaSlicer by Prusa Research, which is based on Slic3r by Alessandro Ranellucci and
  the RepRap community. The vendor profiles were contributed by printer and filament manufacturers and the
  OrcaSlicer community.

### PrusaSlicer settings

- Repositories:
  - https://github.com/prusa3d/PrusaSlicer-settings-prusa-fff, commit `0f0548d5fa09add2c105136c4d421205767d98ee`
    (branch `main`, no release tags)
  - https://github.com/prusa3d/PrusaSlicer-settings-non-prusa-fff, commit `a01e756eceadc4d7b47e56f7296f00e4dd6b85bf`
    (branch `main`, no release tags)
- Path: `<vendor>/<version>.ini`; the generator uses the newest bundle of each vendor.
- Licence: GNU Affero General Public License, version 3. The two repositories carry no licence file of their own;
  they are the profile repositories of PrusaSlicer (AGPL-3.0), whose source tree ships the same bundles in
  `resources/profiles`, and they succeed https://github.com/prusa3d/PrusaSlicer-settings, which is licensed under
  AGPL-3.0.
- Copyright: Prusa Research a.s. and the contributors of the vendor bundles. Several bundles name their authors in
  comments at the top of the INI file (for example Caribou Research & Development, Geeetech, and individual
  contributors on GitHub); these comments are not settings and are not copied into the generated files, see the
  bundle named in each file's `source`.

## What the generator changes

- **Inheritance resolved.** Every profile is written with all values it inherits (OrcaSlicer: the `inherits` chain
  within the vendor folder and from the OrcaFilamentLibrary and its `fdm_*_common` bases; PrusaSlicer: the INI
  `inherits` list with several parents in order). The keys `inherits`, `instantiation`, `setting_id` and
  `filament_ids` are removed.
- **Scripts removed.** `post_process` (commands a slicer runs after export) is removed from every profile.
- **Regrouped.** Each printer preset becomes one file with the process presets compatible with it. Filament
  presets are grouped by product (brand and name without the `@…` suffix) into one file per product: a base
  profile plus printer-specific variants that store only the settings that differ. The compatibility of processes
  and filaments is evaluated once by the generator (see README.md, "Compatibility of processes and filaments").
- **Selection.** Abstract base profiles do not become files. OrcaArena (test printers) and presets on OrcaSlicer's
  `blacklist.json` are left out. From PrusaSlicer only printers that OrcaSlicer does not have are taken; the
  vendors Templates, CocoaPress, Print4Taste, QIDITechnology, RatRig, Snapmaker, Anker, Elegoo, Geeetech, FLSun,
  BIQU and Positron3D are left out because OrcaSlicer covers them or they are not plastic FFF printers.
- **Values otherwise unchanged.** Settings keep the keys and value encoding of their source (OrcaSlicer JSON
  strings and string arrays; PrusaSlicer INI values as strings, unescaped as PrusaSlicer reads them).
- **Added metadata.** Ids, display names, nozzle diameters, versions, checksums and `catalogID` numbers from
  Penforge's previously bundled catalogue.
