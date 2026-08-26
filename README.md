# Delta Solar — Home Assistant Integration (HACS)

Monitor your **Delta Solar** inverter and plant energy data directly in Home Assistant.

## Features

- **Auto-discovery**: enter only your email and password — plant ID, serial number, timezone, and all other parameters are fetched automatically
- **Multiple plant support**: if you have more than one installation, you pick from a dropdown during setup
- **Sensors per plant**:
  | Sensor | Unit | Description |
  |--------|------|-------------|
  | Today's Energy | kWh | Energy generated today |
  | Monthly Energy | kWh | Energy generated this calendar month |
  | Yearly Energy | kWh | Energy generated this calendar year |
  | Lifetime Energy | kWh | Total energy generated since commissioning |
  | Current Power | W | Real-time AC output power (sum of phase powers) |
  | String N Voltage | V | DC input voltage per MPPT string |
  | String N Current | A | DC input current per MPPT string |
  | String N Power | W | DC input power per MPPT string |
  | Line N Voltage | V | AC line-to-line voltage (e.g. ~400 V on a 3-phase system) |
  | Phase N Current | A | AC output current per phase |
  | Phase N Power | W | AC output power per phase |
- The number of string/phase sensors is detected automatically from your inverter (e.g. RPI-M6A reports 2 strings and 3 phases)
- Firmware version is shown on the device page (`sw_version`)
- Live electrical values (power, voltages, currents) come from the inverter's latest snapshot report, so they always share one timestamp — immune to plant timezone/clock misconfiguration
- Data refreshes every **15 minutes**, matching the inverter's cloud reporting cadence
- Works with the HA **Energy Dashboard** (Today's Energy sensor)

## Installation via HACS

1. Open HACS → **Integrations** → ⋮ → **Custom repositories**
2. Add `https://github.com/adityasanehi/delta-solar-hacs-integration` as an **Integration**
3. Search for **Delta Solar** and install
4. Restart Home Assistant
5. Go to **Settings → Devices & Services → Add Integration** and search for **Delta Solar**

## Manual Installation

Copy the `custom_components/delta_solar/` folder into your HA `config/custom_components/` directory and restart.

## Configuration

During the setup wizard you only need:

| Field | Description |
|-------|-------------|
| **Email** | Your mydeltasolar.deltaww.com account email |
| **Password** | Your portal password |

Everything else (Plant ID, inverter serial number, timezone, etc.) is discovered automatically from the API.

## Supported Devices

Any Delta solar installation accessible via [mydeltasolar.deltaww.com](https://mydeltasolar.deltaww.com) including:

- RPI series inverters
- SOLiS-compatible Delta installations

## Troubleshooting

- **invalid_auth**: verify your credentials work at [mydeltasolar.deltaww.com](https://mydeltasolar.deltaww.com)
- **Sensors show unavailable**: check HA logs (`Settings → System → Logs`) for `delta_solar` entries
- **Energy values are 0**: the API response format may differ from what is expected; open an issue and attach the raw log output (enable debug logging below)

### Enable debug logging

```yaml
# configuration.yaml
logger:
  default: warning
  logs:
    custom_components.delta_solar: debug
```

## Privacy

Credentials are stored locally in Home Assistant's encrypted config store. No data is sent anywhere except the official Delta Solar portal.
