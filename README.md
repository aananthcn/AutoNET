# AutoNET — Vehicle Network Definition

AutoNET stores CAN DBC definitions, setup scripts, and bridge tooling required to build a simulated vehicle network for projects such as **VHAL-Core**, **IVI**, and **ClusterUI**.

The network models two ECUs (`TestECU` transmitter, `ClusterECU` receiver) communicating over virtual CAN interfaces that can optionally be bridged to real hardware.

Supported hardware adapters are documented in [DEVICES.md](DEVICES.md):

| Device | Type | Channels | Notes |
|---|---|---|---|
| **Waveshare USB-CAN-B** | USB dongle | 2 | Industrial isolation, no driver needed on Linux — see [Waveshare wiki](https://www.waveshare.com/wiki/USB-CAN-B#Software) |
| **SmartElex 2-CH CAN HAT+** | Raspberry Pi HAT | 2 | MCP2515 via SPI, device tree overlay |
| **Canalyst-II** | USB dongle | 2 | Used by `can-bridge.py` via `canalystii` Python library |

---

## Contents

- [Repository Layout](#repository-layout)
- [Prerequisites](#prerequisites)
- [SavvyCAN — Install and Build](#savvycan--install-and-build)
- [Concept and Setup](#concept-and-setup)
  - [Virtual CAN Nodes](#virtual-can-nodes)
  - [CAN Message Frames and Signals](#can-message-frames-and-signals-autonet-dbc)
  - [Bridge: vcan ↔ Hardware](#bridge-vcan--hardware-canalyst-ii)
  - [Sending and Receiving CAN Messages](#sending-and-receiving-can-messages)
- [AutoNET Simulator](#autonet-simulator)
- [Workflow Summary](#workflow-summary)
- [Extending the DBC](#extending-the-dbc)

---

## Repository Layout

```
AutoNET/
├── ARCHITECTURE.md              # CAN network design — ECUs, message frames, signal tables
├── DEVICES.md                   # Hardware adapter setup (USB-CAN-B, SmartElex HAT+, Canalyst-II)
├── config/
│   └── systemd/                 # systemd-networkd unit files for persistent CAN interface bring-up
├── networks/
│   └── CAN/
│       └── AutoNET.dbc          # CAN database — all message frames & signals
├── scripts/
│   ├── can-bridge.py            # Full bridge: vcan0/1 <=> Canalyst-II CAN1/2
│   └── can-test.py              # Interactive tool: bridge + direct device send/monitor
└── simulator/
    ├── README.md                # Simulator documentation
    ├── can-sim.py               # CAN simulator — DBC-driven frame generation
    └── usecases/                # Use-case JSON configs (basic_cluster_ui, rvc_usecase, …)
```

---

## Prerequisites

### System packages

```bash
sudo apt update
sudo apt install -y \
    can-utils \          # cansend, candump, cangen, canplayer
    python3-pip \
    git cmake ninja-build \
    qt6-base-dev qt6-serialbus-dev \   # SavvyCAN build deps
    libqt6websockets6-dev
```

### Python packages

```bash
pip3 install python-can canalystii
```

`python-can` provides the `can.Bus` abstraction; `canalystii` is the vendor driver for the Canalyst-II USB CAN analyser.

### Kernel module

The `vcan` kernel module must be available. On Ubuntu/Debian it ships with `linux-modules-extra-$(uname -r)`:

```bash
sudo apt install linux-modules-extra-$(uname -r)
sudo modprobe vcan
```

---

## SavvyCAN — Install and Build

SavvyCAN is a cross-platform CAN bus analysis GUI with DBC import, graphing, and scripting support.

### Option A — AppImage (fastest)

Download the latest AppImage from the [SavvyCAN releases page](https://github.com/collin80/SavvyCAN/releases), then:

```bash
chmod +x SavvyCAN-*.AppImage
./SavvyCAN-*.AppImage
```

### Option B — Build from source

```bash
git clone https://github.com/collin80/SavvyCAN.git
cd SavvyCAN
mkdir build && cd build
cmake .. -G Ninja -DCMAKE_BUILD_TYPE=Release
ninja
sudo ninja install          # installs to /usr/local/bin/SavvyCAN
```

### Connecting SavvyCAN to a virtual CAN interface

1. Start SavvyCAN.
2. Go to **Connection → Open Connection Window**.
3. Click **Add New Device Connection**.
4. Select **SocketCAN** from the driver list.
5. Enter the interface name (`vcan0`, `vcan1`, etc.) and click **OK**.
6. Tick the connection checkbox to activate it.

### Loading the DBC file

1. Go to **DBC Files → Load DBC File**.
2. Browse to `networks/CAN/AutoNET.dbc` and open it.

Signal values now decode automatically in the **Received Frames** and **Graph** views.

---

## Concept and Setup

### Virtual CAN Nodes

Virtual CAN interfaces (`vcan0`, `vcan1`, …) are software loopback nodes that mirror the physical channels of a hardware CAN adapter. Each vcan interface maps one-to-one to a hardware channel:

```
vcan0  <──────────────>  CAN1  (e.g. Waveshare USB-CAN-B ch1 / Canalyst-II ch0)
vcan1  <──────────────>  CAN2  (e.g. Waveshare USB-CAN-B ch2 / Canalyst-II ch1)
```

This mapping is what `can-bridge.py` implements — it creates and bridges both interfaces automatically. Tools like SavvyCAN, CANgaroo, and `candump` connect to `vcan0`/`vcan1` and transparently see traffic from the physical bus.

#### Create vcan0 and vcan1 (with hardware bridge)

The easiest way is to run the bridge script, which creates both interfaces and starts bridging immediately:

```bash
python3 scripts/can-bridge.py      # creates vcan0/vcan1 and bridges to Canalyst-II CAN1/CAN2
```

#### Create interfaces manually (without hardware)

Use this when you want virtual nodes for software-only testing (no hardware adapter needed):

```bash
sudo modprobe vcan

sudo ip link add dev vcan0 type vcan && sudo ip link set up vcan0   # mirrors CAN1
sudo ip link add dev vcan1 type vcan && sudo ip link set up vcan1   # mirrors CAN2
```

#### Verify

```bash
ip link show type vcan
```

Both interfaces should appear as `UP,RUNNING`.

#### Tear down

```bash
sudo ip link set down vcan0 && sudo ip link delete vcan0
sudo ip link set down vcan1 && sudo ip link delete vcan1
```

### CAN Message Frames and Signals (AutoNET DBC)

Full signal definitions, bit layouts, scale/offset tables, and enum value maps are in the **[CAN Network Design](ARCHITECTURE.md#can-network-design)** section of `ARCHITECTURE.md`.

### Bridge: vcan ↔ Hardware (Canalyst-II)

The Canalyst-II exposes two physical CAN channels (CAN1, CAN2). The bridge script maps them to two virtual interfaces:

```
vcan0  <──────────────>  CAN1  (Canalyst-II ch0)
vcan1  <──────────────>  CAN2  (Canalyst-II ch1)
```

#### Run the full bridge

```bash
python3 scripts/can-bridge.py
```

The script:
1. Creates and brings up `vcan0` and `vcan1` automatically.
2. Initialises both Canalyst-II channels at 500 kbps.
3. Starts four forwarding threads (one per direction per channel).
4. Displays a live counter (`TX / RX / LastID`) for each channel.

Press **Ctrl+C** to stop. The bridge cleans up all resources on exit.

#### Run the simple one-way test bridge (hardware → vcan0 only)

```bash
python3 scripts/can-test.py
```

Useful for sniffing a real bus without injecting anything back.

### Sending and Receiving CAN Messages

#### Using can-utils (command line)

**Send a raw frame (extended ID):**

```bash
# DrivetrainStatus: Speed=100 km/h (raw=1000=0x03E8), RPM=2000 (raw=8000=0x1F40),
#                   Gear=DRIVE (8), Throttle=25% (raw=63)
cansend vcan0 00000040#E803401F08003F00
```

**Decode: build the 8-byte payload manually**

| Byte | Value | Meaning |
|---|---|---|
| 0–1 | `E8 03` | Speed raw = 0x03E8 = 1000 → 1000 × 0.1 = 100 km/h |
| 2–3 | `40 1F` | RPM raw  = 0x1F40 = 8000 → 8000 × 0.25 = 2000 rpm |
| 4–5 | `08 00` | Gear raw = 8 → DRIVE |
| 6   | `3F`   | Throttle raw = 63 → 63 × 0.4 = 25.2 % |
| 7   | `00`   | padding |

**Receive all frames:**

```bash
candump vcan0
```

**Receive with DBC decoding (cantools):**

```bash
pip3 install cantools
python3 - <<'EOF'
import cantools, can

db  = cantools.database.load_file('networks/CAN/AutoNET.dbc')
bus = can.Bus(interface='socketcan', channel='vcan0', receive_own_messages=True)
while True:
    msg = bus.recv()
    try:
        decoded = db.decode_message(msg.arbitration_id, msg.data)
        print(f"0x{msg.arbitration_id:03X}  {decoded}")
    except Exception:
        pass
EOF
```

#### Send a VehicleStatus warning frame

Turn on `CheckEngine` (bit 10) and `LowFuel` (bit 11) → bits 10+11 set = 0x0C00:

```bash
# Byte 0 = 0x00, Byte 1 = 0x0C  (bits 8–15 in little-endian layout)
cansend vcan0 00000043#00000000000C0000
```

#### Generate continuous traffic for testing

```bash
cangen vcan0 -e -g 100 -I 40 -L 8   # 10 fps extended frames on ID 0x40
```

---

## AutoNET Simulator

`simulator/can-sim.py` sends DBC-encoded CAN frames with realistic varying signal values at configurable periodicities — no real ECU required. It auto-starts `can-bridge.py` if the hardware bridge is not already running.

```bash
python3 simulator/can-sim.py \
    --dbcfile networks/CAN/AutoNET.dbc \
    --usecase simulator/usecases/basic_cluster_ui.json
```

Supports **scenario-based testing** — a use-case JSON can define a sequence of timed phases, each with signal overrides (e.g. lock `Gear=REVERSE` for 15 s to trigger a rear-view camera).

For full documentation, CLI options, use-case format, and architecture decisions see **[simulator/README.md](simulator/README.md)**.

---

## Workflow Summary

```
1. sudo bash scripts/can-setup.sh          # bring up vcan0

2. python3 scripts/can-bridge.py           # (optional) bridge to real hardware

3. ./SavvyCAN.AppImage                     # open GUI
   └─ Connection → SocketCAN → vcan0
   └─ DBC Files  → networks/CAN/AutoNET.dbc

4. cansend vcan0 00000040#...              # inject test frames
   candump vcan0                           # monitor traffic
```

---

## Extending the DBC

To add a new message or signal, edit `networks/CAN/AutoNET.dbc` following the patterns already there:

```
BO_ <DBC_ID> <MessageName>: <DLC_bytes> <TransmitterECU>
   SG_ <SignalName> : <startBit>|<length>@<byteOrder><signedness> (<factor>,<offset>) [<min>|<max>] "<unit>" <ReceiverECU>
```

- `DBC_ID` for extended frames = `0x80000000 | <29-bit CAN ID>`
- `@1+` = little-endian unsigned; `@1-` = little-endian signed; `@0+` = big-endian unsigned
- Reload the DBC in SavvyCAN after saving to see the new signals decoded live.
