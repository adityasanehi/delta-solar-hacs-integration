"""Local client for the Delta inverter's own Wi-Fi AP (Modbus RTU framing over raw TCP).

Protocol reverse-engineered from the DeltaSolar Android app: default
192.168.50.1:5001, unit 0xFF, function 3/4, 1-based register addresses on the app side
(wire address = app address - 1). The app opens a fresh socket per request, and so do we:
the inverter AP drops every ~180 s, so there is no long-lived connection to go stale.
"""
from __future__ import annotations

import asyncio
import struct
from typing import Any

UNIT_ID = 0xFF
CONNECT_TIMEOUT = 3.0
READ_TIMEOUT = 3.0
ATTEMPTS = 3
MAX_PHASE_STRINGS_PER_BLOCK = 6


class LocalError(Exception):
    """Inverter unreachable or returned an unusable reply."""


class LocalIllegalAddress(LocalError):
    """Inverter answered with a Modbus exception (e.g. register not on this model)."""


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def build_request(func: int, address: int, count: int) -> bytes:
    """address is the app's 1-based register number."""
    frame = struct.pack(">BBHH", UNIT_ID, func, address - 1, count)
    return frame + struct.pack("<H", crc16(frame))


def check_reply(reply: bytes, func: int, count: int) -> tuple[int, ...]:
    if len(reply) < 5 or crc16(reply[:-2]) != struct.unpack("<H", reply[-2:])[0]:
        raise LocalError(f"bad CRC/length: {reply.hex()}")
    if reply[1] == func | 0x80:
        raise LocalIllegalAddress(f"modbus exception {reply[2]:#04x}")
    if reply[0] != UNIT_ID or reply[1] != func or reply[2] != count * 2:
        raise LocalError(f"unexpected reply: {reply.hex()}")
    return struct.unpack(f">{count}H", reply[3:3 + count * 2])


class LocalClient:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        # The inverter handles one request at a time; overlapping ones corrupt each other.
        self._lock = asyncio.Lock()

    async def _once(self, func: int, address: int, count: int) -> tuple[int, ...]:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), CONNECT_TIMEOUT
        )
        try:
            writer.write(build_request(func, address, count))
            await writer.drain()
            head = await asyncio.wait_for(reader.readexactly(3), READ_TIMEOUT)
            rest = 2 if head[1] & 0x80 else head[2] + 2
            tail = await asyncio.wait_for(reader.readexactly(rest), READ_TIMEOUT)
            return check_reply(head + tail, func, count)
        finally:
            writer.close()

    async def read(self, func: int, address: int, count: int) -> tuple[int, ...]:
        async with self._lock:
            last: Exception | None = None
            for _ in range(ATTEMPTS):
                try:
                    return await self._once(func, address, count)
                except LocalIllegalAddress:
                    raise
                except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, LocalError) as err:
                    last = err
                    await asyncio.sleep(0.2)
            raise LocalError(f"{self.host}:{self.port} {last!r}")


def _ascii(regs: tuple[int, ...]) -> str:
    return b"".join(struct.pack(">H", r) for r in regs).decode("ascii", "ignore").strip("\x00 ")


def _mac(regs: tuple[int, ...]) -> str:
    return ":".join(f"{b:02X}" for b in b"".join(struct.pack(">H", r) for r in regs))


def _s16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def _u32(lo: int, hi: int) -> int:
    return hi * 65536 + lo  # the inverter sends the low word first


_CURRENT = {1: 0.01, 2: 0.1, 3: 1.0}
_VOLT = {1: 0.01, 2: 0.1, 3: 1.0}
_WATT = {1: 0.1, 2: 1.0, 3: 10.0, 4: 100.0, 5: 1000.0, 6: 10000.0, 7: 100000.0}
_WH = {1: 0.001, 2: 0.01, 3: 0.1, 4: 1.0, 5: 10.0, 6: 100.0, 7: 1000.0}


def decode_scales(raw: int) -> dict[str, float]:
    """Register 40995 packs the scale factors; 0 means the model's fixed defaults.

    Defaults match what the app uses (V 0.1, I 0.01, W 1, Wh 1 on 53248/53252); a
    RPI-M6A reports 0 here and its lifetime counter is in plain Wh.
    """
    if not raw:
        return {"v": 0.1, "idc": 0.01, "iac": 0.01, "w": 1.0, "wh": 1.0}
    return {
        "idc": _CURRENT.get((raw & 0x6) >> 1, 0.01),
        "w": _WATT.get((raw & 0x38) >> 3, 1.0),
        "wh": _WH.get((raw & 0x1C0) >> 6, 1.0),
        "iac": _CURRENT.get((raw & 0xC00) >> 10, 0.01),
        "v": _VOLT.get((raw & 0x3000) >> 12, 0.1),
    }


async def read_identity(client: LocalClient) -> dict[str, Any]:
    model = _ascii(await client.read(3, 44032, 8))
    mac = _mac(await client.read(3, 60441, 3))
    return {"model": model, "mac": mac}


async def read_layout(client: LocalClient) -> dict[str, Any]:
    """Config-like values that don't change between polls (valid at night too)."""
    (n_dc,) = await client.read(4, 40987, 1)
    (n_ac,) = await client.read(4, 40988, 1)
    (scale_raw,) = await client.read(4, 40995, 1)
    return {"dc_string_count": n_dc, "ac_phase_count": n_ac, "scales": decode_scales(scale_raw)}


async def read_live(client: LocalClient, layout: dict[str, Any]) -> dict[str, Any]:
    s = layout["scales"]
    n_dc, n_ac = layout["dc_string_count"], layout["ac_phase_count"]
    data: dict[str, Any] = {}

    ac = await client.read(4, 49152, 1 + 4 * n_ac)
    data["current_power"] = ac[0] * s["w"]
    for i in range(n_ac):
        v, c, p = ac[1 + 4 * i], _s16(ac[2 + 4 * i]), _s16(ac[3 + 4 * i])
        data[f"ac{i + 1}_voltage"] = v * s["v"]
        data[f"ac{i + 1}_current"] = c * s["iac"]
        data[f"ac{i + 1}_power"] = p * s["w"]

    done = 0
    while done < n_dc:
        chunk = min(MAX_PHASE_STRINGS_PER_BLOCK, n_dc - done)
        dc = await client.read(4, 45057 + 3 * done, 3 * chunk)
        for j in range(chunk):
            idx = done + j + 1
            data[f"dc{idx}_voltage"] = dc[3 * j] * s["v"]
            data[f"dc{idx}_current"] = dc[3 * j + 1] * s["idc"]
            data[f"dc{idx}_power"] = dc[3 * j + 2] * s["w"]
        done += chunk

    e = await client.read(4, 53248, 6)
    data["today_energy"] = _u32(e[0], e[1]) * s["wh"] / 1000
    data["lifetime_energy"] = _u32(e[4], e[5]) * s["wh"] / 1000
    return data
