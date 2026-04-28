# Hardware Devices

Reference guide for the CAN hardware adapters used with AutoNET.

---

## Waveshare USB-CAN-B

> Full documentation: [Waveshare USB-CAN-B Wiki](https://www.waveshare.com/wiki/USB-CAN-B#Software)

### Overview

Industrial-grade dual-channel USB-to-CAN adapter with full three-terminal galvanic isolation (USB, CAN1, CAN2). Connects to any host PC over USB and appears as two SocketCAN interfaces on Linux.

### Specifications

| Property | Value |
|---|---|
| Channels | 2 (CAN1, CAN2) |
| Controller | Microchip, 32-bit MIPS M4K core, up to 80 MHz |
| Baud rate | 10 Kbps – 1 Mbps (configurable) |
| Isolation | 2500 VDC — USB, CAN1, CAN2 fully isolated |
| Protocols | CAN 2.0A, CAN 2.0B, CANOpen, SAE J1939, DeviceNet, ICAN, ISO 15765 |
| OS support | Windows XP/7/8/10/11, Linux (Raspberry Pi OS, Ubuntu/Jetson Nano) |
| Connector | USB-B (device side), screw terminal (CAN side) |

### Terminal resistor

The CAN bus requires a 120 Ω termination resistor at **each end** of the bus. On the USB-CAN-B, short the **R+** and **R−** pins with a jumper wire to enable the built-in 120 Ω resistor.

> A bus with missing termination will show high error rates and intermittent frame loss.

---

### Linux Setup

On a modern Linux kernel the USB-CAN-B is recognised automatically by the `gs_usb` kernel module — no manual driver compilation is needed.

#### 1. Plug in and verify detection

```bash
lsusb | grep -i microchip      # adapter should appear
dmesg | tail -20               # look for gs_usb or usbcan
ip link show                   # look for can0, can1
```

#### 2. Bring up both CAN interfaces

```bash
sudo ip link set can0 up type can bitrate 500000
sudo ip link set can1 up type can bitrate 500000
```

Change `500000` to match your bus bitrate (e.g. `250000`, `1000000`).

#### 3. Verify

```bash
ip link show type can
```

Both interfaces should appear as `UP`.

#### 4. Monitor and send traffic

```bash
# Terminal A — receive on CAN1
candump can0

# Terminal B — send on CAN2
cansend can1 00000040#E803401F08003F00
```

#### 5. python-can usage

```python
import can

bus0 = can.Bus(interface='socketcan', channel='can0', bitrate=500000)
bus1 = can.Bus(interface='socketcan', channel='can1', bitrate=500000)

# Send on can1, receive on can0 (when looped back or connected to a peer)
msg = can.Message(arbitration_id=0x40, data=[0xE8,0x03,0x40,0x1F,0x08,0x00,0x3F,0x00],
                  is_extended_id=True)
bus1.send(msg)
received = bus0.recv(timeout=1.0)
```

#### 6. Tear down

```bash
sudo ip link set can0 down
sudo ip link set can1 down
```

---

### Windows Setup (USB-CAN TOOL)

The proprietary **USB-CAN TOOL** GUI runs on Windows and provides sending, receiving, filtering, relay, and real-time logging.

#### Installation

1. Run `USB-CAN TOOLSetup(V9.xx).exe` from the supplied CD or download.
2. The installer bundles three components — select all:
   - **USB-CAN TOOL** (33 MB) — the main GUI
   - **LABVIEW Run Time** (29.4 MB) — required runtime engine
   - **USB driver** (6.6 MB) — Microchip WDF driver
3. Follow the wizard through the VC++ 2008 Redistributable and NI LabVIEW Run-Time Engine 2011 SP1 installation steps.
4. When the Device Driver Installation Wizard appears, click **Next** → **Finish**. The driver status should show **Ready to use**.

#### Connecting the device

1. Plug the USB-CAN-B into the PC.
2. Launch **USB-CAN Tool**.
3. In the **Device** menu, select **USB-CAN2.0** (the dual-channel model — do **not** choose the single-channel "USB-CAN" entry).
4. Go to **Operation → Start(S)** to open the adapter. The title bar updates with the serial number and firmware version.
5. To close: **Operation → Stop(T)**.

#### GUI sections

| Area | Purpose |
|---|---|
| **Send Data** | Set Format (Standard/Extended), Type (Data/Remote), CAN ID (hex), Channel (1 or 2), frame count, send cycle (ms), ID/Data auto-increment |
| **CAN Routing** | Relay frames between CAN1 and CAN2 automatically |
| **ID Filter** | Per-channel allow/block list for received IDs |
| **Statistics** | Frm/s R (receive fps) and Frm/s T (transmit fps) per channel |
| **Data List** | Live scrolling log: Index, Time, Timestamp, Channel, Direction, Frame ID, Type, Format, DLC, Data |

#### Sending a frame

Fill in the **Send Data** area:
- Format: `Extended`
- Type: `Data`
- CAN ID (hex): `00 00 00 40`
- Channel: `1`
- Data (hex): `E8 03 40 1F 08 00 3F 00`
- Send Cycle: `10` ms (for continuous transmission)

Click **Send**. Received frames appear in the Data List in real time.

---

## SmartElex 2-CH CAN HAT+

### Overview

Isolated dual-channel CAN expansion board for Raspberry Pi. Uses two MCP2515 SPI CAN controllers (one per channel) and exposes both as standard SocketCAN interfaces (`can0`, `can1`). Suited for embedding the Raspberry Pi as a CAN node rather than as a USB-attached analyser.

### Compatibility

Raspberry Pi Zero / Zero W / Zero WH / 2B / 3B / 3B+ / 4B / 5.

> When fitting on a Pi 2B/3B/4B/5, use copper standoffs to prevent the CAN terminal block from contacting the HDMI port and causing a short circuit.

### Specifications

| Property | Value |
|---|---|
| Channels | 2 (CAN0, CAN1) |
| CAN controller | MCP2515 × 2 (CAN 2.0B, standard + extended frames) |
| CAN transceiver | SN65HVD230 × 2 |
| Oscillator | 16 MHz |
| SPI bus | SPI1 (default), also supports SPI0 via pad rework |
| Logic voltage | 3.3 V or 5 V — select via jumper (set to **3.3 V** for Raspberry Pi) |
| Input power | 5 V (from 40-pin header) or 7–36 V (external terminal) |
| Isolation | Power isolation + digital signal isolation onboard |
| ESD protection | SM24CANB transient voltage suppressor |
| Terminal resistor | 120 Ω onboard per channel — enable via jumper cap |
| Form factor | Standard HAT+ with EEPROM |

### Default SPI Pin Mapping (BCM numbering)

| Signal | BCM | WPI | Function |
|---|---|---|---|
| MISO | 19 | 24 | SPI1 MISO |
| MOSI | 20 | 28 | SPI1 MOSI |
| SCK  | 21 | 29 | SPI1 SCLK |
| CS_0 | 17 | 0  | CAN0 chip select (SPI1 CE1) |
| INT_0| 22 | 3  | CAN0 interrupt (soldered default) |
| CS_1 | 16 | 27 | CAN1 chip select (SPI1 CE2) |
| INT_1| 13 | 23 | CAN1 interrupt (soldered default) |

> INT_0 and INT_1 are physically soldered to their default BCM pins. Changing them requires resoldering the 0 Ω pad and updating `/boot/firmware/config.txt`.

---

### Raspberry Pi Setup

#### Step 1 — Hardware

1. Power off the Pi.
2. Align the HAT+ to the 40-pin GPIO header and press firmly.
3. Set the **logic voltage jumper to 3.3 V**.
4. Enable the onboard 120 Ω terminal resistors with the jumper caps (required unless your bus already has termination at both ends).

#### Step 2 — Enable SPI

```bash
sudo raspi-config
# Navigate: Interfacing Options → SPI → Yes → OK
sudo reboot
```

Confirm SPI devices appeared:

```bash
ls /dev/spidev*
# Expected: /dev/spidev0.0  /dev/spidev0.1
```

#### Step 3 — Install dependencies

```bash
sudo apt update
sudo apt install -y can-utils
sudo pip3 install RPi.GPIO spidev python-can
```

#### Step 4 — Configure the device tree overlay

Edit the boot config. The path depends on your OS version:

| OS | Config file |
|---|---|
| Raspberry Pi OS (≤ 2022) | `/boot/config.txt` |
| Raspberry Pi OS (≥ 2023) / Pi 5 | `/boot/firmware/config.txt` |

```bash
sudo nano /boot/firmware/config.txt   # adjust path for your OS
```

Add at the end of the file:

```
dtparam=spi=on
dtoverlay=i2c0
dtoverlay=spi1-3cs
dtoverlay=mcp2515,spi1-1,oscillator=16000000,interrupt=22
dtoverlay=mcp2515,spi1-2,oscillator=16000000,interrupt=13
```

Save and reboot:

```bash
sudo reboot
```

#### Step 5 — Verify MCP2515 initialisation

```bash
dmesg | grep spi1
# Expected output:
# [  2.566685] mcp251x spi1.2 can0: MCP2515 successfully initialized.
# [  2.587384] mcp251x spi1.1 can1: MCP2515 successfully initialized.
```

#### Step 6 — Bring up CAN interfaces

```bash
sudo ip link set can0 up type can bitrate 500000
sudo ip link set can1 up type can bitrate 500000
sudo ifconfig can0 txqueuelen 65536
sudo ifconfig can1 txqueuelen 65536
ifconfig          # can0 and can1 should appear as UP,RUNNING
```

#### Step 7 — Test (loopback with single HAT)

Physically bridge the two channels: connect **CAN0_H → CAN1_H** and **CAN0_L → CAN1_L**.

```bash
# Terminal 1 — listen on CAN0
candump can0

# Terminal 2 — send from CAN1
cansend can1 000#11.22.33.44
```

You should see frames appear in Terminal 1.

#### Tear down

```bash
sudo ifconfig can0 down
sudo ifconfig can1 down
```

---

### Troubleshooting

#### SPI devices not visible (`ls /dev/spidev*` empty)

SPI is not enabled. Re-run `sudo raspi-config` and enable SPI under **Interfacing Options**, then reboot.

#### MCP2515 not detected (`dmesg | grep mcp` empty)

Likely causes:
- Wrong oscillator value in `config.txt` (must be `16000000` for this HAT)
- Wrong interrupt pin numbers
- SPI not enabled

Check kernel modules are loaded:

```bash
lsmod | grep spi
# Expected: spi_bcm2835  spidev
```

If missing, load manually:

```bash
sudo modprobe spi_bcm2835
sudo modprobe spidev
```

#### Common error messages

| Error | Likely cause |
|---|---|
| `Cannot find device can0` | Overlay not applied or MCP2515 not detected |
| `spi transfer failed` | HAT not seated properly or wrong SPI bus |
| `mcp251x spi0.0: probe failed` | Wrong oscillator or interrupt pin in config |
| `/dev/spidev*` missing | SPI not enabled in raspi-config |

---

## Device Comparison

| Feature | Waveshare USB-CAN-B | SmartElex 2-CH CAN HAT+ |
|---|---|---|
| Form factor | USB dongle (connects to any PC) | Raspberry Pi HAT |
| Channels | 2 | 2 |
| Isolation | 2500 VDC (full 3-terminal) | Power + signal isolation |
| Linux interface | SocketCAN (`can0`/`can1`) | SocketCAN (`can0`/`can1`) |
| Driver needed | None (gs_usb in kernel) | Device tree overlay (built-in kernel driver) |
| Windows tool | USB-CAN TOOL V9.14 GUI | None (Linux only) |
| Bitrate range | 10 Kbps – 1 Mbps | Up to 1 Mbps (MCP2515 limit) |
| Best use | Desktop / laptop development host | Embedded Pi node on the vehicle bus |
