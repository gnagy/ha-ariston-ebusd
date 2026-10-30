# Boiler errors

How the boiler puts its errors on the bus, and how `ariston_errors.csv`, `boiler_fault.yaml` and
`boiler_last_error.yaml` turn them into Home Assistant entities.

The boiler keeps two kinds of error report, and they travel differently:

- **Current errors**, one state per error, active or cleared. The boiler broadcasts them, so nothing has to ask.
- **The error history**, the last ten errors with the boiler's own date and time (menu 8.6.0 on the display).
  Nothing broadcasts it, so ebusd polls it.

The layout comes from two community ebusd configurations, ysard's (a Chaffoteaux Mira C Green) and
wrongisthenewright's (a Genus One hybrid), checked against a Genus One System's bus.

## Current errors: the 2004 broadcast

```
37 fe 2004 05 | 07 02 00 00 3c
                │  │  └─┴──── 00 3c: the device that raised it; the same on every error seen
                │  └────────── flags
                └───────────── error index, mapped to a display code by the table below
```

| Flags | Meaning                                                                  |
|-------|--------------------------------------------------------------------------|
| `00`  | not active                                                               |
| `01`  | a zone error with no zone affected: not active                           |
| `02`  | active. On a zone error, bit 0 is zone-enable and bits 1–6 are zones 1–6 |

Other boilers may send fewer or more bytes after the flags (ysard's sends 3 for a resolved error, and one byte per
affected zone when active), so only the index and the flags are decoded.

**When the boiler sends it:**

- **On change**, at once, as a pair of identical telegrams, repeated about every 10 s for a minute or two, then about
  every 2 minutes for an hour or more.
- **Hourly**, the whole table: one telegram per error the boiler supports, 53 in about 5 seconds, active or not.
  Indices `2d` and `2f` come twice.

So the current state can be rebuilt from at most an hour of bus traffic. After ebusd restarts, an error's entity can
take up to an hour to get a value; the retained MQTT value covers the gap in Home Assistant.

### One row per index

ebusd keeps one value per message definition. A single row for every `2004` telegram would show only the error
announced last, which after the hourly dump is always `ec`. With the index as the row's ID, each telegram matches
only its own row, so every error keeps its own state. `ariston_errors.csv` has 52 rows, one per index in this boiler's
dump, named `error_<code>` with the display code and description in the comment.

The first line of `type_switch-list` in `mqtt-hassio.cfg` makes them binary sensors of class `problem`, in the
diagnostic category. Each becomes `binary_sensor.ebusd_ariston_error_<code>`.

A comma in a row's comment shifts the CSV columns, and ebusd then stops loading every file after it. The descriptions
avoid commas for that reason.

### Index to display code

The index is not the display code, and the table can differ between systems. This one is from wrongisthenewright's
templates, and matches the error table in the Genus One installation manual (pp. 36–37):

| Index          | Code      | Index          | Code                            |
|----------------|-----------|----------------|---------------------------------|
| `00`           | 101       | `21`,`22`,`24` | 303, 304, 306                   |
| `01`           | 102       | `2c`           | 5P6                             |
| `02`…`04`      | 1P1…1P3   | `2d`,`2e`,`2f` | 501, 502, 504                   |
| `05`,`06`      | 104, 107  | `30`,`31`,`32` | 5P1, 5P2, 5P3                   |
| `07`           | 1P4       | `3b`,`3c`,`3f` | 610, 612, 611                   |
| `08`           | 1P4 (ESC) | `49`           | 3P9                             |
| `0a`…`0e`      | 110…118   | `69`           | 411                             |
| `0f`,`10`,`11` | 103…106   | `78`           | 901                             |
| `12`,`13`      | 108, 111  | `c3`…`c9`      | 313, 5P5, —, 802, 503, 803, 804 |
| `14`,`15`,`16` | 1P5…1P7   | `ec`           | `---`                           |
| `18`…`1f`      | 201…209   |                |                                 |

`c5` has no display code: it is the deaeration or automatic setup notice. `ec` is what the display shows as `---`.
Index `69` (411, room probe) may be sent with flags `01` all the time; that is a zone error with no zone, not a fault.

If your boiler's table differs, ysard's ebusd configuration has a script that rebuilds it by broadcasting each index
and reading the display.

## Kinds, and what clears them

The installation manual (p. 36) sorts errors into three kinds, and `boiler_fault.yaml` carries the kind of each code
from the manual's table (pp. 36–37) and the Genus One training manual (pp. 85–86):

| Kind                        | Example       | Goes away                                                              |
|-----------------------------|---------------|------------------------------------------------------------------------|
| warning, `xPy`              | 1P4, 5P3      | by itself; the boiler keeps running                                    |
| safety shut-off, "volatile" | 108, 110      | by itself, once the cause is removed                                   |
| lockout, "non-volatile"     | 501, 504, 303 | only with the RESET button. More than 5 resets in 15 minutes gives 304 |

Seen on the bus:

- **A lockout replaces the warning that led to it**: the lockout is raised and the warning cleared within the same
  second (5P3 flame cut-off, then 504 flame lift).
- **A lockout's clear has no telegram before it.** The RESET button acts inside the boiler, and the bus only learns
  the result. No telegram is known that resets a lockout remotely.
- **Low pressure has two thresholds** (training manual): below parameter 241, 0.6 bar by default, the boiler raises 1P4
  and keeps running; below parameter 240, 0.4 bar by default, it raises 111 and shuts down.

A broadcast `2004` from another master raises or clears a code on the display, which trusts whatever it hears. That
does not change the boiler's own state, and the boiler re-announces its table within the hour.

## The summary: `binary_sensor.boiler_fault`

`boiler_fault.yaml` is on while any `binary_sensor.ebusd_ariston_error_*` entity is on, found by id pattern rather
than listed. Its `errors` attribute lists each active error with its code, description, kind and since when Home
Assistant has seen it. `c5` and `ec` are notices and are left out.

While ebusd is down every error entity is unavailable. Counting none of them as on would report a clean boiler, so
the summary is unavailable too until the error entities have a state.

## The history: `last_error`

The `r9` row `last_error` reads history slot `0400`, the most recent of the ten (`0400`–`0409`), with verb `2002`:

```
31 3c 2002 02 0400   →   0b | 07 00 0000 1a 08 16 04 25 0100
                                │  │  │    │  │  │  └──┴── time 04:37
                                │  │  │    └──┴──┴──────── year 26, month 8, day 22
                                │  │  └──────────────────── not decoded
                                │  └─────────────────────── zone flags
                                └────────────────────────── index 07: 1P4
```

`0b` is the reply's length; the bytes after the time are not decoded.

No other device on the bus asks for it, so ebusd polls it. ebusd publishes code, zone, year, month, day and time as
separate entities. `boiler_last_error.yaml` assembles them into `sensor.boiler_last_error`, a timestamp, because no
ebusd date type reads a year-first date; it is unavailable while the slot is empty. The boiler's clock is local time,
set through the WiFi module, so it is read in Home Assistant's own time zone. Slots `0401`–`0409` are not read yet.
