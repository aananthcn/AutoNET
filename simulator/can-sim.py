#!/usr/bin/env python3
"""
can-sim.py — AutoNET CAN simulator

Generates realistic varying signal values from a DBC file and sends CAN frames
at configurable periodicities defined in a use-case JSON file.

Optionally supports a scenario section in the use-case JSON to sequence
signal overrides across timed phases (e.g. forcing a specific gear for N seconds).

Usage:
    python3 simulator/can-sim.py --dbcfile networks/CAN/AutoNET.dbc
    python3 simulator/can-sim.py --dbcfile networks/CAN/AutoNET.dbc \
        --usecase simulator/usecases/basic_cluster_ui.json
    python3 simulator/can-sim.py --dbcfile networks/CAN/AutoNET.dbc \
        --usecase simulator/usecases/rvc_usecase.json
"""

import argparse
import json
import math
import random
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import can
import cantools


DEFAULT_INTERFACE = "vcan0"
DEFAULT_PERIOD_MS = 100


def parse_args():
    p = argparse.ArgumentParser(
        description="AutoNET CAN simulator — sends DBC-encoded frames with varying signal data"
    )
    p.add_argument("--dbcfile", required=True, metavar="FILE",
                   help="Path to the DBC file")
    p.add_argument("--usecase", metavar="FILE",
                   help="Path to a use-case JSON config file (optional)")
    p.add_argument("--no-bridge-check", action="store_true",
                   help="Skip the can-bridge.py running check (vcan-only mode)")
    return p.parse_args()


_BRIDGE_SCRIPT  = Path(__file__).parent.parent / 'scripts' / 'can-bridge.py'
_BRIDGE_WAIT_S  = 15    # seconds to wait for vcan interface to appear


def _bridge_running():
    result = subprocess.run(['pgrep', '-f', 'can-bridge.py'], capture_output=True)
    return result.returncode == 0


def _start_bridge():
    if not _BRIDGE_SCRIPT.exists():
        print(f"  [bridge] Script not found: {_BRIDGE_SCRIPT}", file=sys.stderr)
        return None
    log_path = Path(tempfile.gettempdir()) / 'can-bridge.log'
    log_file = open(log_path, 'w')
    proc = subprocess.Popen(
        [sys.executable, str(_BRIDGE_SCRIPT)],
        stdout=log_file,
        stderr=log_file,
    )
    print(f"  [bridge] Started (pid {proc.pid}) — log: {log_path}")
    return proc


def _wait_for_interface(iface, bridge_proc, timeout=_BRIDGE_WAIT_S):
    """Poll until iface exists, or bridge_proc exits early, or timeout."""
    print(f"  [bridge] Waiting for {iface}...", end='', flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if bridge_proc and bridge_proc.poll() is not None:
            print(f" bridge exited (rc={bridge_proc.returncode}).")
            return False
        result = subprocess.run(['ip', 'link', 'show', iface], capture_output=True)
        if result.returncode == 0:
            print(" ready.")
            return True
        time.sleep(0.5)
    print(f" timed out after {timeout}s.")
    return False


def load_usecase(path):
    with open(path) as f:
        return json.load(f)


class ScenarioPhase:
    """One named time window in a scenario with optional per-signal overrides."""

    def __init__(self, name, description, duration_s, overrides):
        self.name        = name
        self.description = description
        self.duration_s  = duration_s
        # overrides: {msg_name: {signal_name: physical_value_or_choice_string}}
        self.overrides   = overrides


class Scenario:
    """
    Time-based sequencer of ScenarioPhases.

    Each phase runs for duration_s seconds then the next begins.
    When cyclic=True the sequence repeats indefinitely.
    """

    def __init__(self, description, phases, cyclic=True):
        self.description = description
        self.phases      = phases
        self.cyclic      = cyclic
        self._start      = time.time()
        self._total      = sum(p.duration_s for p in phases)

    def _active_phase(self):
        elapsed = time.time() - self._start
        if self.cyclic:
            elapsed = elapsed % self._total
        else:
            elapsed = min(elapsed, self._total)
        t = 0.0
        for phase in self.phases:
            t += phase.duration_s
            if elapsed < t:
                return phase
        return self.phases[-1]

    def current_phase_name(self):
        return self._active_phase().name

    def current_overrides(self, msg_name):
        """Returns {signal_name: value} for the active phase, or {} if none."""
        return self._active_phase().overrides.get(msg_name, {})


def parse_scenario(data):
    """Build a Scenario from the 'scenario' dict in a use-case JSON, or return None."""
    if not data:
        return None
    phases = [
        ScenarioPhase(
            name        = entry.get("name", "unnamed"),
            description = entry.get("description", ""),
            duration_s  = float(entry["duration_s"]),
            overrides   = entry.get("signal_overrides", {}),
        )
        for entry in data.get("phases", [])
        if "duration_s" in entry
    ]
    if not phases:
        return None
    return Scenario(
        description = data.get("description", ""),
        phases      = phases,
        cyclic      = data.get("cyclic", True),
    )


class SignalState:
    """
    Maintains per-signal generation state and produces the next physical value.

    Value generation rules:
    - Choices signal (enum / boolean): pick from the defined value list; change
      only every N ticks so the value does not flicker. Boolean-like signals
      (exactly 2 choices) are biased toward the lower / "normal" state.
    - Continuous signal: sinusoidal oscillation within [min, max] using wall-clock
      time so each signal moves at its own frequency independently of send rate.
    """

    BOOL_ZERO_WEIGHT = 90    # % probability of the lower (off/closed/ok) state
    ENUM_MIN_TICKS   = 10    # ticks before an enum value may change
    ENUM_MAX_TICKS   = 50

    def __init__(self, signal, phase=0.0):
        self.signal          = signal
        self.phase           = phase
        self._freq           = random.uniform(0.05, 0.20)   # Hz — unique per signal
        self._enum_current   = None
        self._enum_countdown = 0

    def _next_enum(self):
        sig  = self.signal
        keys = list(sig.choices.keys())

        if self._enum_countdown > 0:
            self._enum_countdown -= 1
            return self._enum_current

        if len(keys) == 2:
            weights = [self.BOOL_ZERO_WEIGHT, 100 - self.BOOL_ZERO_WEIGHT]
            raw = random.choices(keys, weights=weights)[0]
        else:
            raw = random.choice(keys)

        scale  = sig.scale  if sig.scale  is not None else 1
        offset = sig.offset if sig.offset is not None else 0
        self._enum_current   = raw * scale + offset
        self._enum_countdown = random.randint(self.ENUM_MIN_TICKS, self.ENUM_MAX_TICKS)
        return self._enum_current

    def _next_continuous(self):
        sig = self.signal
        lo  = sig.minimum if sig.minimum is not None else 0.0
        hi  = sig.maximum if sig.maximum is not None else 100.0

        center    = (lo + hi) / 2.0
        amplitude = (hi - lo) * 0.30
        value     = center + amplitude * math.sin(
            2 * math.pi * self._freq * time.time() + self.phase
        )
        value = max(lo, min(hi, value))

        scale = sig.scale if sig.scale is not None else 1
        if sig.is_float or (isinstance(scale, float) and scale % 1 != 0):
            return float(value)
        return int(round(value))

    def next_value(self):
        if self.signal.choices:
            return self._next_enum()
        return self._next_continuous()


class MessageSender(threading.Thread):
    """Sends a single DBC message at a fixed period on a CAN bus."""

    def __init__(self, db_msg, bus, period_ms, scenario=None):
        super().__init__(daemon=True, name=db_msg.name)
        self.db_msg   = db_msg
        self.bus      = bus
        self.period_s = period_ms / 1000.0
        self.scenario = scenario
        self.states   = {
            sig.name: SignalState(sig, phase=i * 0.7)
            for i, sig in enumerate(db_msg.signals)
        }
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while True:
            overrides = (self.scenario.current_overrides(self.db_msg.name)
                         if self.scenario else {})
            values = {
                name: overrides[name] if name in overrides else state.next_value()
                for name, state in self.states.items()
            }
            try:
                data = self.db_msg.encode(values)
                self.bus.send(can.Message(
                    arbitration_id=self.db_msg.frame_id,
                    data=data,
                    is_extended_id=self.db_msg.frame_id > 0x7FF,
                ))
            except Exception as exc:
                print(f"  [warn] {self.db_msg.name}: {exc}", file=sys.stderr)
            if self._stop.wait(self.period_s):
                break


def build_plan(db, usecase):
    """
    Returns (plan, scenario) where plan is a list of
    (cantools.Message, period_ms, interface) tuples.
    Falls back to all DBC messages on the default interface when no use-case is given.
    """
    if usecase is None:
        return [(msg, DEFAULT_PERIOD_MS, DEFAULT_INTERFACE) for msg in db.messages], None

    scenario  = parse_scenario(usecase.get("scenario"))
    top_iface = usecase.get("interface", DEFAULT_INTERFACE)
    plan = []
    for entry in usecase.get("messages", []):
        period_ms = entry.get("period_ms", DEFAULT_PERIOD_MS)
        iface     = entry.get("interface", top_iface)
        try:
            if "name" in entry:
                msg = db.get_message_by_name(entry["name"])
            else:
                raw_id = entry["frame_id"]
                fid    = int(raw_id, 16) if isinstance(raw_id, str) else raw_id
                msg    = db.get_message_by_frame_id(fid)
        except KeyError as exc:
            print(f"  [warn] message not found in DBC: {exc}", file=sys.stderr)
            continue
        plan.append((msg, period_ms, iface))
    return plan, scenario


def _scenario_monitor(scenario, stop_evt):
    """Prints a line to stdout whenever the active scenario phase changes."""
    last = None
    while not stop_evt.wait(0.05):
        current = scenario.current_phase_name()
        if current != last:
            print(f"  [scenario] phase → {current}")
            last = current


def main():
    args    = parse_args()
    db      = cantools.database.load_file(args.dbcfile)
    usecase = load_usecase(args.usecase) if args.usecase else None

    bridge_proc = None
    if not args.no_bridge_check and not _bridge_running():
        print("  [bridge] can-bridge.py is not running — starting it automatically.")
        bridge_proc = _start_bridge()
        if bridge_proc is None:
            sys.exit(1)
        if not _wait_for_interface(DEFAULT_INTERFACE, bridge_proc):
            print("  [bridge] Interface did not come up. Check the bridge log.", file=sys.stderr)
            bridge_proc.terminate()
            sys.exit(1)

    print(f"DBC:      {args.dbcfile}  ({len(db.messages)} message(s))")
    if args.usecase:
        print(f"Use-case: {args.usecase}")

    plan, scenario = build_plan(db, usecase)
    if not plan:
        print("No messages to send — check use-case config.", file=sys.stderr)
        sys.exit(1)

    if scenario:
        phases_str = " → ".join(
            f"{p.name}({p.duration_s}s)" for p in scenario.phases
        )
        cyclic_str = " [cyclic]" if scenario.cyclic else ""
        print(f"Scenario: {phases_str}{cyclic_str}")

    buses   = {}
    senders = []
    print()
    print(f"  {'Message':<24} {'ID':<8} {'Period':>8}   Interface")
    print(f"  {'-'*24} {'-'*8} {'-'*8}   {'-'*12}")
    for db_msg, period_ms, iface in plan:
        if iface not in buses:
            buses[iface] = can.Bus(interface="socketcan", channel=iface)
        senders.append(MessageSender(db_msg, buses[iface], period_ms, scenario))
        print(f"  {db_msg.name:<24} 0x{db_msg.frame_id:03X}     {period_ms:>5} ms   {iface}")

    print()
    print("Simulator running — Ctrl+C to stop.")

    stop_evt = threading.Event()
    if scenario:
        threading.Thread(target=_scenario_monitor, args=(scenario, stop_evt),
                         daemon=True).start()

    for s in senders:
        s.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        stop_evt.set()
        for s in senders:
            s.stop()
        for s in senders:
            s.join(timeout=1.0)
        for bus in buses.values():
            bus.shutdown()
        if bridge_proc is not None:
            bridge_proc.terminate()
            bridge_proc.wait(timeout=3)
            print("  [bridge] Bridge stopped.")
        print("Stopped.")


if __name__ == "__main__":
    main()
