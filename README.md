# Delta Solar — Home Assistant Integration (HACS)

Monitor your **Delta Solar** inverter and plant energy data directly in Home Assistant.

## Features

- **Auto-discovery**: enter only your email and password — plant ID, serial number, timezone, and all other parameters are fetched automatically
- **Multiple plant support**: if you have more than one installation, you pick from a dropdown during setup
- **4 sensors per plant**:
  | Sensor | Unit | Description |
  |--------|------|-------------|
  | Today's Energy | kWh | Energy generated today |
  | Monthly Energy | kWh | Energy generated this calendar month |
  | Yearly Energy | kWh | Energy generated this calendar year |
  | Current Power | W | Real-time output power |
- Data refreshes every **5 minutes**
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
# delta-solar-hacs-integration
