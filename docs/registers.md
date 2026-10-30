# Registers

What the rows in `ebusd/configuration/` decode, and how each was identified: enough to read a row's comment, check a
value against the boiler's display, or add a register.

Most layouts come from community ebusd configurations: wrongisthenewright's (a Genus One hybrid), ysard's (a
Chaffoteaux Mira C Green), kredow's register map, and others built on them. Each row here was checked against a
Genus One System's bus traffic and its display menus, and the comments say where a meaning is still unconfirmed.

## The bus

| Address | Device                                       |
|---------|----------------------------------------------|
| `37`    | the boiler, as a master                      |
| `3c`    | the boiler, as the target of addressed reads |
| `70`    | an older Ariston room thermostat, on zone 1  |
| `f0`    | a Sensys HD, on zone 2                       |
| `7f`    | the WiFi module                              |
| `31`    | ebusd                                        |

Your bus may have other addresses. ebusd's log, and `ebusctl info`, list the masters it sees.

Ariston's BridgeNet puts register ids in the data. Ids are 2 bytes in wire order, values little-endian:

| Verb (PBSB) | What it carries                                                                          |
|-------------|------------------------------------------------------------------------------------------|
| `2000`      | a read of one or more registers. The reply starts with a bitmask of the ids answered     |
| `2001`      | a read of a register with its range: value, minimum, maximum                             |
| `200f`      | a broadcast answer: register and value                                                   |
| `200e`      | a broadcast answer with the range: register, value, minimum, maximum                     |
| `2010`      | the boiler's status broadcasts, every few seconds                                        |
| `2020`      | writes from any master (`fe 2020 <id> <value>`), and the boiler's rotating settings dump |
| `2004`      | current errors, see [errors](errors.md)                                                  |
| `2002`      | the error history, see [errors](errors.md)                                               |

## How ebusd decodes them

**One telegram is decoded by exactly one row.** ebusd looks a telegram up by sender, target, PBSB and its first data
bytes, longest ID first, and stores the data into the single row it finds. A second row with the same key is refused
at load as a duplicate. The circuit and name are not part of the key, so another circuit doesn't help. That has
consequences for the files:

- **A telegram that carries several registers is one row with several fields**, keyed on its first register. The
  `2020` settings dump comes in a few fixed shapes, so `ariston_zone.csv` and `ariston_zone2.csv` decode each shape
  with one row, and the comments above those rows show the telegram.
- **A register can't also have a row of its own** for a telegram that a multi-field row already decodes.

**Rows that share a circuit and name behave as one value.** One name can hold one active read (`r`), one write (`w`)
and one passive row (`m`/`u`), and all of them publish to the same topic and entity: whichever received data last
holds the value. That is how the read-back rows in `ariston.csv` share a name with the passive rows, so a control's
re-read updates the same entity.

**An `r` row is polled**, by priority: `r1` often, `r5` less, `r9` rarely. It also picks up the same request sent
by another device, such as the Sensys or the WiFi module, which is why many rows need no poll of their own.

## Zone settings

**Thermoregulation**, menu 4.2.1 for zone 1 and 5.2.1 for zone 2, registers `c079` and `c07a`:

| Value | Meaning                  |
|-------|--------------------------|
| 0     | fixed flow temperature   |
| 1     | basic                    |
| 2     | room temperature only    |
| 3     | outdoor temperature only |
| 4     | room and outdoor         |

The Genus One manual (p. 41) confirms that 2 is room only and 3 is outdoor only. wrongisthenewright's configuration
has the two swapped; don't copy its labels. Under "basic", the curve's slope, offset and flow limits have no effect.

**Zone mode**, `c679` and `c67a`. Cycling the Sensys through off, manual and time program moved `c679` and nothing
else: 0 off, 2 manual, 3 time program. 1 is accepted, shows as `-` on the Sensys, and is unknown. Zone 2's `c67a` uses
the same labels by assumption: it has not been seen to change. This is not the "heat request mode" of menu 4.2.9 that
the Nimbus and Zone Manager manuals describe (standard, time programs excluded, forcing); that is a different
register, `ce79` in wrongisthenewright's configuration.

**Heat request and flow setpoint**, read off the Sensys's menus 4.3.4 and 4.3.8. The boiler broadcasts zone 1's heat
request `0191` on `200f` about every 5 minutes. Zone 1's computed flow setpoint `6197` is broadcast only when someone
asks, but the boiler answers an addressed `2001` read, so it is polled. The setpoint is the end of the zone's
regulation chain and acts only while the zone requests heat.

## A thermostat whose room temperature wraps

The zone 1 thermostat here, an older Ariston model at `70`, answers the boiler's request for its room temperature
(`7118`) with a 2-byte value in tenths of a degree, but **the high byte is always `00`**: the value wraps at 25.6 °C.

| Real room | Sent |
|-----------|------|
| 25.4 °C   | 25.4 |
| 25.5 °C   | 25.5 |
| 25.6 °C   | 0.0  |
| 26.2 °C   | 0.6  |
| 30.4 °C   | 4.8  |

Correcting it is exact: **real = sent + 25.6 when sent is below 10 °C**, since a heated room is never that cold.
`ariston_climate_zone1.yaml` does this for the climate tile. The evidence: tens of thousands of telegrams with the high
byte `00`, every crossing a single 0.1 °C step from 25.5 to 0.0, a correlation of 0.98 with an independent room
sensor once unwrapped (−0.82 raw), and a thermostat warmed by hand counting up past 25.5 to 0.1.

The thermostat's `200e` answer, which it sends when another device asks for the register with its range, carries the
full value. Only the periodic answer wraps. A Sensys does not wrap.

**The boiler uses the wrapped value.** With zone 1 on room-and-outdoor regulation (4) in winter mode, a room above
25.5 °C reads as cold, and the zone's flow setpoint goes to its maximum as soon as it calls for heat. Setting the zone
to outdoor only (3) takes the room value out of its regulation. If your zone 1 thermostat wraps, do that, or replace
it with a Sensys. The correction in the package only fixes what Home Assistant shows.

## Counters

Read with `2000` from `3c`, menu 8.0 and 8.1 on the display. A 32-bit counter is two registers, low word then high
word, requested together and read as one `ULG`.

| Registers   | Menu  | Row                            | Unit |
|-------------|-------|--------------------------------|------|
| `4bd1`      | 8.1.0 | `hours_burner_on`              | h    |
| `4cd1`      | 8.1.1 | `hours_burner_on_dhw`          | h    |
| `46d1`      | 8.1.2 | `boiler_flame_faults`          |      |
| `4dd1`      | 8.1.4 | `boiler_heat_request_duration` | min  |
| `40d2 41d2` | 8.0   | `boiler_diverter_cycles`       |      |
| `44d2 45d2` | 8.0   | `boiler_circulation_cycles`    |      |

The rest of the `d2` pairs are in `ariston_poll.csv`. The display shows a tenth of `4cd1` and `46d1`. `47d1`–`4ad1`
answer with an empty mask, and `46d2`–`49d2` are not in the menu.

## The burner while it runs

| Register | Row                         | Meaning                                                                                            |
|----------|-----------------------------|----------------------------------------------------------------------------------------------------|
| `6847`   | `boiler_gas_power`          | gas power, ÷ 10 kW. Inside the boiler's rated 3–28 kW input; probably the Sensys's 8.2.8           |
| `4013`   | `boiler_fan_speed`          | fan speed in rpm, falling as the burner modulates down; menu 8.2.2                                 |
| `c300`   | `boiler_pump_modulation`    | pump modulation in %; menu 8.2.7. Stays up after the flame goes out                                |
| `409d`   | `boiler_combustion_control` | **unconfirmed.** 0 without a flame, about 105 at ignition, settling to about 97–100 within minutes |

`409d` is asked for by the Sensys every 10 s, beside the pressure `7547`. wrongisthenewright calls it
`flame_efficiency`, but the boiler has no flue gas sensor to measure one. It isn't gas power, fan or pump: it does not
follow them. Doubling the gas power did not raise it, and every burn starts near 105 and decays. That fits a
combustion control's correction factor near 100, which the Genus One adjusts from its ionisation current; hence the
name, marked unconfirmed.

## Adding a register

1. Find it in the raw log (`--lograwdata`) while you change the setting on the display or the Sensys, and note the
   verb and the value's bytes.
2. Check that no existing row already decodes that telegram: ebusd will refuse a duplicate, or decode it with the other
   row only.
3. Name it by the conventions in [naming](naming.md), and give it a comment without commas.
4. Restart the add-on, and compare the entity with the display.
