import can
import threading
import subprocess
from canalystii import CanalystDevice, Message as HWMessage
import time

# ── Configuration ─────────────────────────────────────────────────
BITRATE = 500000
# ─────────────────────────────────────────────────────────────────

device    = None
vcan0_bus = None
vcan1_bus = None
running   = True

# Counters for display
stats = {
    'vcan0_to_can1': 0,
    'can1_to_vcan0': 0,
    'vcan1_to_can2': 0,
    'can2_to_vcan1': 0,
    'can1_last_id' : 0,
    'can2_last_id' : 0,
}
stats_lock = threading.Lock()

SPINNER = ['⠋','⠙','⠹','⠸','⠼','⠴','⠦','⠧','⠇','⠏']
spinner_idx = 0

def display_loop():
    global spinner_idx
    while running:
        with stats_lock:
            s = stats.copy()
        spin = SPINNER[spinner_idx % len(SPINNER)]
        spinner_idx += 1
        line = (
            f"\r{spin} "
            f"CAN1: TX={s['vcan0_to_can1']:>6} RX={s['can1_to_vcan0']:>6} "
            f"LastID=0x{s['can1_last_id']:03X}   |    "
            f"CAN2: TX={s['vcan1_to_can2']:>6} RX={s['can2_to_vcan1']:>6} "
            f"LastID=0x{s['can2_last_id']:03X}  "
        )
        print(line, end='', flush=True)
        time.sleep(0.1)

def ch0_to_vcan0():
    while running:
        msgs = device.receive(0)
        if msgs:
            for msg in msgs:
                try:
                    vcan_msg = can.Message(
                        arbitration_id=msg.can_id,
                        data=bytes(msg.data[:msg.data_len]),
                        is_extended_id=bool(msg.extended),
                        dlc=msg.data_len
                    )
                    vcan0_bus.send(vcan_msg)
                    with stats_lock:
                        stats['can1_to_vcan0'] += 1
                        stats['can1_last_id']   = msg.can_id
                except Exception as e:
                    pass

def vcan0_to_ch0():
    while running:
        msg = vcan0_bus.recv(timeout=0.1)
        if msg:
            try:
                hw_msg = HWMessage()
                hw_msg.can_id    = msg.arbitration_id
                hw_msg.extended  = 1 if msg.is_extended_id else 0
                hw_msg.remote    = 0
                hw_msg.data_len  = msg.dlc
                hw_msg.send_type = 0
                for i, b in enumerate(msg.data):
                    hw_msg.data[i] = b
                device.send(0, [hw_msg])
                with stats_lock:
                    stats['vcan0_to_can1'] += 1
            except Exception as e:
                pass

def ch1_to_vcan1():
    while running:
        msgs = device.receive(1)
        if msgs:
            for msg in msgs:
                try:
                    vcan_msg = can.Message(
                        arbitration_id=msg.can_id,
                        data=bytes(msg.data[:msg.data_len]),
                        is_extended_id=bool(msg.extended),
                        dlc=msg.data_len
                    )
                    vcan1_bus.send(vcan_msg)
                    with stats_lock:
                        stats['can2_to_vcan1'] += 1
                        stats['can2_last_id']   = msg.can_id
                except Exception as e:
                    pass

def vcan1_to_ch1():
    while running:
        msg = vcan1_bus.recv(timeout=0.1)
        if msg:
            try:
                hw_msg = HWMessage()
                hw_msg.can_id    = msg.arbitration_id
                hw_msg.extended  = 1 if msg.is_extended_id else 0
                hw_msg.remote    = 0
                hw_msg.data_len  = msg.dlc
                hw_msg.send_type = 0
                for i, b in enumerate(msg.data):
                    hw_msg.data[i] = b
                device.send(1, [hw_msg])
                with stats_lock:
                    stats['vcan1_to_can2'] += 1
            except Exception as e:
                pass

try:
    subprocess.run(["sudo", "modprobe", "vcan"], check=True)
    subprocess.run(["sudo", "ip", "link", "add", "dev", "vcan0", "type", "vcan"],
                   capture_output=True)
    subprocess.run(["sudo", "ip", "link", "set", "up", "vcan0"], check=True)
    subprocess.run(["sudo", "ip", "link", "add", "dev", "vcan1", "type", "vcan"],
                   capture_output=True)
    subprocess.run(["sudo", "ip", "link", "set", "up", "vcan1"], check=True)

    device    = CanalystDevice(device_index=0)
    device.init(0, bitrate=BITRATE)
    device.init(1, bitrate=BITRATE)

    vcan0_bus = can.Bus(interface='socketcan', channel='vcan0')
    vcan1_bus = can.Bus(interface='socketcan', channel='vcan1')

    print(f"{'─'*87}")
    print(f"CAN Bridge @ {BITRATE} bps  |  vcan0 <=> CAN1 <=> RPi-CAN1  |  vcan1 <=> CAN2 <=> RPi-CAN2")
    print(f"{'─'*87}")

    threads = [
        threading.Thread(target=ch0_to_vcan0, daemon=True),
        threading.Thread(target=vcan0_to_ch0, daemon=True),
        threading.Thread(target=ch1_to_vcan1, daemon=True),
        threading.Thread(target=vcan1_to_ch1, daemon=True),
        threading.Thread(target=display_loop,  daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

except KeyboardInterrupt:
    running = False
    print("\n\nStopped.")
finally:
    if device:    device.__del__()
    if vcan0_bus: vcan0_bus.shutdown()
    if vcan1_bus: vcan1_bus.shutdown()