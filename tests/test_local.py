"""Self-check for the local Modbus client against an emulated inverter.

Run with: python3 tests/test_local.py   (or pytest). No homeassistant needed.
Register values are the ones read from a real RPI-M6A (night: live values 0).
"""
import asyncio
import importlib.util
import struct
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "local", Path(__file__).resolve().parent.parent / "custom_components" / "delta_solar" / "local.py"
)
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)

REGS = {
    **{44032 + i: v for i, v in enumerate((21072, 18733, 19766, 16672, 8224, 8224, 8224, 8224))},
    **{60441 + i: v for i, v in enumerate((35034, 6769, 48320))},
    40987: 2, 40988: 3, 40995: 0,
    **{49152 + i: 0 for i in range(13)},
    **{45057 + i: 0 for i in range(6)},
    **{53248 + i: v for i, v in enumerate((22800, 0, 40210, 0, 5754, 731))},
}


async def serve(reader, writer, regs, drop=None):
    try:
        req = await reader.readexactly(8)
        assert L.crc16(req[:-2]) == struct.unpack("<H", req[-2:])[0], "request CRC"
        unit, func, addr, n = struct.unpack(">BBHH", req[:6])
        assert unit == 0xFF
        if drop and drop[0]:
            writer.close(); return
        addr += 1
        if any(addr + i not in regs for i in range(n)):
            body = bytes([unit, func | 0x80, 2])
        else:
            body = bytes([unit, func, n * 2]) + b"".join(struct.pack(">H", regs[addr + i]) for i in range(n))
        writer.write(body + struct.pack("<H", L.crc16(body)))
        await writer.drain()
    finally:
        writer.close()


async def main():
    # known-answer: the app's frame for model read (func 3, addr 44032 x8)
    assert L.build_request(3, 44032, 8)[:6].hex() == "ff03abff0008"
    assert L.crc16(bytes.fromhex("010300000001")) == 0x0A84  # classic Modbus vector (84 0A on wire)

    drop = [False]
    srv = await asyncio.start_server(lambda r, w: serve(r, w, REGS, drop), "127.0.0.1", 0)
    c = L.LocalClient("127.0.0.1", srv.sockets[0].getsockname()[1])

    ident = await L.read_identity(c)
    assert ident == {"model": "RPI-M6A", "mac": "88:DA:1A:71:BC:C0"}, ident

    layout = await L.read_layout(c)
    assert (layout["dc_string_count"], layout["ac_phase_count"]) == (2, 3)
    live = await L.read_live(c, layout)
    assert live["today_energy"] == 22.8 and live["lifetime_energy"] == 47912.570, live
    assert live["current_power"] == 0 and live["dc2_voltage"] == 0 and live["ac3_power"] == 0

    # daytime values: scales and signedness
    REGS.update({49152: 5300, 49153: 2301, 49154: 770, 49155: 1766, 49156: 500,
                 49157: 2298, 49158: 765, 49159: 1760, 49160: 500,
                 49161: 2305, 49162: 0xFFFF, 49163: 0xFFF6, 49164: 500,
                 45057: 6123, 45058: 480, 45059: 2939})
    live = await L.read_live(c, layout)
    assert live["current_power"] == 5300 and abs(live["ac1_voltage"] - 230.1) < 1e-9
    assert live["ac1_current"] == 7.7 and live["ac3_current"] == -0.01 and live["ac3_power"] == -10
    assert abs(live["dc1_voltage"] - 612.3) < 1e-9 and live["dc1_current"] == 4.8 and live["dc1_power"] == 2939

    # register absent on this model -> distinct error, not retried 3x
    try:
        await c.read(4, 1538, 1)
        raise SystemExit("expected LocalIllegalAddress")
    except L.LocalIllegalAddress:
        pass

    # connection drop (AP/bridge reconnect): errors out, then recovers on next poll
    drop[0] = True
    try:
        await c.read(4, 40987, 1)
        raise SystemExit("expected LocalError")
    except L.LocalError:
        pass
    drop[0] = False
    assert await c.read(4, 40987, 1) == (2,)

    # nothing listening at all
    srv.close(); await srv.wait_closed()
    try:
        await c.read(4, 40987, 1)
        raise SystemExit("expected LocalError")
    except L.LocalError:
        pass

    # scale-factor register: W x10, Wh x0.1... bits: idc=2<<1, w=3<<3, wh=3<<6, iac=2<<10, v=2<<12
    s = L.decode_scales((2 << 1) | (3 << 3) | (3 << 6) | (2 << 10) | (2 << 12))
    assert s == {"idc": 0.1, "w": 10.0, "wh": 0.1, "iac": 0.1, "v": 0.1}, s
    print("local ok")


def test_local():
    asyncio.run(main())


if __name__ == "__main__":
    test_local()
