#!/usr/bin/env python3
"""Generator for the Penforge profile catalogue (repository format 1).

Reads the pinned profile collections listed in tools/sources.json (checked out under .sources/), resolves
inheritance, regroups the profiles and writes index.json, printers/ and filaments/ as described in README.md.

Usage (from anywhere, Python 3.9+, standard library only):

    python3 -I tools/build.py --fetch      # clone/update the pinned sources into .sources/ (sparse, shallow)
    python3 -I tools/build.py              # generate the catalogue from .sources/
    python3 -I tools/build.py --verify     # check index.json against the files (sha256, bytes, no scripts)

    python3 -I tools/build.py --import-catalog <dir>
        one-time: read the numeric IDs of Penforge's previously bundled catalogue (index.json.z, profiles.json.z)
        and write tools/catalog-ids.json, which every build uses to set `catalogID`.

The output is deterministic: running the generator twice on the same sources gives byte-identical files and the
same versions. Versions are bumped against the index.json already in the repository.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
import zlib
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
FORMAT = 1

# Keys never written to a profile. `post_process` holds scripts the slicer runs after export; Penforge never takes
# scripts from downloaded profiles, so the generator removes them everywhere.
DROP_KEYS = {"inherits", "instantiation", "setting_id", "filament_ids", "post_process"}

# MARK: - Vendors and names

# Orca vendor folders that are not printer vendors (OrcaArena: the project's test printers; the filament library
# is read separately as the printer-independent base of all filaments)
ORCA_SKIP_VENDORS = {"OrcaArena", "OrcaFilamentLibrary"}
ORCA_LIBRARY = "OrcaFilamentLibrary"

# Display name per Orca vendor folder (default: the folder name)
VENDOR_NAMES = {"BBL": "Bambu Lab", "Qidi": "QIDI", "Ratrig": "RatRig", "Prusa": "Prusa Research", "Voron": "Voron Design",
                "Custom": "Generic", "UltiMaker": "UltiMaker", "Lulzbot": "LulzBot", "Tronxy": "Tronxy",
                "TwoTrees": "Two Trees", "re3D": "re3D", "iQ": "iQ", "LH": "LH", "M3D": "M3D"}

# PrusaSlicer vendors that OrcaSlicer already covers or that are not plastic FFF printers, and their display names
PS_SKIP_VENDORS = {"Templates", "CocoaPress", "Print4Taste", "QIDITechnology", "RatRig", "Snapmaker", "Anker", "Elegoo",
                   "Geeetech", "FLSun", "BIQU", "Positron3D"}
PS_VENDOR_NAMES = {"PrusaResearch": "Prusa Research", "Voron": "Voron Design", "Ultimaker": "UltiMaker",
                   "LulzBot": "LulzBot", "HartSmartProducts": "HartSmart Products", "PapapiuLab": "Papapiu Lab"}
# PrusaSlicer models that OrcaSlicer has under another name (normalised names, see ps_key)
PS_SKIP_MODELS = {("Voron", n) for n in ("2250mm", "2300mm", "2350mm", "trident250mm", "trident300mm",
                                         "trident350mm", "zero", "switchwire")} | {
    ("LulzBot", "taz6aero"), ("Anycubic", "4maxpro20"), ("Ultimaker", "2"),
}

# Filament brands (`filament_vendor`) spelled differently across vendors
BRAND_ALIASES = {"bbl": "Bambu Lab", "bambu": "Bambu Lab", "bambulab": "Bambu Lab", "esun": "eSUN", "sunlu": "SUNLU",
                 "polymaker": "Polymaker", "overture": "Overture", "jayo": "JAYO", "elegoo": "Elegoo",
                 "creality": "Creality", "anycubic": "Anycubic", "qidi": "QIDI", "flashforge": "Flashforge",
                 "sovol": "Sovol", "prusament": "Prusament", "generic": "Generic", "eryone": "Eryone",
                 "snapmaker": "Snapmaker", "fiberlogy": "Fiberlogy", "extrudr": "Extrudr", "colorfabb": "colorFabb",
                 "fillamentum": "Fillamentum", "dasfilament": "Das Filament"}
# Short forms of a brand that start product names ("Bambu PLA Basic" from "Bambu Lab")
BRAND_PREFIXES = {"Bambu Lab": ["Bambu Lab", "Bambu", "BBL"], "Prusa Research": ["Prusa Research", "Original Prusa", "Prusa"]}

# Suffix of filament ids whose settings are in PrusaSlicer format, so they never collide with an OrcaSlicer product
PRUSA_FILAMENT_SUFFIX = "-prusaslicer"


def slug(text):
    """Lowercase ASCII slug: umlauts transliterated, `+` → `plus`, everything else → `-`, repeats collapsed"""
    t = text
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("Ä", "Ae"), ("Ö", "Oe"), ("Ü", "Ue"), ("ß", "ss"), ("+", "plus")):
        t = t.replace(a, b)
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]", "-", t)).strip("-")


def strip_prefix(text, prefixes):
    """`text` without the longest of `prefixes` at its start (whole words, case-insensitive), if anything remains"""
    for p in sorted({p for p in prefixes if p}, key=len, reverse=True):
        if text.lower().startswith(p.lower()) and (len(text) == len(p) or not text[len(p)].isalnum()):
            rest = text[len(p):].strip(" -_")
            if rest:
                return rest
    return text


def first(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


def num(v):
    v = first(v)
    if v is None:
        return None
    try:
        return float(str(v).replace("%", "").split(",")[0].split(";")[0])
    except ValueError:
        return None


def strip_at(name):
    return re.sub(r"\s*@.*$", "", name).strip()


def brand_name(raw):
    key = re.sub(r"[^a-z0-9]", "", (raw or "").lower())
    return BRAND_ALIASES.get(key, (raw or "").strip() or "Generic")


def load_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def dumps(obj):
    """The one serialisation used for every file: UTF-8, 2-space indent, sorted keys, trailing newline"""
    return (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def clean(values):
    return {k: v for k, v in values.items() if k not in DROP_KEYS}


# MARK: - Conditions (`compatible_printers_condition`, e.g. `printer_notes=~/.*MK4.*/ and nozzle_diameter[0]==0.4`)

TOKEN = re.compile(r'\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<str>"(?:[^"\\]|\\.)*")|(?P<re>/(?:[^/\\]|\\.)*/)|'
                   r'(?P<op>==|!=|=~|!~|<=|>=|&&|\|\||[<>()!\[\]])|(?P<id>[A-Za-z_][A-Za-z_0-9]*))')
_TOKENS = {}


def tokens(text):
    if text not in _TOKENS:
        toks, pos, t = [], 0, text.strip()
        try:
            while pos < len(t):
                m = TOKEN.match(t, pos)
                if not m or m.end() == pos:
                    raise ValueError("bad token")
                pos = m.end()
                toks.append((m.lastgroup, m.group(m.lastgroup)))
        except ValueError:
            toks = None
        _TOKENS[text] = toks
    return _TOKENS[text]


class Cond:
    """Evaluator for the expression language of the slicers' compatibility conditions (the subset the profiles use)"""

    def __init__(self, toks, values):
        self.toks, self.i, self.values = toks, 0, values

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def parse(self):
        v = self.p_or()
        if self.i != len(self.toks):
            raise ValueError("trailing tokens")
        return v

    def p_or(self):
        v = self.p_and()
        while self.peek()[1] in ("or", "||"):
            self.take()
            r = self.p_and()
            v = truth(v) or truth(r)
        return v

    def p_and(self):
        v = self.p_not()
        while self.peek()[1] in ("and", "&&"):
            self.take()
            r = self.p_not()
            v = truth(v) and truth(r)
        return v

    def p_not(self):
        if self.peek()[1] in ("not", "!"):
            self.take()
            return not truth(self.p_not())
        return self.p_cmp()

    def p_cmp(self):
        a = self.p_atom()
        op = self.peek()[1]
        if op in ("==", "!=", "<", ">", "<=", ">="):
            self.take()
            b = self.p_atom()
            fa, fb = as_num(a), as_num(b)
            if fa is not None and fb is not None:
                a, b = fa, fb
            else:
                a, b = str(a), str(b)
            return {"==": a == b, "!=": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
        if op in ("=~", "!~"):
            self.take()
            kind, pat = self.take()
            if kind != "re":
                raise ValueError("regex expected")
            hit = re.fullmatch(pat[1:-1], str(a), re.S) is not None
            return hit if op == "=~" else not hit
        return a

    def p_atom(self):
        kind, t = self.take()
        if t == "(":
            v = self.p_or()
            if self.take()[1] != ")":
                raise ValueError(") expected")
            return v
        if kind == "num":
            return float(t)
        if kind == "str":
            return t[1:-1]
        if kind == "id":
            if t in ("true", "false"):
                return t == "true"
            v = self.values.get(t)
            idx, idx_given = 0, False
            if self.peek()[1] == "[":
                idx_given = True
                self.take()
                idx = int(float(self.take()[1]))
                self.take()
            if v is None:
                v = ""  # missing key: empty / 0, like an unset option in the slicers
            if isinstance(v, str) and "," in v and idx_given:
                v = [x.strip() for x in v.split(",")]
            if isinstance(v, list):
                v = v[idx] if idx < len(v) else (v[0] if v else "")
            return v
        raise ValueError("unexpected %r" % t)


def as_num(v):
    if isinstance(v, bool):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def truth(v):
    """Truth value as in the slicers: "0", "false" and empty text are false"""
    if isinstance(v, str):
        return v.strip().lower() not in ("", "0", "false", "0.0")
    return bool(v)


STATS = Counter()


def condition(text, values):
    """Result of a condition; None when it cannot be evaluated"""
    if not text or not text.strip():
        return True
    toks = tokens(text)
    if toks is None:
        return None
    try:
        return truth(Cond(toks, values).parse())
    except (ValueError, KeyError, IndexError, TypeError, re.error):
        return None


# MARK: - OrcaSlicer

class OrcaVendor:
    """One vendor folder of OrcaSlicer's resources/profiles: the profiles listed in `<vendor>.json`"""

    def __init__(self, root, folder, library=None, blacklist=None):
        self.folder = folder
        self.root = root
        self.prusa = False
        self.library = library
        self.models = {}
        self.raw = {"machine": {}, "process": {}, "filament": {}}
        self.files = {"machine": {}, "process": {}, "filament": {}}
        self.blacklist = blacklist or {}
        self._resolved = {}
        meta = load_json(os.path.join(root, folder + ".json"))
        base = os.path.join(root, folder)
        for entry in meta.get("machine_model_list", []):
            p = os.path.join(base, entry["sub_path"])
            if os.path.exists(p):
                j = load_json(p)
                self.models[j.get("name", entry["name"])] = j
        for kind, key in (("machine", "machine_list"), ("process", "process_list"), ("filament", "filament_list")):
            for entry in meta.get(key, []):
                p = os.path.join(base, entry["sub_path"])
                if not os.path.exists(p):
                    STATS["orca: listed file missing"] += 1
                    continue
                try:
                    j = load_json(p)
                except ValueError:
                    STATS["orca: unreadable JSON"] += 1
                    continue
                if j.get("type") != kind:
                    continue
                name = j.get("name", entry["name"])
                self.raw[kind][name] = j
                self.files[kind][name] = os.path.join(folder, entry["sub_path"])

    def lookup(self, kind, name):
        if name in self.raw[kind]:
            return self, self.raw[kind][name]
        if kind == "filament" and self.library is not None and name in self.library.raw["filament"]:
            return self.library, self.library.raw["filament"][name]
        return None, None

    def resolved(self, kind, name, seen=()):
        """Values of a profile with everything it inherits; the profile's own values win"""
        key = (kind, name)
        if key in self._resolved:
            return self._resolved[key]
        owner, j = self.lookup(kind, name)
        if j is None:
            return None
        if owner is not self:
            return owner.resolved(kind, name, seen)
        parent = (j.get("inherits") or "").strip()
        values = {}
        if parent and parent != name and parent not in seen:
            base = self.resolved(kind, parent, seen + (name,))
            if base is None:
                STATS["orca: unresolved parent"] += 1
                UNRESOLVED.add("%s/%s: %s -> %s" % (self.folder, kind, name, parent))
            else:
                values.update(base)
        values.update(j)
        self._resolved[key] = values
        return values

    def is_instance(self, kind, name):
        j = self.raw[kind][name]
        if str(j.get("instantiation", "true")).lower() != "true":
            return False
        if kind == "filament" and first(j.get("filament_id")) in self.blacklist.get("filament", ()):
            return False
        if kind == "process" and j.get("setting_id") in self.blacklist.get("process", ()):
            return False
        return True

    def source_file(self, kind, name):
        return "resources/profiles/" + self.files[kind][name]


UNRESOLVED = set()


# MARK: - PrusaSlicer

def ps_unescape(value):
    """An INI value as PrusaSlicer reads it: one quoted string is unquoted and unescaped, a list of quoted strings
    (`"a";"b"`) stays as written (the importer splits it), anything else is unescaped C-style (`\\n`, `\\r`)"""
    v = value.strip()
    if v.startswith('"'):
        m = re.fullmatch(r'"((?:[^"\\]|\\.)*)"', v)
        if not m:
            return v
        v = m.group(1)
    out, i = [], 0
    while i < len(v):
        c = v[i]
        if c == "\\" and i + 1 < len(v):
            n = v[i + 1]
            out.append({"n": "\n", "r": "\r"}.get(n, n))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def ps_version(f):
    try:
        return tuple(int(x) for x in f[:-4].split("-")[0].split("."))
    except ValueError:
        return (0,)


class PSVendor:
    """One vendor of a PrusaSlicer-settings repository (its newest `<version>.ini`)"""

    def __init__(self, repo_dir, vendor):
        self.name = vendor
        self.folder = "PS-" + vendor
        self.prusa = True
        self.raw = {"machine": {}, "process": {}, "filament": {}}
        self.models = {}
        self._resolved = {}
        path = os.path.join(repo_dir, vendor)
        inis = sorted([f for f in os.listdir(path) if f.endswith(".ini")], key=ps_version)
        self.ini = os.path.join(vendor, inis[-1]) if inis else None
        if not inis:
            return
        kinds = {"printer": "machine", "print": "process", "filament": "filament"}
        current = None
        with open(os.path.join(repo_dir, self.ini), encoding="utf-8", errors="replace") as f:
            for line in f:
                t = line.strip()
                if not t or t.startswith("#") or t.startswith(";"):
                    continue
                if t.startswith("[") and t.endswith("]"):
                    kind, _, sec = t[1:-1].partition(":")
                    if kind == "printer_model":
                        current = self.models.setdefault(sec, {"id": sec})
                    elif kind in kinds:
                        current = self.raw[kinds[kind]].setdefault(sec, {})
                    else:
                        current = None
                    continue
                if current is None or "=" not in t:
                    continue
                k, _, val = t.partition("=")
                current[k.strip()] = ps_unescape(val)

    @staticmethod
    def parents(j):
        return [x.strip().strip('"') for x in (j.get("inherits") or "").split(";") if x.strip().strip('"')]

    def resolved(self, kind, name, seen=()):
        """Values with all parents; PrusaSlicer applies several parents (`*common*; *PLA*`) in order, own values last"""
        if (kind, name) in self._resolved:
            return self._resolved[(kind, name)]
        j = self.raw[kind].get(name)
        if j is None:
            return None
        values = {}
        for parent in self.parents(j):
            if parent in seen or parent == name:
                continue
            base = self.resolved(kind, parent, seen + (name,))
            if base is None:
                STATS["prusa: unresolved parent"] += 1
                UNRESOLVED.add("%s/%s: %s -> %s" % (self.folder, kind, name, parent))
            else:
                values.update(base)
        values.update(j)
        values["name"] = name
        self._resolved[(kind, name)] = values
        return values

    def is_instance(self, kind, name):
        return not name.startswith("*")


def ps_key(vendor, name):
    """Comparable model name: without vendor, Original, Prusa, i3, Input Shaper and additions after && or /"""
    t = " " + name.lower() + " "
    t = re.split(r"&&|/", t)[0] + " "
    for w in ("original", "prusa", " i3 ", "input shaper", vendor.lower(), "creality", "anycubic", "artillery", "sovol",
              "voron", "ultimaker", "lulzbot"):
        if w.strip():
            t = t.replace(w, " ")
    return re.sub(r"[^a-z0-9]", "", t)


# MARK: - Sources

def load_sources():
    return load_json(os.path.join(TOOLS, "sources.json"))["sources"]


def git(args, cwd):
    return subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def fetch(sources_dir):
    """Sparse, shallow checkout of every pinned source at its commit"""
    os.makedirs(sources_dir, exist_ok=True)
    for s in load_sources():
        d = os.path.join(sources_dir, s["checkout"])
        if not os.path.isdir(os.path.join(d, ".git")):
            os.makedirs(d, exist_ok=True)
            git(["init", "-q"], d)
            git(["remote", "add", "origin", s["repository"]], d)
        git(["sparse-checkout", "set", "--no-cone"] + s["sparse"], d)
        git(["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", s["commit"]], d)
        git(["checkout", "-q", "--detach", s["commit"]], d)
        print("%s: %s" % (s["name"], git(["rev-parse", "HEAD"], d)))


def check_sources(sources_dir):
    for s in load_sources():
        d = os.path.join(sources_dir, s["checkout"])
        if not os.path.isdir(d):
            sys.exit("missing source %s: run tools/build.py --fetch" % d)
        head = git(["rev-parse", "HEAD"], d)
        if head != s["commit"]:
            sys.exit("%s is at %s, pinned is %s: run tools/build.py --fetch" % (d, head, s["commit"]))


# MARK: - Old catalogue IDs

def import_catalog(directory):
    """Numeric IDs of Penforge's previously bundled catalogue, keyed `<folder>/<profile name>` per kind"""
    def read(name):
        with open(os.path.join(directory, name), "rb") as f:
            return json.loads(zlib.decompress(f.read(), -15))
    ix, pr = read("index.json.z"), read("profiles.json.z")
    folders = [f[0] for f in ix["folders"]]
    out = {"printer": {}, "process": {}, "filament": {}}
    conflicts = []
    # A printer of the old catalogue is a model with its nozzle variants ([diameter, machine profile name]); the
    # same number goes to every variant. The app identifies a printer by number and nozzle diameter.
    for p in ix["printers"]:
        for _, variant in p[8]:
            key = "%s/%s" % (folders[p[1]], variant)
            if key in out["printer"] and out["printer"][key] != p[0]:
                conflicts.append((key, out["printer"][key], p[0]))
                continue
            out["printer"][key] = p[0]
    for kind, key in (("process", "processes"), ("filament", "filaments")):
        for e in pr[key]:
            out[kind]["%s/%s" % (folders[e[1]], e[2])] = e[0]
    with open(os.path.join(TOOLS, "catalog-ids.json"), "wb") as f:
        f.write(dumps(out))
    print("catalog-ids.json: %d printer variants, %d processes, %d filaments" % tuple(len(out[k]) for k in out))
    for c in conflicts:
        print("  kept %s for %s, dropped %s (same machine profile)" % (c[1], c[0], c[2]))


def load_catalog_ids():
    p = os.path.join(TOOLS, "catalog-ids.json")
    return load_json(p) if os.path.exists(p) else {"printer": {}, "process": {}, "filament": {}}


# MARK: - Build

def nozzle_of(values):
    n = num(values.get("nozzle_diameter"))
    return round(n, 2) if n else None


def printer_slug(name, manufacturer, folder):
    prefixes = [manufacturer, folder, manufacturer.split(" ")[0]] + BRAND_PREFIXES.get(manufacturer, [])
    rest = strip_prefix(name, prefixes)
    rest = re.sub(r"\bnozzle\b", " ", rest, flags=re.I)
    return slug(rest)


def product_slug(product, brand):
    prefixes = [brand, brand.split(" ")[0]] + BRAND_PREFIXES.get(brand, [])
    prefixes += [k for k, v in BRAND_ALIASES.items() if v == brand]
    return slug(strip_prefix(product, prefixes)) or slug(product)


def build(sources_dir, out_dir):
    check_sources(sources_dir)
    sources = load_sources()
    src = {s["name"]: s for s in sources}
    ids = load_catalog_ids()
    used_ids = Counter()

    def catalog_id(kind, key):
        i = ids[kind].get(key)
        if i is not None:
            used_ids[kind] += 1
        return i

    orca_name = "OrcaSlicer"
    orca_root = os.path.join(sources_dir, src[orca_name]["checkout"], src[orca_name]["path"])
    blacklist = load_json(os.path.join(orca_root, "blacklist.json")) if os.path.exists(os.path.join(orca_root, "blacklist.json")) else {}
    library = OrcaVendor(orca_root, ORCA_LIBRARY, blacklist=blacklist)
    vendors = []  # (vendor, source name)
    for folder in sorted(os.listdir(orca_root)):
        if folder in ORCA_SKIP_VENDORS or not os.path.isdir(os.path.join(orca_root, folder)):
            continue
        if not os.path.exists(os.path.join(orca_root, folder + ".json")):
            continue
        vendors.append((OrcaVendor(orca_root, folder, library, blacklist), orca_name))

    printers = []  # dicts, see below
    by_folder = defaultdict(list)

    def add_printer(v, source, name, values, manufacturer, model, cond_values, file_info):
        n = nozzle_of(values)
        if n is None:
            STATS["printer without nozzle diameter skipped"] += 1
            SKIPPED.append("no nozzle diameter: %s/%s" % (v.folder, name))
            return
        prefixes = [manufacturer, v.name if v.prusa else v.folder, manufacturer.split(" ")[0]] + BRAND_PREFIXES.get(manufacturer, [])
        p = {
            "vendor": v, "source": source, "machine": name, "manufacturer": manufacturer,
            "model": strip_prefix(model, prefixes), "printer_model": model,
            "nozzle": n, "values": values, "cond": cond_values, "file": file_info,
            "catalogID": catalog_id("printer", "%s/%s" % (v.folder, name)),
            "slug": printer_slug(name, manufacturer, v.folder if not v.prusa else v.name),
        }
        printers.append(p)
        by_folder[v.folder].append(p)

    # Orca printers: machine instances whose model is listed by the vendor
    for v, source in vendors:
        manufacturer = VENDOR_NAMES.get(v.folder, v.folder)
        for name in sorted(v.raw["machine"]):
            if not v.is_instance("machine", name):
                continue
            values = v.resolved("machine", name)
            model = (values.get("printer_model") or "").strip()
            if v.models and model not in v.models:
                STATS["orca: machine instance of an unlisted model skipped"] += 1
                SKIPPED.append("model %r not listed: %s/%s" % (model, v.folder, name))
                continue
            add_printer(v, source, name, values, manufacturer, model, values,
                        {"name": source, "file": v.source_file("machine", name)})

    # PrusaSlicer printers that OrcaSlicer does not have
    orca_keys = defaultdict(set)
    for p in printers:
        orca_keys[p["manufacturer"]].add(ps_key("", p["printer_model"]))
    for sname in ("PrusaSlicer-settings-prusa-fff", "PrusaSlicer-settings-non-prusa-fff"):
        repo = os.path.join(sources_dir, src[sname]["checkout"])
        for vfolder in sorted(os.listdir(repo)):
            path = os.path.join(repo, vfolder)
            if vfolder in PS_SKIP_VENDORS or vfolder.startswith(".") or not os.path.isdir(path):
                continue
            v = PSVendor(repo, vfolder)
            if not v.models:
                continue
            vendors.append((v, sname))
            manufacturer = PS_VENDOR_NAMES.get(vfolder, vfolder)
            known = orca_keys.get(manufacturer, set())
            for name in sorted(v.raw["machine"]):
                if not v.is_instance("machine", name):
                    continue
                values = v.resolved("machine", name)
                mid = values.get("printer_model", "")
                if mid not in v.models:
                    STATS["prusa: printer without a listed model skipped"] += 1
                    SKIPPED.append("model %r not listed: %s/%s" % (mid, v.folder, name))
                    continue
                if v.models[mid].get("technology", "FFF") != "FFF":
                    continue
                mname = v.models[mid].get("name", mid).replace(" && ", " / ").strip()
                key = ps_key(vfolder, mname)
                if key in known or (vfolder, key) in PS_SKIP_MODELS:
                    STATS["prusa: printer known to OrcaSlicer skipped"] += 1
                    continue
                cond = dict(values)
                cond["num_extruders"] = str(len(str(values.get("nozzle_diameter", "0.4")).split(",")))
                add_printer(v, sname, name, values, manufacturer, mname, cond,
                            {"name": sname, "file": v.ini, "section": "printer:" + name})

    # Ids: <manufacturer>/<printer>; a clash gets the full profile name, then the source format
    taken = {}
    for p in sorted(printers, key=lambda p: (p["source"] != orca_name, p["vendor"].folder, p["machine"])):
        base = slug(p["manufacturer"]) + "/" + p["slug"]
        pid = base
        if pid in taken:
            pid = slug(p["manufacturer"]) + "/" + slug(p["machine"])
        if pid in taken:
            pid = base + ("-prusaslicer" if p["vendor"].prusa else "-" + slug(p["vendor"].folder))
        n = 2
        while pid in taken:
            pid = "%s-%d" % (base, n)
            n += 1
        if pid != base:
            STATS["printer id clash resolved"] += 1
            CLASHES.append("%s (%s) -> %s" % (base, p["machine"], pid))
        taken[pid] = p
        p["id"] = pid

    # Compatibility within a vendor (as OrcaSlicer and PrusaSlicer do for system presets)
    cond_cache = {}

    def compatible(values, scope):
        """Printers a process or filament profile fits; None = no restriction"""
        listed = values.get("compatible_printers") or []
        if isinstance(listed, str):
            listed = re.findall(r'"([^"]*)"', listed) or listed.split(";")
        names = {str(x).strip() for x in listed if str(x).strip()}
        if names:
            return [p for p in scope if p["machine"] in names]
        cond = values.get("compatible_printers_condition") or ""
        if isinstance(cond, list):
            cond = cond[0] if cond else ""
        if not cond.strip():
            return None
        out = []
        for p in scope:
            k = (cond, p["id"])
            if k not in cond_cache:
                r = condition(cond, p["cond"])
                if r is None:
                    STATS["condition not evaluable (treated as compatible)"] += 1
                    UNEVALUABLE.add(cond[:160])
                cond_cache[k] = r is None or r
            if cond_cache[k]:
                out.append(p)
        return out

    # Processes
    for p in printers:
        p["processes"] = []
    for v, source in vendors:
        scope = by_folder.get(v.folder, [])
        if not scope:
            continue
        for name in sorted(v.raw["process"]):
            if not v.is_instance("process", name):
                continue
            values = v.resolved("process", name)
            fits = compatible(values, scope)
            if fits is None:
                fits = scope
            if not fits:
                STATS["process without a compatible printer"] += 1
                continue
            entry = {"name": name, "settings": clean(values), "catalogID": catalog_id("process", "%s/%s" % (v.folder, name))}
            STATS["process profiles"] += 1
            for p in fits:
                p["processes"].append(entry)

    # Filaments: profiles from each vendor for its printers, the Orca filament library for every printer
    instances = []  # (vendor, source, name, values, fits or None)
    for v, source in vendors:
        scope = by_folder.get(v.folder, [])
        if not scope:
            continue
        for name in sorted(v.raw["filament"]):
            if not v.is_instance("filament", name):
                continue
            values = v.resolved("filament", name)
            fits = compatible(values, scope)
            if fits is None:
                fits = scope
            if not fits:
                STATS["filament without a compatible printer"] += 1
                continue
            instances.append((v, source, name, values, fits))
    orca_printers = [p for p in printers if not p["vendor"].prusa]
    for name in sorted(library.raw["filament"]):
        if not library.is_instance("filament", name):
            continue
        values = library.resolved("filament", name)
        fits = compatible(values, orca_printers)
        if fits is not None and not fits:
            continue
        instances.append((library, orca_name, name, values, fits))

    groups = defaultdict(list)
    for inst in instances:
        v, source, name, values, fits = inst
        brand = brand_name(first(values.get("filament_vendor")))
        product = strip_at(name) or name
        # Brands spelled differently ("Devil Design", "DevilDesign") group together; the id uses the common spelling
        key = (v.prusa, re.sub(r"[^a-z0-9]", "", slug(brand)) or "generic",
               product_slug(product, brand) + (PRUSA_FILAMENT_SUFFIX if v.prusa else ""))
        groups[key].append((brand, product) + inst)

    # One spelling per brand across both formats: the most common one
    spellings = defaultdict(Counter)
    for key, members in groups.items():
        for m in members:
            spellings[key[1]][m[0]] += 1
    brand_display = {k: sorted(c.items(), key=lambda x: (-x[1], x[0]))[0][0] for k, c in spellings.items()}

    filaments = []
    for key in sorted(groups):
        prusa, bslug, pslug = key
        members = groups[key]
        brand = brand_display[bslug]
        product = sorted(Counter(m[1] for m in members).items(), key=lambda x: (-x[1], x[0]))[0][0]
        universal = [m for m in members if m[6] is None]
        variants = [m for m in members if m[6] is not None]
        if len(universal) > 1:
            STATS["filament product with several printer-independent profiles"] += 1
            # keep the first as base, the others become variants for every printer of the source
            for m in universal[1:]:
                variants.append(m[:6] + (orca_printers,))
            universal = universal[:1]
        f = {"id": "%s/%s" % (slug(brand) or "generic", pslug), "manufacturer": brand, "name": product, "prusa": prusa,
             "source_name": members[0][3]}
        variant_values = [clean(m[5]) for m in variants]
        if universal:
            u = universal[0]
            f["base"] = clean(u[5])
            f["base_file"] = {"name": u[3], "file": u[2].source_file("filament", u[4])}
            f["catalogID"] = catalog_id("filament", "%s/%s" % (u[2].folder, u[4]))
            f["generic"] = True
        else:
            # No printer-independent profile: the most typical variant (closest to the per-key majority) is the base
            consensus = {}
            counts = defaultdict(Counter)
            for vals in variant_values:
                for k, x in vals.items():
                    counts[k][json.dumps(x, sort_keys=True)] += 1
            for k, c in counts.items():
                consensus[k] = sorted(c.items(), key=lambda x: (-x[1], x[0]))[0][0]

            def distance(vals):
                d = sum(1 for k, x in vals.items() if consensus.get(k) != json.dumps(x, sort_keys=True))
                return d + sum(1 for k in consensus if k not in vals)
            best = min(range(len(variants)), key=lambda i: (distance(variant_values[i]), variants[i][4], variants[i][2].folder))
            m = variants[best]
            # Only keys every variant has, so that base + variant overlay gives each variant exactly
            shared = set.intersection(*(set(vals) for vals in variant_values))
            f["base"] = {k: x for k, x in variant_values[best].items() if k in shared}
            if m[2].prusa:
                f["base_file"] = {"name": m[3], "file": m[2].ini, "section": "filament:" + m[4]}
            else:
                f["base_file"] = {"name": m[3], "file": m[2].source_file("filament", m[4])}
            f["generic"] = False
        f["type"] = first(f["base"].get("filament_type")) or "PLA"
        out_variants = []
        for m, vals in zip(variants, variant_values):
            v, source, name, values, fits = m[2:]
            diff = {k: x for k, x in vals.items() if f["base"].get(k, None) != x or k not in f["base"]}
            lost = [k for k in f["base"] if k not in vals]
            # A key the printer-independent profile sets but this variant does not: null removes it on overlay
            for k in lost:
                diff[k] = None
            if lost:
                STATS["variant keys removed with null"] += len(lost)
                for k in lost:
                    LOST[k] += 1
                    LOST_FILES[f["id"]] += 1
            out_variants.append({
                "name": name,
                "catalogID": catalog_id("filament", "%s/%s" % (v.folder, name)),
                "printers": sorted({p["id"] for p in fits}),
                "settings": diff,
            })
        out_variants.sort(key=lambda x: (x["name"], x["printers"], json.dumps(x["settings"], sort_keys=True)))
        f["variants"] = out_variants
        filaments.append(f)

    dup = [i for i, c in Counter(f["id"] for f in filaments).items() if c > 1]
    assert not dup, "duplicate filament ids: %s" % dup[:5]

    # Default process per printer: the vendor's default, else the most standard preset for the nozzle
    def default_process(p):
        names = [e["name"] for e in p["processes"]]
        if not names:
            return None
        d = (first(p["values"].get("default_print_profile")) or "").strip()
        if d in names:
            return d
        STATS["default process chosen by layer height"] += 1
        target = 0.2 if abs(p["nozzle"] - 0.4) < 1e-6 else max(0.08, min(0.4, p["nozzle"] / 2))

        def score(e):
            lh = num(e["settings"].get("layer_height")) or 0
            n = e["name"].lower()
            return (round(abs(lh - target), 4), 0 if ("standard" in n or "normal" in n) else 1, len(n), e["name"])
        return min(p["processes"], key=score)["name"]

    # MARK: Write
    files = {}  # path -> (bytes, entry)
    index_printers, index_filaments = [], []
    for p in sorted(printers, key=lambda p: p["id"]):
        dflt = default_process(p)
        procs = []
        for e in sorted(p["processes"], key=lambda e: e["name"]):
            x = {"name": e["name"], "default": e["name"] == dflt, "settings": e["settings"]}
            if e["catalogID"] is not None:
                x["catalogID"] = e["catalogID"]
            procs.append(x)
        doc = {
            "format": FORMAT, "id": p["id"], "manufacturer": p["manufacturer"], "model": p["model"], "name": p["machine"],
            "nozzle": p["nozzle"], "settingsFormat": "prusa" if p["vendor"].prusa else "orca",
            "settings": clean(p["values"]), "processes": procs, "source": p["file"],
        }
        path = "printers/%s.json" % p["id"]
        data = dumps(doc)
        entry = {"id": p["id"], "manufacturer": p["manufacturer"], "model": p["model"], "name": p["machine"],
                 "nozzle": p["nozzle"], "path": path, "source": p["source"]}
        if p["catalogID"] is not None:
            entry["catalogID"] = p["catalogID"]
        files[path] = data
        index_printers.append(entry)
    for f in sorted(filaments, key=lambda f: f["id"]):
        printers_of = sorted({i for v in f["variants"] for i in v["printers"]}) if not f["generic"] else []
        variants = []
        for v in f["variants"]:
            x = {"name": v["name"], "printers": v["printers"], "settings": v["settings"]}
            if v["catalogID"] is not None:
                x["catalogID"] = v["catalogID"]
            variants.append(x)
        doc = {
            "format": FORMAT, "id": f["id"], "manufacturer": f["manufacturer"], "name": f["name"], "type": f["type"],
            "settingsFormat": "prusa" if f["prusa"] else "orca", "settings": f["base"], "variants": variants,
            "source": f["base_file"],
        }
        path = "filaments/%s.json" % f["id"]
        files[path] = dumps(doc)
        entry = {"id": f["id"], "manufacturer": f["manufacturer"], "name": f["name"], "type": f["type"],
                 "printers": printers_of, "path": path, "source": f["source_name"]}
        if f.get("catalogID") is not None:
            entry["catalogID"] = f["catalogID"]
        index_filaments.append(entry)

    # Versions against the index.json already in the repository
    index_path = os.path.join(out_dir, "index.json")
    prev = load_json(index_path) if os.path.exists(index_path) else {}
    prev_entries = {e["path"]: e for e in prev.get("printers", []) + prev.get("filaments", [])}
    changed = False
    for entry in index_printers + index_filaments:
        data = files[entry["path"]]
        entry["sha256"] = hashlib.sha256(data).hexdigest()
        entry["bytes"] = len(data)
        old = prev_entries.get(entry["path"])
        if old is None:
            entry["version"] = 1
            changed = True
        elif old.get("sha256") == entry["sha256"]:
            entry["version"] = old.get("version", 1)
        else:
            entry["version"] = old.get("version", 0) + 1
            changed = True
    if set(prev_entries) - set(files):
        changed = True
    index_sources = [{k: s[k] for k in ("name", "repository", "tag", "commit", "path", "license")} for s in sources]
    if prev.get("sources") != index_sources:
        changed = True
    if changed or not prev:
        version = prev.get("version", 0) + 1
        generated = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        version, generated = prev["version"], prev["generated"]
    index = {"format": FORMAT, "version": version, "generated": generated, "sources": index_sources,
             "printers": index_printers, "filaments": index_filaments}

    # Write only what changed, remove files of entries that are gone
    written = 0
    for path, data in files.items():
        full = os.path.join(out_dir, path)
        if os.path.exists(full):
            with open(full, "rb") as fh:
                if fh.read() == data:
                    continue
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(data)
        written += 1
    removed = 0
    for top in ("printers", "filaments"):
        for dirpath, _, names in os.walk(os.path.join(out_dir, top), topdown=False):
            for n in names:
                rel = os.path.relpath(os.path.join(dirpath, n), out_dir).replace(os.sep, "/")
                if rel not in files:
                    os.remove(os.path.join(dirpath, n))
                    removed += 1
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
    with open(index_path, "wb") as fh:
        fh.write(dumps(index))

    # Report
    nvariants = sum(len(f["variants"]) for f in filaments)
    print("index version %d (%s)" % (version, "changed" if changed else "unchanged"))
    print("printers %d, process presets %d (attached %d times), filament files %d, variants %d" % (
        len(index_printers), STATS["process profiles"], sum(len(p["processes"]) for p in printers), len(index_filaments),
        nvariants))
    print("written %d, removed %d, total %.1f MB" % (written, removed, sum(len(d) for d in files.values()) / 1e6))
    print("catalogID: printers %d of %d files, processes %d presets, filaments %d (of %d old printer variants, %d processes, %d filaments)" % (
        used_ids["printer"], len(index_printers), used_ids["process"], used_ids["filament"],
        len(ids["printer"]), len(ids["process"]), len(ids["filament"])))
    for k in sorted(STATS):
        print("  %s: %d" % (k, STATS[k]))
    if UNRESOLVED:
        print("unresolved parents (%d):" % len(UNRESOLVED))
        for u in sorted(UNRESOLVED)[:40]:
            print("  " + u)
    if LOST and os.environ.get("PROFILES_DEBUG"):
        print("keys only in the base:", LOST.most_common(25))
        print("files:", LOST_FILES.most_common(15))
    for x in SKIPPED:
        print("skipped printer, " + x)
    if CLASHES:
        print("id clashes (%d):" % len(CLASHES))
        for c in CLASHES[:40]:
            print("  " + c)
    if UNEVALUABLE:
        print("conditions not evaluable (%d):" % len(UNEVALUABLE))
        for c in sorted(UNEVALUABLE)[:20]:
            print("  " + c)
    return index


CLASHES = []
UNEVALUABLE = set()
LOST = Counter()
SKIPPED = []
LOST_FILES = Counter()


def verify(out_dir):
    index = load_json(os.path.join(out_dir, "index.json"))
    errors = 0
    seen = set()
    for kind in ("printers", "filaments"):
        for e in index[kind]:
            full = os.path.join(out_dir, e["path"])
            seen.add(e["path"])
            if not os.path.exists(full):
                print("missing %s" % e["path"])
                errors += 1
                continue
            with open(full, "rb") as fh:
                data = fh.read()
            if hashlib.sha256(data).hexdigest() != e["sha256"] or len(data) != e["bytes"]:
                print("sha256/bytes mismatch %s" % e["path"])
                errors += 1
            if b'"post_process"' in data:
                print("post_process in %s" % e["path"])
                errors += 1
            doc = json.loads(data)
            if doc.get("id") != e["id"] or "printers/%s.json" % e["id"] != e["path"] and "filaments/%s.json" % e["id"] != e["path"]:
                print("id/path mismatch %s" % e["path"])
                errors += 1
            if dumps(doc) != data:
                print("not canonical JSON %s" % e["path"])
                errors += 1
    for top in ("printers", "filaments"):
        for dirpath, _, names in os.walk(os.path.join(out_dir, top)):
            for n in names:
                rel = os.path.relpath(os.path.join(dirpath, n), out_dir).replace(os.sep, "/")
                if rel not in seen:
                    print("file not in index: %s" % rel)
                    errors += 1
    print("verified %d printers, %d filaments, %d errors" % (len(index["printers"]), len(index["filaments"]), errors))
    return errors


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sources", default=os.path.join(ROOT, ".sources"), help="checkout folder of the pinned sources")
    ap.add_argument("--out", default=ROOT, help="repository root to write into")
    ap.add_argument("--fetch", action="store_true", help="clone or update the pinned sources, then stop")
    ap.add_argument("--verify", action="store_true", help="check index.json against the files, then stop")
    ap.add_argument("--import-catalog", metavar="DIR", help="write tools/catalog-ids.json from an old bundled catalogue")
    a = ap.parse_args()
    if a.fetch:
        fetch(a.sources)
        return
    if a.import_catalog:
        import_catalog(a.import_catalog)
        return
    if a.verify:
        sys.exit(1 if verify(a.out) else 0)
    build(a.sources, a.out)


if __name__ == "__main__":
    main()
