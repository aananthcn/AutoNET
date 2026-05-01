# AutoNET — CLAUDE.md

## Project Overview

AutoNET is a **vehicle network builder**, similar in spirit to tools like PREEvision. The goal is to provide a full network design and configuration environment for automotive-grade networks.

**Planned network support (in order):**
1. **CAN** — current focus; DBC definitions, virtual interfaces, hardware bridge tooling
2. **Ethernet** — next planned network type
3. **PCIe** — long-term roadmap

The current implementation starts with **SavvyCAN** as the CAN base, modelling two ECUs (`TestECU` transmitter, `ClusterECU` receiver) over virtual CAN interfaces that can optionally be bridged to real hardware. This serves as the foundation while the broader network builder is developed.

---

## Repository Layout

```
AutoNET/
├── CLAUDE.md                        # This file
├── ARCHITECTURE.md                  # CAN network design — ECUs, message frames, signal tables
├── DEVICES.md                       # Hardware adapter setup (USB-CAN-B, SmartElex HAT+, Canalyst-II)
├── config/
│   └── systemd/
│       ├── can0.network             # systemd-networkd unit — brings up can0 at boot
│       └── can1.network             # systemd-networkd unit — brings up can1 at boot
├── networks/
│   └── CAN/
│       └── AutoNET.dbc              # CAN database — all message frames & signals
├── scripts/
│   ├── can-bridge.py                # Full bridge: vcan0/1 <=> Canalyst-II CAN1/2
│   └── can-test.py                  # Interactive tool: bridge + direct device send/monitor
└── simulator/
    ├── can-sim.py                   # CAN simulator — sends DBC-encoded frames with varying data
    └── usecases/
        ├── basic_cluster_ui.json   # Use-case: all 4 AutoNET messages at automotive rates
        └── rvc_usecase.json        # Use-case: normal driving → reverse gear cycle (RVC test)
```

---

## CAN Network Architecture

All messages use **extended (29-bit) CAN IDs**. The DBC stores IDs with bit 31 set (e.g. `0x8000_0040`) to flag extended frames; the actual on-wire ID is the lower 29 bits.

### Messages

| Message | CAN ID | Bytes | Description |
|---|---|---|---|
| `DrivetrainStatus` | 0x40 | 8 | Speed, RPM, gear, throttle |
| `EngineHealth`     | 0x41 | 8 | Coolant, oil, battery, load |
| `FuelRange`        | 0x42 | 8 | Fuel level and estimated range |
| `VehicleStatus`    | 0x43 | 8 | Indicator & warning bit-flags |

### Signal encoding summary

- **DrivetrainStatus (0x40):** `Speed_kmh` (×0.1 km/h), `EngineRPM` (×0.25 rpm), `Gear` (enum), `ThrottlePos` (×0.4 %)
- **EngineHealth (0x41):** `CoolantTemp` (×1 −40 offset °C), `OilPressure` (×0.1 bar), `BatteryVoltage` (×0.1 V), `EngineLoad` (×0.4 %)
- **FuelRange (0x42):** `FuelLevel_pct` (×0.4 %), `Range_km` (×1 km)
- **VehicleStatus (0x43):** 14 single-bit flags (turn signals, doors, warnings, etc.)

Full signal bit layouts and value maps are in `ARCHITECTURE.md`.

---

## Supported Hardware

| Device | Type | Channels | Notes |
|---|---|---|---|
| **Waveshare USB-CAN-B** | USB dongle | 2 | `gs_usb` kernel driver, no install needed on Linux |
| **SmartElex 2-CH CAN HAT+** | Raspberry Pi HAT | 2 | MCP2515 via SPI1, device tree overlay required |
| **Canalyst-II** | USB dongle | 2 | Used by `can-bridge.py` via `canalystii` Python library |

Hardware setup procedures are in `DEVICES.md`.

---

## Prerequisites

### System packages

```bash
sudo apt update
sudo apt install -y can-utils python3-pip git cmake ninja-build \
    qt6-base-dev qt6-serialbus-dev libqt6websockets6-dev
```

### Python packages

```bash
pip3 install python-can canalystii cantools
```

### Kernel module

```bash
sudo apt install linux-modules-extra-$(uname -r)
sudo modprobe vcan
```

---

## Common Commands

### Bring up virtual CAN

```bash
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan && sudo ip link set up vcan0
sudo ip link add dev vcan1 type vcan && sudo ip link set up vcan1
```

Or let `can-bridge.py` create and bridge both interfaces automatically:

### Bridge to Canalyst-II hardware

```bash
python3 scripts/can-bridge.py      # full bidirectional bridge: vcan0/1 <=> CAN1/2
python3 scripts/can-test.py        # interactive tool: bridge + direct device send/monitor
```

### can-test.py — interactive commands

`can-test.py` runs a CAN1→vcan0 bridge in the background and provides an interactive prompt with two modes:

| Command | Description |
|---|---|
| `m -b` | Monitor vcan0 (bridge output) via `candump` |
| `s -b <frame>` | Send a frame to vcan0 via `cansend` |
| `m -d 1` | Monitor CAN1 via vcan0 (CAN1 RX is already bridged there) |
| `m -d 2` | Monitor CAN2 directly from the Canalyst-II |
| `s -d 1 <frame>` | Send a frame directly to Canalyst-II CAN1 |
| `s -d 2 <frame>` | Send a frame directly to Canalyst-II CAN2 |

Frame format follows `cansend` convention: `<id>#<data>` — use 8 hex chars for extended IDs, e.g. `00000040#E803401F08003F00`.

Up/down arrow keys cycle through command history.

**Physical loopback behaviour (Canalyst-II test setup):**
CAN1 and CAN2 on the Canalyst-II are physically wired together (CAN1_H↔CAN2_H, CAN1_L↔CAN2_L). Traffic flows:
- `s -d 2` → CAN2 TX → loopback → CAN1 RX → vcan0 (visible in SavvyCAN/CANgaroo)
- `s -d 1` → CAN1 TX → loopback → CAN2 RX → vcan0 (also forwarded, visible the same way)

Both channels forward received frames to vcan0, so all traffic is visible on the same interface regardless of which channel transmitted it.

**Implementation notes for can-test.py:**
- All Canalyst-II access goes through a single `CanalystDevice` object (two `can.Bus` instances on the same device cause `[Errno 16] Resource busy`)
- Two daemon threads own all `device.receive()` calls — one per channel — mirroring `can-bridge.py`'s threading model; the main thread calls `device.send()` directly
- Do not serialise send and receive through a single thread or lock: the receive timeout (~10 ms) starves the send path and causes CAN ACK failures
- On exit, `os._exit(0)` is used to bypass Python GC, which triggers a libusb segfault if the device is still held
- If the device is not plugged in, `CanalystDevice()` raises an exception; this is caught and a diagnostic message is printed before exiting

### Send / receive (can-utils)

```bash
cansend vcan0 00000040#E803401F08003F00   # DrivetrainStatus: 100 km/h, 2000 rpm, DRIVE, 25%
candump vcan0                              # receive all frames
cangen vcan0 -e -g 100 -I 40 -L 8        # generate continuous test traffic
```

### DBC-decoded receive (Python)

```bash
pip3 install cantools
python3 - <<'EOF'
import cantools, can
db  = cantools.database.load_file('networks/CAN/AutoNET.dbc')
bus = can.Bus(interface='socketcan', channel='vcan0', receive_own_messages=True)
while True:
    msg = bus.recv()
    try:
        print(f"0x{msg.arbitration_id:03X}  {db.decode_message(msg.arbitration_id, msg.data)}")
    except Exception:
        pass
EOF
```

### CAN Simulator

`can-sim.py` generates realistic varying signal values from a DBC file and sends encoded CAN frames at configurable periodicities. It is the primary tool for driving a cluster display or any CAN receiver with live-looking data.

#### Usage

```bash
# Send all DBC messages on vcan0 at 100 ms default period
python3 simulator/can-sim.py --dbcfile networks/CAN/AutoNET.dbc

# Use a specific use-case config (recommended)
python3 simulator/can-sim.py \
    --dbcfile networks/CAN/AutoNET.dbc \
    --usecase simulator/usecases/basic_cluster_ui.json
```

#### Use-case JSON format

Use-case files live in `simulator/usecases/`. Each file specifies which messages to send, at what rate, and on which interface:

```json
{
  "description": "...",
  "interface": "vcan0",
  "messages": [
    { "name": "DrivetrainStatus", "frame_id": "0x40", "period_ms": 10   },
    { "name": "EngineHealth",     "frame_id": "0x41", "period_ms": 100  },
    { "name": "FuelRange",        "frame_id": "0x42", "period_ms": 1000 },
    { "name": "VehicleStatus",    "frame_id": "0x43", "period_ms": 100  }
  ]
}
```

Fields `name` and `frame_id` are both optional but at least one must be present. `interface` can be overridden per message.

#### Signal value generation rules

| Signal type | Generation strategy |
|---|---|
| Enum (choices list) | Random pick from defined values; changes every 10–50 ticks |
| Boolean (2 choices) | 90 % probability of the lower / "normal" state (off/closed/ok) |
| Continuous (min/max) | Sinusoidal oscillation within ±30 % of mid-range; unique frequency per signal |
| Float scale (e.g. ×0.1) | Returns `float`; integer scale returns `int` |

Factor and offset from the DBC are applied automatically by `cantools` during encoding.

#### Scenario support

A use-case JSON may include an optional `scenario` block that sequences signal overrides across timed phases:

```json
"scenario": {
  "description": "...",
  "cyclic": true,
  "phases": [
    { "name": "normal_driving", "description": "...", "duration_s": 4 },
    { "name": "reverse",        "description": "...", "duration_s": 15,
      "signal_overrides": { "DrivetrainStatus": { "Gear": "REVERSE" } } }
  ]
}
```

- `signal_overrides` maps message name → signal name → fixed physical value or choice string
- Signals not listed in `signal_overrides` continue to be generated normally
- Phase transitions are printed to stdout as they occur
- `cyclic: true` repeats the phase sequence indefinitely

#### Extending the simulator

- Add new use-case JSON files under `simulator/usecases/` for different test scenarios
- Future network simulators follow the same naming pattern: `eth-sim.py`, `grpc-sim.py`, etc.

---

### Tear down

```bash
sudo ip link set down vcan0 && sudo ip link delete vcan0
```

---

## Extending the DBC

Edit `networks/CAN/AutoNET.dbc` following this pattern:

```
BO_ <DBC_ID> <MessageName>: <DLC_bytes> <TransmitterECU>
   SG_ <SignalName> : <startBit>|<length>@<byteOrder><signedness> (<factor>,<offset>) [<min>|<max>] "<unit>" <ReceiverECU>
```

- `DBC_ID` for extended frames = `0x80000000 | <29-bit CAN ID>`
- `@1+` = little-endian unsigned; `@1-` = little-endian signed; `@0+` = big-endian unsigned
- Reload the DBC in SavvyCAN after saving to see decoded signals live.

---

## SavvyCAN

CAN bus analysis GUI with DBC import, graphing, and scripting. Use the AppImage for fastest setup:

```bash
chmod +x SavvyCAN-*.AppImage && ./SavvyCAN-*.AppImage
```

Connect: **Connection → Open Connection Window → Add New Device Connection → SocketCAN → vcan0**

Load DBC: **DBC Files → Load DBC File → networks/CAN/AutoNET.dbc**

---

## Workflow Summary

```
1. python3 scripts/can-bridge.py           # brings up vcan0/vcan1 and bridges to hardware
3. ./SavvyCAN.AppImage                     # open GUI, connect to vcan0, load AutoNET.dbc
4. cansend vcan0 00000040#...              # inject test frames
   candump vcan0                           # monitor traffic
```
