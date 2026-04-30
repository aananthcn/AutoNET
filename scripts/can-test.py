import can
import os
import queue
import readline
import subprocess
import threading
import time
from canalystii import CanalystDevice, Message as HWMessage

BITRATE = 500000

def ensure_vcan(name):
    result = subprocess.run(["ip", "link", "show", name], capture_output=True)
    if result.returncode != 0:
        print(f"{name} not found — creating it now...")
        subprocess.run(["sudo", "modprobe", "vcan"], check=True)
        subprocess.run(["sudo", "ip", "link", "add", "dev", name, "type", "vcan"], check=True)
        subprocess.run(["sudo", "ip", "link", "set", "up", name], check=True)
        print(f"{name} created and brought up.")
    else:
        print(f"{name} already exists, skipping setup.")

def str_to_hw_msg(frame_str):
    if '#' not in frame_str:
        raise ValueError("expected <id>#<data>")
    id_str, data_str = frame_str.split('#', 1)
    data          = bytes.fromhex(data_str) if data_str else b''
    msg           = HWMessage()
    msg.can_id    = int(id_str, 16)
    msg.extended  = 1 if len(id_str) > 3 else 0
    msg.remote    = 0
    msg.data_len  = len(data)
    msg.send_type = 0
    for i, b in enumerate(data):
        msg.data[i] = b
    return msg

def print_help():
    print()
    print("=" * 60)
    print("  CAN Test: CAN1 <-> vcan0  |  CAN2 <-> vcan1  [running]")
    print("=" * 60)
    print("  Bridge commands:")
    print("    m -b <1|2>     monitor vcan0 (CAN1) or vcan1 (CAN2)")
    print("    s -b <frame>   send a frame to vcan0 (CAN1), e.g.:")
    print("                     s -b 00000040#E803401F08003F00")
    print()
    print("  Device commands (Canalyst-II direct):")
    print("    m -d <1|2>           monitor CAN1 or CAN2 directly")
    print("    s -d <1|2> <frame>   send a frame to CAN1 or CAN2, e.g.:")
    print("                           s -d 2 00000040#E803401F08003F00")
    print()
    print("  h              show this help")
    print("  q              quit")
    print("=" * 60)
    print()

running        = True
device         = None
vcan_bus0      = None
vcan_bus1      = None
rx2_queue      = queue.Queue()
monitoring_ch2 = threading.Event()

def receive_ch0_loop():
    """CAN1 → vcan0"""
    while running:
        msgs = device.receive(0)
        if msgs:
            for m in msgs:
                try:
                    vcan_bus0.send(can.Message(
                        arbitration_id=m.can_id,
                        data=bytes(m.data[:m.data_len]),
                        is_extended_id=bool(m.extended),
                        dlc=m.data_len,
                    ))
                except Exception:
                    pass
        else:
            time.sleep(0.01)

def receive_ch1_loop():
    """CAN2 → vcan1"""
    while running:
        msgs = device.receive(1)
        if msgs:
            for m in msgs:
                try:
                    vcan_bus1.send(can.Message(
                        arbitration_id=m.can_id,
                        data=bytes(m.data[:m.data_len]),
                        is_extended_id=bool(m.extended),
                        dlc=m.data_len,
                    ))
                except Exception:
                    pass
                if monitoring_ch2.is_set():
                    rx2_queue.put(m)
        else:
            time.sleep(0.01)

try:
    ensure_vcan('vcan0')
    ensure_vcan('vcan1')
    try:
        device = CanalystDevice(device_index=0)
        device.init(0, bitrate=BITRATE)
        device.init(1, bitrate=BITRATE)
    except Exception:
        print("Error: Canalyst-II not found — is the USB-CAN device plugged in?")
        print("       Run: lsusb | grep -i microchip")
        os._exit(1)
    vcan_bus0 = can.Bus(interface='socketcan', channel='vcan0')
    vcan_bus1 = can.Bus(interface='socketcan', channel='vcan1')

    threading.Thread(target=receive_ch0_loop, daemon=True).start()
    threading.Thread(target=receive_ch1_loop, daemon=True).start()

    print_help()

    while True:
        try:
            cmd = input("bridge> ").strip()
        except EOFError:
            break

        if cmd == 'q':
            break

        elif cmd in ('h', ''):
            print_help()

        # ── monitor ──────────────────────────────────────────────────
        elif cmd.startswith('m -b'):
            ch = cmd[4:].strip()
            if ch in ('1', ''):
                print("  Monitoring vcan0 (CAN1) — Ctrl+C to return to prompt.")
                try:
                    subprocess.run(["candump", "vcan0"])
                except KeyboardInterrupt:
                    print()
            elif ch == '2':
                print("  Monitoring vcan1 (CAN2) — Ctrl+C to return to prompt.")
                try:
                    subprocess.run(["candump", "vcan1"])
                except KeyboardInterrupt:
                    print()
            else:
                print("  Usage: m -b <1|2>")

        elif cmd.startswith('m -d '):
            ch = cmd[5:].strip()
            if ch == '1':
                print("  Monitoring CAN1 via vcan0 — Ctrl+C to return to prompt.")
                try:
                    subprocess.run(["candump", "vcan0"])
                except KeyboardInterrupt:
                    print()
            elif ch == '2':
                while not rx2_queue.empty():
                    rx2_queue.get_nowait()
                monitoring_ch2.set()
                print("  Monitoring CAN2 directly — Ctrl+C to return to prompt.")
                try:
                    while True:
                        try:
                            m = rx2_queue.get(timeout=0.5)
                            id_str = f"{m.can_id:08X}" if m.extended else f"{m.can_id:03X}"
                            data   = bytes(m.data[:m.data_len]).hex().upper()
                            print(f"  CAN2  {id_str}#{data}")
                        except queue.Empty:
                            pass
                except KeyboardInterrupt:
                    print()
                finally:
                    monitoring_ch2.clear()
            else:
                print("  Usage: m -d <1|2>")

        # ── send ─────────────────────────────────────────────────────
        elif cmd.startswith('s -b '):
            frame = cmd[5:].strip()
            try:
                subprocess.run(["cansend", "vcan0", frame], check=True)
                print(f"  Sent to vcan0: {frame}")
            except subprocess.CalledProcessError as e:
                print(f"  Error: {e}")

        elif cmd.startswith('s -d '):
            parts = cmd[5:].split(None, 1)
            if len(parts) != 2 or parts[0] not in ('1', '2'):
                print("  Usage: s -d <1|2> <frame>")
            else:
                ch, frame_str = parts
                try:
                    device.send(int(ch) - 1, [str_to_hw_msg(frame_str)])
                    print(f"  Sent to CAN{ch}: {frame_str}")
                except Exception as e:
                    print(f"  Error: {e}")

        else:
            print(f"  Unknown command '{cmd}'. Type h for help.")

except KeyboardInterrupt:
    pass
finally:
    running = False
    try:
        if vcan_bus0:
            vcan_bus0.shutdown()
    except Exception:
        pass
    try:
        if vcan_bus1:
            vcan_bus1.shutdown()
    except Exception:
        pass
    print("\nBridge stopped.", flush=True)
    os._exit(0)
