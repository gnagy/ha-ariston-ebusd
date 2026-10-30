# ha-ariston-ebusd

An Ariston boiler in Home Assistant over eBUS: message definitions for [ebusd](https://github.com/john30/ebusd), the
MQTT integration file that names its entities, Home Assistant packages that turn them into climate, hot water and
heating-curve controls, and a dashboard view.

**Status: draft.** The files are the ones running on one house, made generic.

Start with [docs/getting-started.md](docs/getting-started.md): it installs the reads first, checks them against the
boiler, and adds the writes last. The comments in the files refer to the rest of `docs/`:

| Page                           | What                                                                      |
|--------------------------------|---------------------------------------------------------------------------|
| [design](docs/design.md)       | the layers from the boiler to a dashboard, how a write travels, the rules |
| [naming](docs/naming.md)       | how a CSV row becomes a Home Assistant entity, and why the ids are stable |
| [registers](docs/registers.md) | the bus, how ebusd decodes Ariston telegrams, zone settings, counters     |
| [errors](docs/errors.md)       | the boiler's error broadcasts and history, and the fault summary          |

Tested on one boiler only: an Ariston Genus One System 30 with two heating zones. Other Ariston models share much of
the register set, but check that reads work before you enable any write.

## Layout

| Path                               | What                                                                          | Goes to                                    |
|------------------------------------|-------------------------------------------------------------------------------|--------------------------------------------|
| `ebusd/configuration/`             | Message definitions: broadcasts, polled reads, zones, errors, writes          | the eBUSd add-on's `configuration/` folder |
| `ebusd/mqtt-hassio.cfg`            | ebusd's Home Assistant integration file, with the changes marked `Ariston:`   | the eBUSd add-on's `/config`               |
| `ebusd/addon-options.example.yaml` | Example options for the eBUSd add-on                                          | the add-on's Configuration tab             |
| `homeassistant/packages/`          | Climate, hot water, heating-curve and fault packages over ebusd's MQTT topics | Home Assistant's `packages/`               |
| `homeassistant/dashboards/`        | The Heating view                                                              | a dashboard view, in the raw config editor |
| `tools/check-controls.py`          | Checks that the definitions and the packages agree                            | run locally                                |

`_templates.csv` and `broadcast.csv` in `ebusd/configuration/` are stock ebusd files, included so the folder works as
it is. The rest is new.

## Optional parts

Leave these out if your system doesn't have them:

- **Zone 2:** `ebusd/configuration/ariston_zone2.csv` and `ariston_cmd_zone2.csv`,
  `homeassistant/packages/ariston_climate_zone2.yaml`, and the last section of the Heating view.
- **The Ariston WiFi module:** `ebusd/configuration/ariston_wifi.csv` and its card in the Heating view.
- **The zone 1 room temperature correction** in `ariston_climate_zone1.yaml`, for a thermostat that wraps at 25.6 °C. The
  file says what to change.

## Writes

Everything Home Assistant may set is listed in `ebusd/configuration/ariston_cmd*.csv`, and nothing else can be
written. Start without them: with only the read rows, check that the values in Home Assistant match the boiler's
display. Then add the `ariston_cmd*.csv` files and the packages.

## License

Apache 2.0, see `LICENSE`.
