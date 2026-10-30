# Naming

How a row in ebusd's CSV files becomes a Home Assistant device and entity, and the conventions the rows and
`ebusd/mqtt-hassio.cfg` follow so that the entity ids are predictable. The packages and the Heating view depend on
those ids.

`mqtt-hassio.cfg` is upstream's `contrib/etc/ebusd/mqtt-hassio.cfg` of 2024-10-26, with each change marked
`Ariston:` and explained where it is made.

## From a CSV row to an entity

| Layer       | Built from                                                          | Example: circuit `ariston_z1`, row `z1_regulation`, field `type`      |
|-------------|---------------------------------------------------------------------|-----------------------------------------------------------------------|
| CSV         | circuit, message name, field name, comment, field comment           | `ariston_z1`, `z1_regulation`, `type`, empty, "Thermoregulation type" |
| state topic | `ebusd/<circuit>/<name>`                                            | `ebusd/ariston_z1/z1_regulation`                                      |
| `unique_id` | `ebusd_ariston_<name>_<field>`, with field `0` on single-field rows | `ebusd_ariston_z1_regulation_type`                                    |
| device      | one per circuit                                                     | `ebusd ariston_z1`                                                    |
| entity id   | `<domain>.ebusd_ariston_<name>[_<field>]`, pinned for new entities  | `sensor.ebusd_ariston_z1_regulation_type`                             |
| entity name | the row's comment, or on a multi-field row each field's comment     | "Thermoregulation type"                                               |

- **The circuit is left out of the unique id and the entity id**, so a row can move to another circuit, and with it
  to another device, and keep its entity and history. Message names must therefore be unique across circuits.
- **The domain** comes from the cfg's `type_switch-list`: `error_*` rows are problem binary sensors, the on/off modes
  and the flame binary sensors, and everything else a sensor. Counters, burner internals, WiFi and the per-error
  entities are in the diagnostic category.
- **Discovery messages are retained**, so the entities survive a Home Assistant restart without waiting for ebusd.
- **Every entity is unavailable while ebusd is not running**: ebusd publishes `ebusd/global/running` false when it
  stops, and as its MQTT last will.

## Entity ids are pinned

Each discovery message carries `default_entity_id`, `<domain>.ebusd ariston <name> <field>`. Home Assistant uses the
part after the dot, slugified, so spaces become underscores and an empty field name on a single-field row leaves no
trailing separator. The id therefore does not depend on the device's name or area.

`default_entity_id` applies **only when Home Assistant creates the entity**. An entity that already exists keeps
whatever id it has. So an installation that ran an older configuration keeps its old ids until they are renamed in
the entity registry, which keeps their history. Deleting an entity and letting discovery recreate it gives the new
id but loses the history.

**ebusd's own entities** (running, signal, uptime, the update check) are pinned the same way, as
`binary_sensor.ebusd_global_running`, `sensor.ebusd_global_uptime` and so on, after their `ebusd/global/…` topics.
Not `binary_sensor.ebusd_running`: on Home Assistant OS the Supervisor's own entity for the add-on holds that id,
disabled, and ebusd's would become `binary_sensor.ebusd_running_2`.

## Conventions for the rows

| Element     | Convention                                                                                                                                                   | Examples                                                      |
|-------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------|
| circuit     | `ariston` for the boiler, its errors and hot water; `ariston_z1`, `ariston_z2` for the zones; `ariston_wifi` for the WiFi module; `cmd` for writes           | `ariston`, `ariston_z1`                                       |
| message     | `<subsystem>_<quantity>[_<qualifier>]`, snake\_case. Subsystems `boiler`, `heating`, `dhw`, `z1`…`z6`, `wifi`, `error`. Zone 2 uses zone 1's names with `z2` | `boiler_gas_power`, `z1_day_temp`, `z2_day_temp`, `error_1p4` |
| field       | empty for a single value; snake\_case names when a row carries several                                                                                       | `z1_regulation` → `type`, `room_influence`                    |
| request row | its own name ending `_req`, never the name of the row that decodes the answer: a field-less poll publishes an empty retained value on its topic              | `<name>_req`                                                  |
| comment     | English, sentence case, **no commas**, which shift the CSV columns. No device name in it, since Home Assistant adds that                                     | "Room temperature", "DHW comfort temperature"                 |

On a multi-field row the row's comment stays empty and each field comment is the full name. The cfg joins the two
without a separator, because ebusd trims comments, so there is no way to put a space between them.

## Devices and areas

ebusd's devices are one per circuit, created in the area `Heating` (`area =` in the cfg; upstream's own value). Home
Assistant applies the area only when it creates a device, so move them afterwards as you like: the boiler to where
it is, each zone to the room its controller is in. Entity ids and history do not change with the area, so swapping
two zones' thermostats later means changing two device areas and nothing else.
