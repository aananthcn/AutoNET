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

## Repository Layout

```
AutoNET/
├── DEVICES.md                   # Hardware adapter setup (USB-CAN-B, SmartElex HAT+, Canalyst-II)
├── networks/
│   └── CAN/
│       └── AutoNET.dbc          # CAN database — all message frames & signals
└── scripts/
    ├── can-setup.sh             # Create a single vcan0 interface
    ├── can-bridge.py            # Full bridge: vcan0/1 <=> Canalyst-II CAN1/2
    └── can-test.py              # Simple one-way bridge (hardware → vcan0)
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

## Virtual CAN Nodes

### Create a single vcan0 node

```bash
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set up vcan0
```

Or use the provided script:

```bash
bash scripts/can-setup.sh
```

### Create additional nodes (vcan1, vcan2 …)

```bash
sudo ip link add dev vcan1 type vcan && sudo ip link set up vcan1
sudo ip link add dev vcan2 type vcan && sudo ip link set up vcan2
```

### Verify

```bash
ip link show type vcan
```

### Tear down

```bash
sudo ip link set down vcan0 && sudo ip link delete vcan0
```

---

## CAN Message Frames and Signals (AutoNET DBC)

All messages use **extended (29-bit) CAN IDs** (`TestECU` is the transmitter, `ClusterECU` is the receiver for all frames).

### Message overview

| Message | CAN ID | Bytes | Source | Description |
|---|---|---|---|---|
| `DrivetrainStatus` | 0x40 | 8 | TestECU | Speed, RPM, gear, throttle |
| `EngineHealth`     | 0x41 | 8 | TestECU | Coolant, oil, battery, load |
| `FuelRange`        | 0x42 | 8 | TestECU | Fuel level and estimated range |
| `VehicleStatus`    | 0x43 | 8 | TestECU | Indicator & warning bit-flags |

> The DBC stores IDs with bit 31 set (`0x8000_0040` etc.) to flag extended frames — the actual on-wire ID is the lower 29 bits.

---

### DrivetrainStatus (0x40)

| Signal | Bits | Scale | Offset | Range | Unit |
|---|---|---|---|---|---|
| `Speed_kmh`   | 0–15  | 0.1  | 0 | 0–250   | km/h |
| `EngineRPM`   | 16–31 | 0.25 | 0 | 0–8000  | rpm  |
| `Gear`        | 32–47 | 1    | 0 | 0–4096  | —    |
| `ThrottlePos` | 48–55 | 0.4  | 0 | 0–100   | %    |

`Gear` value map: `0=UNKNOWN 1=NEUTRAL 2=REVERSE 4=PARK 8=DRIVE 16–4096=GEAR_1…GEAR_9`

---

### EngineHealth (0x41)

| Signal | Bits | Scale | Offset | Range | Unit |
|---|---|---|---|---|---|
| `CoolantTemp`    | 0–7   | 1   | −40 | −40–120 | °C  |
| `OilPressure`    | 8–15  | 0.1 | 0   | 0–10    | bar |
| `BatteryVoltage` | 16–23 | 0.1 | 0   | 0–15    | V   |
| `EngineLoad`     | 24–31 | 0.4 | 0   | 0–100   | %   |

---

### FuelRange (0x42)

| Signal | Bits | Scale | Offset | Range | Unit |
|---|---|---|---|---|---|
| `FuelLevel_pct` | 0–7  | 0.4 | 0 | 0–100 | %  |
| `Range_km`      | 8–23 | 1   | 0 | 0–800 | km |

---

### VehicleStatus (0x43)

Each signal occupies 1 bit (`0=OFF/CLOSED/OK`, `1=ON/OPEN/WARN`):

| Bit | Signal | Values |
|---|---|---|
| 0  | `TurnLeft`       | OFF / ON   |
| 1  | `TurnRight`      | OFF / ON   |
| 2  | `HandBrake`      | OFF / ON   |
| 3  | `DoorOpen_RF`    | CLOSED / OPEN |
| 4  | `DoorOpen_LF`    | CLOSED / OPEN |
| 5  | `DoorOpen_RR`    | CLOSED / OPEN |
| 6  | `DoorOpen_LR`    | CLOSED / OPEN |
| 7  | `DoorOpen_Bonnet`| CLOSED / OPEN |
| 8  | `DoorOpen_Boot`  | CLOSED / OPEN |
| 9  | `DoorOpen_Top`   | CLOSED / OPEN |
| 10 | `CheckEngine`    | OK / WARN  |
| 11 | `LowFuel`        | OK / WARN  |
| 12 | `SeatBelt`       | OK / WARN  |
| 13 | `HighBeam`       | OK / WARN  |

---

## Bridge: vcan ↔ Hardware (Canalyst-II)

The Canalyst-II exposes two physical CAN channels (CAN1, CAN2). The bridge script maps them to two virtual interfaces:

```
vcan0  <──────────────>  CAN1  (Canalyst-II ch0)
vcan1  <──────────────>  CAN2  (Canalyst-II ch1)
```

### Run the full bridge

```bash
python3 scripts/can-bridge.py
```

The script:
1. Creates and brings up `vcan0` and `vcan1` automatically.
2. Initialises both Canalyst-II channels at 500 kbps.
3. Starts four forwarding threads (one per direction per channel).
4. Displays a live counter (`TX / RX / LastID`) for each channel.

Press **Ctrl+C** to stop. The bridge cleans up all resources on exit.

### Run the simple one-way test bridge (hardware → vcan0 only)

```bash
python3 scripts/can-test.py
```

Useful for sniffing a real bus without injecting anything back.

---

## Sending and Receiving CAN Messages

### Using can-utils (command line)

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

### Send a VehicleStatus warning frame

Turn on `CheckEngine` (bit 10) and `LowFuel` (bit 11) → bits 10+11 set = 0x0C00:

```bash
# Byte 0 = 0x00, Byte 1 = 0x0C  (bits 8–15 in little-endian layout)
cansend vcan0 00000043#00000000000C0000
```

### Generate continuous traffic for testing

```bash
cangen vcan0 -e -g 100 -I 40 -L 8   # 10 fps extended frames on ID 0x40
```

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
