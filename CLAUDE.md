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
├── networks/
│   └── CAN/
│       └── AutoNET.dbc              # CAN database — all message frames & signals
└── scripts/
    ├── can-setup.sh                 # Create a single vcan0 interface
    ├── can-bridge.py                # Full bridge: vcan0/1 <=> Canalyst-II CAN1/2
    └── can-test.py                  # Interactive tool: bridge + direct device send/monitor
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
pip3 install python-can canalystii
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
bash scripts/can-setup.sh          # creates vcan0
# Or manually:
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan && sudo ip link set up vcan0
```

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
1. sudo bash scripts/can-setup.sh          # bring up vcan0
2. python3 scripts/can-bridge.py           # (optional) bridge to real hardware
3. ./SavvyCAN.AppImage                     # open GUI, connect to vcan0, load AutoNET.dbc
4. cansend vcan0 00000040#...              # inject test frames
   candump vcan0                           # monitor traffic
```
