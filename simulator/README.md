# AutoNET CAN Simulator

`can-sim.py` generates realistic, time-varying CAN frames from a DBC file and sends them on a SocketCAN interface at configurable periodicities. It is the primary tool for driving a cluster display or any CAN receiver node with live-looking data without needing a real ECU.

---

## Contents

- [Quick Start](#quick-start)
- [CLI Options](#cli-options)
- [Use-Case JSON Format](#use-case-json-format)
- [Scenario Support](#scenario-support)
- [Signal Value Generation](#signal-value-generation)
- [Bridge Auto-Start](#bridge-auto-start)
- [Available Use Cases](#available-use-cases)
- [Architecture Decisions](#architecture-decisions)
- [Extending the Simulator](#extending-the-simulator)

---

## Quick Start

```bash
# With hardware bridge (Canalyst-II) — bridge is started automatically if not running
python3 simulator/can-sim.py --dbcfile networks/CAN/AutoNET.dbc \
    --usecase simulator/usecases/basic_cluster_ui.json

# vcan-only (no hardware, no bridge check)
python3 simulator/can-sim.py --dbcfile networks/CAN/AutoNET.dbc \
    --usecase simulator/usecases/basic_cluster_ui.json \
    --no-bridge-check
```

Monitor traffic on the receiving side:

```bash
candump vcan0                              # raw frames
# or on the Raspberry Pi:
candump can0
```

---

## CLI Options

| Option | Required | Description |
|---|---|---|
| `--dbcfile FILE` | Yes | Path to the DBC file to load messages and signals from |
| `--usecase FILE` | No | Path to a use-case JSON config. If omitted, all DBC messages are sent at 100 ms on `vcan0` |
| `--no-bridge-check` | No | Skip the `can-bridge.py` running check — useful for vcan-only testing without hardware |

---

## Use-Case JSON Format

Use-case files live in `simulator/usecases/`. A use-case defines which messages to send, at what rate, and on which interface.

```json
{
  "description": "Human-readable description of the use case",
  "interface": "vcan0",
  "messages": [
    {
      "name": "DrivetrainStatus",
      "frame_id": "0x40",
      "period_ms": 10,
      "description": "Speed, RPM, Gear, Throttle"
    },
    {
      "name": "EngineHealth",
      "frame_id": "0x41",
      "period_ms": 100,
      "description": "Coolant, Oil, Battery, Load"
    }
  ]
}
```

### Field reference

| Field | Level | Required | Description |
|---|---|---|---|
| `description` | top / message / phase | No | Human-readable label (ignored by the simulator) |
| `interface` | top | No | Default SocketCAN interface — overridable per message. Default: `vcan0` |
| `messages[].name` | message | One of name/frame_id | Message name as defined in the DBC |
| `messages[].frame_id` | message | One of name/frame_id | Message CAN ID as hex string (e.g. `"0x40"`) |
| `messages[].period_ms` | message | No | Transmit period in milliseconds. Default: 100 |
| `messages[].interface` | message | No | Per-message interface override |

---

## Scenario Support

A use-case may include an optional `scenario` block that sequences **signal overrides** across named, timed phases. Outside of overrides, all signals continue to be generated normally.

```json
"scenario": {
  "description": "Cycles between normal driving and reverse",
  "cyclic": true,
  "phases": [
    {
      "name": "normal_driving",
      "description": "All signals generated freely",
      "duration_s": 4
    },
    {
      "name": "reverse",
      "description": "Gear locked to REVERSE for RVC activation",
      "duration_s": 15,
      "signal_overrides": {
        "DrivetrainStatus": {
          "Gear": "REVERSE"
        }
      }
    }
  ]
}
```

### Scenario field reference

| Field | Required | Description |
|---|---|---|
| `cyclic` | No | If `true`, the phase sequence repeats indefinitely. Default: `true` |
| `phases[].name` | Yes | Phase identifier — printed to stdout on each transition |
| `phases[].duration_s` | Yes | How long this phase lasts, in seconds |
| `phases[].signal_overrides` | No | `{ "MessageName": { "SignalName": value } }` — values are physical or choice strings |

Override values accept either:
- A **number** — the physical value (factor and offset are applied by cantools during encoding)
- A **string** — a choice name as defined in the DBC (e.g. `"REVERSE"`, `"DRIVE"`)

Phase transitions are printed to stdout as they occur:

```
  [scenario] phase → normal_driving
  [scenario] phase → reverse
```

---

## Signal Value Generation

The simulator reads each signal's metadata from the DBC and applies the following rules:

| Signal type | Strategy |
|---|---|
| **Enum** (choices list, >2 values) | Random pick from defined values; value held for 10–50 ticks before changing |
| **Boolean** (exactly 2 choices) | 90 % probability of the lower / "normal" state (off / closed / ok) |
| **Continuous** (numeric min/max) | Sinusoidal oscillation within ±30 % of mid-range |
| **Float scale** (e.g. ×0.1) | Returns `float`; integer scale returns `int` |

Sinusoidal signals use **wall-clock time** rather than a tick counter, so the oscillation frequency is independent of the send period. Each signal is assigned a random frequency (0.05–0.20 Hz) and phase offset so they move independently of each other.

Factor and offset from the DBC are handled automatically by `cantools` during encoding — the simulator always works in the physical domain.

---

## Bridge Auto-Start

When the simulator starts, it checks whether `can-bridge.py` is already running via `pgrep`. If not:

1. It locates `scripts/can-bridge.py` relative to its own file path.
2. It spawns the bridge as a background subprocess, redirecting its output to `/tmp/can-bridge.log` to avoid interleaving with simulator output.
3. It polls `ip link show <interface>` every 500 ms for up to 15 seconds, waiting for the vcan interface to appear.
4. If the bridge exits early (e.g. hardware not found), the wait detects the early exit and reports the log path.
5. On simulator exit (Ctrl+C), the bridge subprocess is terminated automatically.

Use `--no-bridge-check` to skip this entirely for vcan-only testing.

```
  [bridge] can-bridge.py is not running — starting it automatically.
  [bridge] Started (pid 12345) — log: /tmp/can-bridge.log
  [bridge] Waiting for vcan0... ready.
```

---

## Available Use Cases

| File | Description | Period |
|---|---|---|
| `basic_cluster_ui.json` | All 4 AutoNET messages at typical automotive rates | 10 / 100 / 100 / 1000 ms |
| `rvc_usecase.json` | Normal driving for 4 s, then Gear=REVERSE for 15 s, cyclic | same as above |

---

## Architecture Decisions

### One thread per message
Each `MessageSender` is an independent daemon thread that sleeps for its own `period_ms` between sends. This means a 10 ms `DrivetrainStatus` and a 1000 ms `FuelRange` never block each other. Python's GIL is not a concern here because the threads spend nearly all their time sleeping.

### Wall-clock oscillation
Continuous signal values use `time.time()` as the oscillation input, not a per-call counter. This decouples the signal's variation frequency from its send period — a signal sent at 10 ms and one at 100 ms can both oscillate at exactly 0.1 Hz.

### Shared Scenario object (no message passing)
All `MessageSender` threads hold a reference to the same `Scenario` object. Each thread calls `scenario.current_overrides(msg_name)` on every send cycle. The scenario computes the active phase from wall-clock time, so there is no synchronisation needed and no lag between the phase changing and the override taking effect.

### Single `can.Bus` per interface
Multiple `MessageSender` threads sharing the same interface use one shared `can.Bus` instance. `python-can`'s SocketCAN bus is thread-safe for concurrent `send()` calls, and opening the same interface twice would cause a resource conflict.

### cantools for encoding
The simulator always works with **physical values** (the values a human would read, e.g. 100 km/h). `cantools` applies factor, offset, and bit packing when encoding. This means the simulator does not need to know about raw representation — adding a new signal to the DBC requires no code change.

### Bridge output to log file
The bridge's live spinner display would interleave with the simulator's output if written to the same terminal. Redirecting the bridge's stdout/stderr to `/tmp/can-bridge.log` keeps the simulator output clean while still allowing the user to inspect bridge status.

---

## Extending the Simulator

### Add a new use case
Create a new JSON file in `simulator/usecases/`. Copy `basic_cluster_ui.json` as a starting point, adjust message list, periods, interface, and optionally add a `scenario` block.

### Add signals or messages
Edit `networks/CAN/AutoNET.dbc`. No simulator code changes are required — `can-sim.py` reads all signal metadata (min, max, choices, scale, offset) from the DBC at runtime.

### Future simulators
The naming convention is `<network>-sim.py`. Ethernet and gRPC simulators would follow as `eth-sim.py` and `grpc-sim.py` respectively, each with their own `usecases/` subdirectory.
