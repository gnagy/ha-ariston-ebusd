#!/usr/bin/env python3
"""Check that the ebusd rows and the Home Assistant control packages agree with each other.

  check-controls.py --csv DIR --packages DIR --cfg FILE [-v]

Reads every *.csv in --csv (ebusd's configuration folder), every *.yaml in --packages (the folder holding the
ariston_*.yaml packages) and the filter-circuit line of --cfg (mqtt-hassio.cfg). The paths are given, not assumed,
so it runs on any layout. Prints one line per finding and exits 1 on any ERROR.
Nothing is sent to the instance. Design: docs/design.md.

  1  every command topic ebusd/<circuit>/<name>/set has a w row, and every w row in cmd has a user
  2  every other topic of an entity resolves to a readable row (m, u, b or r) or is ebusd/global/running
  3  number min, max and step are representable by the row's type and divider, and inside the type's range
  4  what an entity publishes (payload_on/off, command templates) exists in the row's value list
  5  unique_id and default_entity_id are unique across all packages, and the domain fits the platform
  6  w rows are 2020 broadcasts to fe with a 2-byte id; type and divider agree with other rows of the same id
  7  an automation re-reads after every set, and each command has an r row in the circuit its name prefix gives
  8  no circuit/name is defined twice with the same kind of row
  9  the cmd circuit is not matched by filter-circuit, so ebusd never announces it

Needs Python 3.10+ and PyYAML (pip install pyyaml). In this repo:
  python3 tools/check-controls.py --csv ebusd/configuration --packages homeassistant/packages --cfg ebusd/mqtt-hassio.cfg
"""

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit('PyYAML is missing. Run with hass-ops\'s interpreter: $(head -1 "$(which hass-ops)" | cut -c3-) ' + sys.argv[0])

AVAILABILITY = "ebusd/global/running"
# type: (bytes, lowest raw value, highest raw value); the top or bottom code of each type is its replacement value
TYPES = {
    "UCH": (1, 0, 254), "SCH": (1, -127, 127), "UIN": (2, 0, 65534), "SIN": (2, -32767, 32767),
    "ULG": (4, 0, 4294967294), "SLG": (4, -2147483647, 2147483647),
}
PLATFORM_DOMAIN = {"number": "number", "switch": "switch", "climate": "climate", "water_heater": "water_heater",
                   "sensor": "sensor", "binary_sensor": "binary_sensor", "select": "select"}


class Loader(yaml.SafeLoader):
    pass


Loader.add_multi_constructor("!", lambda loader, suffix, node: loader.construct_scalar(node)
                             if isinstance(node, yaml.ScalarNode) else None)


class Row:
    def __init__(self, path, line, f):
        t = f[0]
        self.kind = "w" if t.startswith("w") else "r" if t.startswith("r") else "p"
        self.circuit, self.name, self.zz, self.pbsb, self.ident = f[1], f[2], f[5].lower(), f[6].lower(), f[7].lower()
        self.where = f"{path.name}:{line}"
        self.ftype, self.divisor, self.values, self.lead_ign = None, None, None, False
        self.lead_ign = len(f) > 10 and f[10].startswith("IGN")
        i = 8
        while i + 3 < len(f):
            if f[i + 2] and not f[i + 2].startswith("IGN"):
                self.ftype = f[i + 2]
                dv = f[i + 3]
                if "=" in dv:
                    self.values = {p.split("=")[0]: p.split("=", 1)[1] for p in dv.split(";") if "=" in p}
                    self.values = {v: k for k, v in self.values.items()}  # name -> number
                elif re.fullmatch(r"-?\d+", dv):
                    self.divisor = int(dv)
                elif not dv:
                    self.divisor = 1
                break
            i += 6


def read_rows(csv_dir):
    rows = []
    for path in sorted(Path(csv_dir).glob("*.csv")):
        if path.name.startswith("_"):
            continue
        with path.open(encoding="utf-8") as fh:
            for n, f in enumerate(csv.reader(fh), 1):
                if f and not f[0].startswith(("#", "*")) and len(f) >= 8:
                    rows.append(Row(path, n, f))
    return rows


def read_packages(pkg_dir):
    """Entities (mqtt platforms and template sensors) and automations, each tagged with its file."""
    ents, autos = [], []
    for path in sorted(Path(pkg_dir).glob("*.yaml")):
        doc = yaml.load(path.read_text(encoding="utf-8"), Loader=Loader) or {}
        for platform, lst in (doc.get("mqtt") or {}).items():
            for e in lst or []:
                ents.append((path.name, platform, e))
        tpl = doc.get("template") or []
        for item in tpl if isinstance(tpl, list) else [tpl]:
            for plat in ("sensor", "binary_sensor"):
                for e in item.get(plat) or []:
                    ents.append((path.name, "template." + plat, e))
        for a in doc.get("automation") or []:
            autos.append((path.name, a))
    return ents, autos


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument("--packages", required=True, type=Path)
    ap.add_argument("--cfg", required=True, type=Path)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    rows = read_rows(args.csv)
    ents, autos = read_packages(args.packages)
    out = []

    def err(where, msg): out.append(("ERROR", where, msg))
    def warn(where, msg): out.append(("WARN", where, msg))

    by = defaultdict(list)
    for r in rows:
        by[(r.circuit, r.name, r.kind)].append(r)

    # 8
    for (circuit, name, kind), lst in by.items():
        if len(lst) > 1:
            (err if kind != "p" else warn)(lst[0].where, f"{circuit}/{name}: {len(lst)} rows of kind {kind} ({', '.join(r.where for r in lst)})")

    used_cmd = set()
    published = defaultdict(set)
    for pkg, platform, e in ents:
        who = f"{pkg} '{e.get('name', '?')}'"
        if platform.startswith("template."):
            continue
        for key, topic in e.items():
            if not (isinstance(topic, str) and key.endswith("_topic") or key == "topic"):
                continue
            if key.endswith("command_topic"):  # 1
                m = re.fullmatch(r"ebusd/([^/]+)/([^/]+)/set", topic)
                if not m:
                    err(who, f"{key} {topic!r} is not ebusd/<circuit>/<name>/set")
                    continue
                circuit, name = m.groups()
                w = by.get((circuit, name, "w"))
                if not w:
                    err(who, f"{key} {topic}: no w row for {circuit}/{name}")
                    continue
                if circuit != "cmd":
                    warn(who, f"{key} writes outside the cmd circuit ({circuit}/{name})")
                used_cmd.add((circuit, name))
                row = w[0]
                if platform == "number":  # 3
                    check_number(e, row, who, err, warn)
                tokens = publishes(e, key)  # 4
                if row.values:
                    for tok in tokens:
                        if tok not in row.values:
                            err(who, f"publishes {tok!r}, but {row.where} allows only {sorted(row.values)}")
                published[(circuit, name)].add(who)
            elif key == "availability_topic":
                if topic != AVAILABILITY:
                    warn(who, f"availability_topic {topic!r} is not {AVAILABILITY}")
            else:  # 2
                if topic == AVAILABILITY:
                    continue
                m = re.fullmatch(r"ebusd/([^/]+)/([^/]+)", topic)
                if not m:
                    err(who, f"{key} {topic!r} is not ebusd/<circuit>/<name>")
                elif not (by.get((m[1], m[2], "p")) or by.get((m[1], m[2], "r"))):
                    err(who, f"{key} {topic}: no readable (m, u, b or r) row for {m[1]}/{m[2]}")
    for (circuit, name, kind), lst in by.items():
        if circuit == "cmd" and kind == "w" and (circuit, name) not in used_cmd:
            warn(lst[0].where, f"cmd/{name} is written by no entity")

    # 5
    seen = {"unique_id": {}, "default_entity_id": {}}
    for pkg, platform, e in ents:
        who = f"{pkg} '{e.get('name', '?')}'"
        for k in seen:
            v = e.get(k)
            if v:
                if v in seen[k]:
                    err(who, f"{k} {v} also in {seen[k][v]}")
                seen[k][v] = who
        dom = e.get("default_entity_id", "").split(".")[0] if e.get("default_entity_id") else None
        if dom and platform in PLATFORM_DOMAIN and dom != PLATFORM_DOMAIN[platform]:
            err(who, f"default_entity_id {e['default_entity_id']} does not fit platform {platform}")
        if platform in ("number", "switch", "water_heater", "select") and not e.get("unique_id"):
            err(who, "no unique_id")

    # 6
    by_id = defaultdict(list)
    for r in rows:
        by_id[r.ident].append(r)
    for r in rows:
        if r.circuit == "cmd" and r.kind == "w":
            if r.pbsb != "2020":
                err(r.where, f"{r.name}: write row is not 2020 (PBSB {r.pbsb})")
            if r.zz != "fe":
                warn(r.where, f"{r.name}: write row is not a broadcast to fe (ZZ {r.zz})")
            if not re.fullmatch(r"[0-9a-f]{4}", r.ident):
                err(r.where, f"{r.name}: id {r.ident!r} is not 2 bytes")
            for o in by_id.get(r.ident, []):
                if o is not r and o.ftype and r.ftype and not o.lead_ign and (o.ftype, o.divisor) != (r.ftype, r.divisor):
                    warn(r.where, f"{r.name}: {r.ftype}/{r.divisor} but {o.where} reads {o.ident} as {o.ftype}/{o.divisor}")

    # 7  the re-read: an automation triggers on every set, and each command used has an r row in the circuit its name
    #    prefix gives (z1_... ariston_z1, z2_... ariston_z2, anything else ariston), as ariston_boiler.yaml derives it
    def triggers_on_set(auto):
        return any(isinstance(tr, dict) and tr.get("topic") == "ebusd/cmd/+/set" for tr in auto.get("triggers") or [])
    rereads = any(triggers_on_set(auto) for _, auto in autos)
    for circuit, n in sorted(used_cmd):
        prefix = n.split("_")[0]
        target = f"ariston_{prefix}" if re.fullmatch(r"z\d+", prefix) else "ariston"
        if not rereads:
            warn(f"cmd/{n}", "no re-read after a set: its entity shows the old value until the next broadcast or dump")
        elif not by.get((target, n, "r")):
            err(f"cmd/{n}", f"is re-read from {target}/{n}, but there is no r row for it")

    # 9
    for line in Path(args.cfg).read_text(encoding="utf-8").splitlines():
        mm = re.match(r"filter-circuit\s*=\s*(.*)$", line)
        if mm and any(r.circuit == "cmd" for r in rows) and re.search(mm.group(1).strip(), "cmd", re.I):
            err(Path(args.cfg).name, f"filter-circuit {mm.group(1).strip()!r} matches cmd, so its rows would be announced")

    counts = Counter(level for level, _, _ in out)
    for level, where, msg in out:
        print(f"{level:5} {where}: {msg}")
    ncmd = sum(1 for r in rows if r.circuit == "cmd" and r.kind == "w")
    print(f"{len(rows)} rows ({ncmd} in cmd), {len(ents)} entities, {len(autos)} automations: "
          f"{counts['ERROR']} errors, {counts['WARN']} warnings")
    sys.exit(1 if counts["ERROR"] else 0)


def check_number(e, row, who, err, warn):
    t = TYPES.get((row.ftype or "").upper())
    if not t or not row.divisor:
        warn(who, f"number on {row.where}: type {row.ftype}/{row.divisor} is not checked")
        return
    size, lo, hi = t
    for k in ("min", "max", "step"):
        v = e.get(k)
        if v is None:
            err(who, f"number has no {k}")
            continue
        raw = v * row.divisor
        if abs(raw - round(raw)) > 1e-6:
            err(who, f"{k} {v} is not a multiple of 1/{row.divisor} ({row.ftype} ÷ {row.divisor} at {row.where})")
        elif k != "step" and not lo <= round(raw) <= hi:
            err(who, f"{k} {v} is outside {row.ftype} ÷ {row.divisor} ({lo / row.divisor} to {hi / row.divisor})")
    if e.get("min") is not None and e.get("max") is not None and e.get("step"):
        n = (e["max"] - e["min"]) / e["step"]
        if abs(n - round(n)) > 1e-6:
            warn(who, f"max - min is not a whole number of steps ({e['min']}..{e['max']} by {e['step']})")


def publishes(e, key):
    """String literals an entity can publish to a command topic."""
    toks = set()
    if key == "command_topic":
        toks.update(str(e[k]) for k in ("payload_on", "payload_off") if k in e)
        toks.update(str(o) for o in e.get("options") or [])
    tpl = e.get(key.replace("_topic", "_template"), "")
    toks.update(re.findall(r"'([^']+)'\s+if\b", tpl))
    toks.update(re.findall(r"\belse\s+'([^']+)'", tpl))
    return toks


if __name__ == "__main__":
    main()
