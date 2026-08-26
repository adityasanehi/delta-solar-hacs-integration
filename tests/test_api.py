"""Parsing self-checks for the Delta Solar API client.

Run with either:
    python3 -m pytest tests/
    python3 tests/test_api.py

The integration package is loaded directly (with a stub parent module) so
homeassistant itself is not required here.
"""
import sys
import types
from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent.parent / "custom_components" / "delta_solar"
if "delta_solar" not in sys.modules:
    _pkg = types.ModuleType("delta_solar")
    _pkg.__path__ = [str(_pkg_dir)]
    sys.modules["delta_solar"] = _pkg

from delta_solar.api import DeltaSolarAPI  # noqa: E402

# Real item=more capture from an RPI-M6A (2026-08-26). Raw scalings:
# iv/ov are volts x10, ic/oc are amps x100, ip/op are watts.
MORE = {
    "result": {
        "O1R19900620W3": {
            "1": {
                "fwv": [294, 302, 271],
                "ivs": 2,
                "male": 46762610,
                "iv": [2714, 3044],
                "ic": [745, 756],
                "ip": [2022, 2302],
                "ov": [4028, 4015, 4029],
                "oc": [612, 615, 610],
                "op": [1423, 1416, 1405],
            }
        }
    }
}


def test_parse_live_data():
    live = DeltaSolarAPI.parse_live_data(MORE, "O1R19900620W3", 1)

    # Per-string DC: V = iv/10, A = ic/100, W = ip.
    assert live["dc1_voltage"] == 271.4
    assert live["dc1_current"] == 7.45
    assert live["dc1_power"] == 2022.0
    assert live["dc2_voltage"] == 304.4
    assert live["dc2_current"] == 7.56
    assert live["dc2_power"] == 2302.0
    assert live["dc_string_count"] == 2

    # Per-phase AC: V = ov/10 (line-to-line), A = oc/100, W = op.
    assert live["ac1_voltage"] == 402.8
    assert live["ac1_current"] == 6.12
    assert live["ac1_power"] == 1423.0
    assert live["ac3_voltage"] == 402.9
    assert live["ac3_power"] == 1405.0
    assert live["ac_phase_count"] == 3

    # Current power = sum of phase powers (the value that reconciles with
    # the energy totals); lifetime = male/1000.
    assert live["current_power"] == 4244.0
    assert live["lifetime_energy"] == 46762.61
    assert live["inverter_status"] == 2
    assert live["firmware_version"] == "1.38 / 1.46 / 1.15"


def test_parse_live_data_empty():
    live = DeltaSolarAPI.parse_live_data({}, "O1R19900620W3", 1)
    assert live["dc_string_count"] == 0
    assert live["ac_phase_count"] == 0
    assert live["current_power"] is None
    assert live["lifetime_energy"] is None
    assert live["firmware_version"] is None


def test_parse_live_data_dc_power_fallback():
    """Without ip, string power falls back to V x A."""
    more = {"result": {"SN1": {"1": {"iv": [2714], "ic": [745]}}}}
    live = DeltaSolarAPI.parse_live_data(more, "SN1", 1)
    assert live["dc1_power"] == 2021.9  # 271.4 * 7.45
    assert live["current_power"] is None


def test_energy_parsers():
    assert DeltaSolarAPI.parse_day_energy({"day_energy": 9510}) == 9.51
    assert DeltaSolarAPI.parse_day_energy({"te": 30720}) == 30.72
    assert DeltaSolarAPI.parse_day_energy({}) is None
    assert DeltaSolarAPI.parse_day_energy({"day_energy": "x"}) is None
    assert DeltaSolarAPI.parse_period_energy({"energy": [25000, None, 26800]}) == 51.8
    assert DeltaSolarAPI.parse_period_energy({}) is None
    assert DeltaSolarAPI.parse_period_energy({"energy": None}) is None

    totals = DeltaSolarAPI.parse_all_totals(
        {"day_energy": 9510},
        {"energy": [25000, 26800]},
        {"energy": [296800, None]},
    )
    assert totals == {"today": 9.51, "month": 51.8, "year": 296.8}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: OK")
    print("all parsing checks passed")
