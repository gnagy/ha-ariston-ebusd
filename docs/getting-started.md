# Getting started

From an Ariston boiler and a bare eBUS adapter to the boiler in Home Assistant: climate entities per zone, hot
water, the heating curve, a fault summary and the Heating view.

The order matters. Reads come first, and you check them against the boiler's own display before anything can
write to it. The writes come last.

Tested on one boiler: an Ariston Genus One System 30 with a Sensys and two zones. If your boiler is a different
model, expect some values to be missing or wrong, and stop at step 6 if they are.

## 1. What you need

- **An Ariston boiler on eBUS**, which Ariston calls BridgeNet: the boiler, a thermostat or Sensys, and optionally
  the Ariston WiFi module, all on one bus.
- **An eBUS adapter**: a USB one, or a network one such as the ESP32-based adapters.
- **Home Assistant OS or Supervised**, so that add-ons are available. With Home Assistant Container, run ebusd
  yourself with the same options as in step 4, and point it at your MQTT broker.
- **An MQTT broker.** The Mosquitto add-on is the simplest.
- **A way to copy files** into the add-on's folder: the Samba, SSH or Studio Code Server add-on.

## 2. Connect the adapter

The adapter goes on the bus terminals, beside the thermostat's wires, with the boiler switched off. Where those
terminals are depends on the boiler, and how to wire the adapter depends on the adapter: follow its documentation.

## 3. MQTT

Install the **Mosquitto broker** add-on and start it. Home Assistant then offers the **MQTT** integration under
**Settings → Devices & services**; set it up.

## 4. The eBUSd add-on

Add `https://github.com/LukasGrebe/ha-addons/` under **Settings → Add-ons → Add-on store → ⋮ → Repositories**, and
install **eBUSd**.

**Don't start it yet.** First set its options on the **Configuration** tab, switched to YAML. On a fresh install
`seed_mqtt_cfg` is on, and its first start would replace the MQTT file you copy in step 5.
`ebusd/addon-options.example.yaml` has the options this setup runs with:

- **`device` or `network_device`.** A USB adapter is picked under `device`. A network adapter goes in
  `network_device`, as `ens:<address>:9999` for one that speaks ebusd's enhanced protocol. Check the adapter's
  documentation for its form. Set one of the two.
- **`seed_mqtt_cfg: false`**, for the reason above.
- **`--configpath=/config/configuration` with `--scanconfig=none`**: ebusd loads these definitions and nothing
  else, instead of guessing a configuration from what it finds on the bus.
- **`--mqttint=/config/mqtt-hassio.cfg`** with **`--mqttjson`**: the file that turns ebusd's messages into Home
  Assistant entities, with the names the packages and the view expect.
- **`--accesslevel='*'`**: needed for the writes in step 9. Without it, ebusd refuses them.
- **`--lograwdata`** and the two options after it: optional. They keep a log of everything on the bus, which is what
  you would send with a question.

The add-on finds the Mosquitto add-on by itself; there is no MQTT host to set. It warns on start that `--log`
appears more than once. That is expected: each `--log` sets one area's level.

## 5. The definitions, reads only

Inside the add-on, `/config` is the folder `/addon_configs/<id>_ebusd/` on the host. The id is the add-on
repository's, shown in the add-on's URL. Copy into it:

- `ebusd/mqtt-hassio.cfg`
- `ebusd/configuration/`, **without** `ariston_cmd.csv` and `ariston_cmd_zone2.csv`, the writes
- and leave out `ariston_zone2.csv` if the boiler has one zone, and `ariston_wifi.csv` if it has no WiFi module

**Copying from a Mac** can bring hidden `._` files along, such as `._ariston.csv`. ebusd stops reading the folder at
the first file it can't parse, so delete them: in the SSH add-on, `find /addon_configs/*_ebusd -name '._*' -delete`.

Start the add-on.

## 6. Check the reads

- **The add-on's log** says `read config files, got 136 messages` with every file of step 5, fewer without zone 2 or
  the WiFi module. An error there names the file that stopped it. `signal acquired` means the adapter hears the bus.
  A few `scan config 3c: …` errors after the start are normal: ebusd asks each device for the standard eBUS
  identification, which Ariston devices don't answer.
- **Settings → Devices & services → MQTT** lists ebusd's devices, put in an area called Heating; move them as you
  like. `binary_sensor.ebusd_global_running` and `binary_sensor.ebusd_global_signal` are ebusd itself. The values
  the boiler sends by itself arrive within a minute, and the polled ones (counters, hours, fan and pump) over the
  following minutes. Settings that the boiler only broadcasts every half hour can take that long.
- **Compare with the boiler's display**: pressure (`sensor.ebusd_ariston_boiler_pressure`), flow temperature
  (`sensor.ebusd_ariston_heating_temp_out`), outside temperature (`sensor.ebusd_ariston_ext_temp`) and the zone 1 day
  temperature (`sensor.ebusd_ariston_z1_day_temp`).

If entities are missing, or values are wrong by a factor or plainly unrelated, the boiler is a different model or
the definitions don't fit it. Don't go on to the writes. An issue with the add-on's log and a few minutes of the raw
log is the way to find out more.

## 7. The packages

Turn on packages in `configuration.yaml`, if they aren't already:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Copy the files in `homeassistant/packages/` into `packages/`, or a subfolder of it such as `packages/ariston/`. Then
choose the optional parts:

- **One zone:** delete `ariston_climate_zone2.yaml`.
- **Zone 1's thermostat** in this house sends its room temperature in a form that wraps at 25.6 °C, and
  `ariston_climate_zone1.yaml` corrects it. If yours doesn't wrap, its first comment says what to change.

Check the configuration (**Developer tools → YAML → Check configuration**, or `ha core check` in the SSH add-on)
and restart Home Assistant. Check that `climate.zone_1`, `switch.heating_winter_mode` and `switch.heating_hot_water`
exist and match the boiler. Their controls do nothing yet, because the write rows are not loaded.
`binary_sensor.boiler_fault` and `sensor.boiler_last_error` stay unavailable until ebusd has polled the boiler's
error table, a few minutes after it starts.

## 8. The Heating view

Open a dashboard, add a view, switch it to the raw configuration editor and paste `homeassistant/dashboards/heating.yaml`.
Delete the zone 2 section and the WiFi module card if you don't need them.

## 9. Writes

Copy `ariston_cmd.csv` into the add-on's `configuration/`, and `ariston_cmd_zone2.csv` for a second zone. Restart the
add-on; its log now says `got 150 messages` with every file. These files list everything Home Assistant may set, and
nothing outside them can be written.

Test one write: raise zone 1's day temperature by 0.5 °C on `climate.zone_1`. The thermostat or the boiler's panel
shows the new value, and within about ten seconds Home Assistant shows what the boiler now holds: the automation
*Ariston controls: re-read a register after it was set* asks for it after every write. Set it back.

The boiler keeps running the heating: the curve, the schedules and its own safety. Home Assistant changes settings
and reads them back. A change made at the thermostat wins, and Home Assistant then shows it.

## 10. When it doesn't work

| Symptom                                     | Look at                                                                        |
|---------------------------------------------|--------------------------------------------------------------------------------|
| No ebusd devices under MQTT                 | the add-on's log; `--mqttint` and its path; the Mosquitto add-on running       |
| `read config files` reports an error        | the file it names: a `._` file from a Mac, or an edit that broke a line        |
| `signal lost`, or bus errors in the log     | the adapter, its wiring, `device` or `network_device`                          |
| Entities exist but stay unknown             | wait half an hour for the broadcasts; then the definitions may not fit         |
| A control in Home Assistant changes nothing | `--accesslevel='*'`; the `ariston_cmd*.csv` files copied; the add-on restarted |
| The configuration check fails after step 7  | the `packages:` line, and that every package file came along                   |

## Updating

Copy the new files over the old ones, restart the add-on, then Home Assistant if a package changed. Keep your
changes in your own copy of this repository rather than editing the files on the instance, where the next update
would overwrite them.
