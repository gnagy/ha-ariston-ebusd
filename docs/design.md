# Design

How the parts fit together, from the boiler's registers up to a dashboard: what each layer is responsible for, what
it may assume about its neighbours, and how a write and a read travel. The comments in the packages, the MQTT file
and `tools/check-controls.py` refer here.

## The one rule

**A layer knows the interface of the layer directly below it, and nothing past that.** Dashboards know entity ids
and nothing about topics. The packages know topics and nothing about the bus. ebusd knows the bus and nothing about
Home Assistant. A fact that appears in two layers has to be changed in two places when one of them is replaced.

```
 L5  dashboards, automations         entity ids
 L4  ariston_*.yaml packages         entities, ranges, names, mappings
 L3  MQTT broker                     topics (the contract)
 L2  ebusd                           rows: passive m, active r, write w
 L1  eBUS                            telegrams
 L0  the boiler                      registers
```

## The layers

| Layer         | Responsible for                                                                         | Must not                                                                        |
|---------------|-----------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| L0 the boiler | holding the settings and running the regulation: curve, schedules, modulation, safety   | be resent its settings on a timer: it keeps them                                |
| L1 eBUS       | carrying telegrams between the masters: boiler, thermostats, Sensys, WiFi module, ebusd | -                                                                               |
| L2 ebusd      | decoding telegrams to values and encoding values to telegrams, from the CSV rows        | hold Home Assistant knowledge: ranges for controls, entity names, mode mappings |
| L3 MQTT       | carrying messages, and keeping the last state of each (state topics are retained)       | -                                                                               |
| L4 packages   | turning topics into numbers, selects, switches, climates and derived sensors            | name a register in logic, reach the bus, or run a control loop                  |
| L5 dashboards | showing and operating                                                                   | contain a topic, a register or an ebusd name                                    |

Some consequences:

- **The boiler acknowledges nothing.** Ariston writes are broadcasts (`fe 2020 <id> <value>`), and the boiler checks
  no sender and sends no reply. A write is only known to have been taken when the register is read back, and a write
  can be silently ignored.
- **ebusd reads its configuration at start only**, so every row change needs an add-on restart.
- **Retained messages outlive the rows that made them.** A removed row leaves a stale topic on the broker, and a stale
  discovery message keeps its entity alive. Clear both when you remove a row.
- **The state of a control is what the state topic says**, never what was last sent. A tile follows the boiler.

## Writes are an allow-list

ebusd's write rows (`w`) are all in one circuit, `cmd`, in `ariston_cmd.csv` and `ariston_cmd_zone2.csv`. The MQTT
file announces only circuits starting `ariston` (`filter-circuit = ^ariston`), and only reads (`filter-direction =
r|u`), so ebusd creates no control entities of its own. The controls are defined by hand in the packages, with their
ranges, steps and names.

So **a register without a row in `cmd` cannot be written**, from Home Assistant or from anything else that publishes
to the broker. Adding a write means adding a row there, and a control in a package that uses it.
`tools/check-controls.py` checks that the two sides agree.

## The contract between ebusd and the packages

| Direction    | Topic                        | Payload                                                                                      |
|--------------|------------------------------|----------------------------------------------------------------------------------------------|
| state        | `ebusd/<circuit>/<name>`     | ebusd's JSON form, `{"0": {"name": "", "value": …}}`; multi-field rows key on the field name |
| command      | `ebusd/cmd/<name>/set`       | the plain value: `-9.5`, `1.05`, `on`                                                        |
| refresh      | `ebusd/<circuit>/<name>/get` | empty; ebusd reads the register and republishes the state topic                              |
| availability | `ebusd/global/running`       | `true` or `false`                                                                            |

How fresh a value is depends on how it reaches ebusd:

| Class     | Source                                                                       | Typical age            |
|-----------|------------------------------------------------------------------------------|------------------------|
| seconds   | boiler status and flame, WiFi state                                          | 5–10 s                 |
| minutes   | day temperature, curve offset, hot water values, heat requests               | 5 s to 5 min           |
| on demand | curve slope, room influence, winter mode, AUTO, hot water on/off, regulation | seconds after a `/get` |

A replacement for ebusd would have to offer the same four topics, the same freshness or better, and a command path
that announces no entities of its own. Nothing above L3 would then change.

## Where each piece of knowledge lives

| Knowledge                                    | Lives in                                      |
|----------------------------------------------|-----------------------------------------------|
| register ids, layouts, dividers, value lists | the ebusd rows                                |
| which registers may be written               | the rows in the `cmd` circuit                 |
| ranges, steps, units, names                  | the package entities                          |
| heat/off ↔ winter mode                       | the zone packages' templates                  |
| a thermostat's room temperature correction   | `ariston_climate_zone1.yaml`                  |
| entity ids                                   | the MQTT file's pins, see [naming](naming.md) |

## A write, end to end

1. The user moves zone 1's curve offset to -9.5 on the dashboard.
2. The number entity publishes `-9.5` to `ebusd/cmd/z1_curve_offset/set`. Its range kept the value within the
   boiler's own limits.
3. ebusd's `w` row encodes it and broadcasts `31 fe 2020 04 6471 a1ff`.
4. Nothing answers. The boiler stores the value, or does not.
5. After 3 s and again after 7 s, the automation *Ariston controls: re-read a register after it was set*, in
   `ariston_boiler.yaml`, publishes to `ebusd/ariston_z1/z1_curve_offset/get`. It runs in `parallel` mode, so writes
   made close together are each re-read.
6. ebusd reads the register from the boiler and republishes the state topic.
7. The entity shows the new value. If the boiler ignored the write it shows the old one: the slider snaps back, which
   is the sign that the write was not taken.

A read is the same from step 6: some master asks the boiler for a register, or the boiler broadcasts it, a passive
row decodes the answer, and the state topic is published, retained.

## When something fails

| Fault                                   | Seen as                                                                 |
|-----------------------------------------|-------------------------------------------------------------------------|
| ebusd stops                             | `ebusd/global/running` turns false; controls and sensors go unavailable |
| a write is lost or ignored              | the control snaps back                                                  |
| a write is taken but the re-read missed | the old value until the next broadcast                                  |
| ebusd's payload format changes          | entities unknown; fixed in the packages' templates alone                |
| the broker is down                      | nothing moves; the retained values return with it                       |

## Rules the files follow

1. **Knowledge flows one way**, as above.
2. **Ranges belong to the entity.** They come from the range the boiler reports for the register, and a control
   never sends outside it.
3. **Every write is confirmed by a read-back**, and the entity shows the read-back.
4. **No timers write.** Writes happen on a user action, at most once per change. The boiler regulates; Home Assistant
   changes its settings.
5. **Derived values stay derived.** A package may correct a reading for display; it never writes a corrected value
   back to the bus.
