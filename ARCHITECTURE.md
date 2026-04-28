# AutoNET Architecture

---

## CAN Network Design

All messages use **extended (29-bit) CAN IDs**. `TestECU` is the transmitter and `ClusterECU` is the receiver for all frames.

> The DBC stores IDs with bit 31 set (`0x8000_0040` etc.) to flag extended frames — the actual on-wire ID is the lower 29 bits.

### Message Overview

| Message | CAN ID | Bytes | Source | Description |
|---|---|---|---|---|
| `DrivetrainStatus` | 0x40 | 8 | TestECU | Speed, RPM, gear, throttle |
| `EngineHealth`     | 0x41 | 8 | TestECU | Coolant, oil, battery, load |
| `FuelRange`        | 0x42 | 8 | TestECU | Fuel level and estimated range |
| `VehicleStatus`    | 0x43 | 8 | TestECU | Indicator & warning bit-flags |

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
| 0  | `TurnLeft`        | OFF / ON      |
| 1  | `TurnRight`       | OFF / ON      |
| 2  | `HandBrake`       | OFF / ON      |
| 3  | `DoorOpen_RF`     | CLOSED / OPEN |
| 4  | `DoorOpen_LF`     | CLOSED / OPEN |
| 5  | `DoorOpen_RR`     | CLOSED / OPEN |
| 6  | `DoorOpen_LR`     | CLOSED / OPEN |
| 7  | `DoorOpen_Bonnet` | CLOSED / OPEN |
| 8  | `DoorOpen_Boot`   | CLOSED / OPEN |
| 9  | `DoorOpen_Top`    | CLOSED / OPEN |
| 10 | `CheckEngine`     | OK / WARN     |
| 11 | `LowFuel`         | OK / WARN     |
| 12 | `SeatBelt`        | OK / WARN     |
| 13 | `HighBeam`        | OK / WARN     |
