"""Self-check for the coordinator's stale-snapshot / lifetime-hold logic.

Run with: python3 tests/test_staleness.py   (or pytest)
homeassistant is stubbed, so only the pure logic runs.
"""
import datetime as D
import sys
import types
from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent.parent / "custom_components" / "delta_solar"
for name in (
    "homeassistant", "homeassistant.core", "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client", "homeassistant.helpers.update_coordinator",
    "homeassistant.util", "homeassistant.util.dt",
):
    sys.modules.setdefault(name, types.ModuleType(name))


class _Base:
    def __class_getitem__(cls, _):
        return cls

    def __init__(self, *a, **k):
        pass


sys.modules["homeassistant.core"].HomeAssistant = object
sys.modules["homeassistant.helpers.aiohttp_client"].async_create_clientsession = None
sys.modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = _Base
sys.modules["homeassistant.helpers.update_coordinator"].UpdateFailed = Exception
dt = sys.modules["homeassistant.util.dt"]
sys.modules["homeassistant.util"].dt = dt
sys.modules["homeassistant"].util = sys.modules["homeassistant.util"]
_now = [D.datetime(2026, 10, 7, 5, 0, tzinfo=D.timezone.utc)]
dt.utcnow = lambda: _now[0]
dt.DEFAULT_TIME_ZONE = D.timezone(D.timedelta(hours=5, minutes=30))

_pkg = types.ModuleType("delta_solar")
_pkg.__path__ = [str(_pkg_dir)]
sys.modules["delta_solar"] = _pkg
from delta_solar.coordinator import STALE_AFTER, DeltaSolarCoordinator  # noqa: E402


def test_lifetime_held_and_stale_flagged():
    c = DeltaSolarCoordinator.__new__(DeltaSolarCoordinator)
    c._last_ts, c._lifetime = None, None
    c._last_ts_seen = _now[0] - STALE_AFTER - D.timedelta(seconds=1)

    def poll(ts, male, minutes=0):
        _now[0] += D.timedelta(minutes=minutes)
        live = {"last_ts": ts, "lifetime_energy": male, "current_power": 1000.0}
        return c._apply_staleness(live)

    r = poll(100, 8255.49)  # restart at night: low portal counter must not be trusted
    assert (r["connection"], r["lifetime_energy"], r["current_power"]) == ("Disconnected", None, 0.0)
    r = poll(200, 47737.0, 15)  # first real report
    assert (r["connection"], r["lifetime_energy"]) == ("Connected", 47737.0)
    r = poll(300, 47750.8, 15)
    assert r["lifetime_energy"] == 47750.8
    for m in (15, 15, 20):  # inverter goes silent
        r = poll(300, 47750.8, m)
    assert (r["connection"], r["lifetime_energy"], r["current_power"]) == ("Disconnected", 47750.8, 0.0)
    r = poll(300, 8244.88, 600)  # portal swaps in its lower counter overnight
    assert r["lifetime_energy"] == 47750.8


if __name__ == "__main__":
    test_lifetime_held_and_stale_flagged()
    print("test_lifetime_held_and_stale_flagged: OK")
