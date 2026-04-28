import can
import subprocess
import threading

def ensure_vcan0():
    result = subprocess.run(["ip", "link", "show", "vcan0"], capture_output=True)
    if result.returncode != 0:
        print("vcan0 not found — creating it now...")
        subprocess.run(["sudo", "modprobe", "vcan"], check=True)
        subprocess.run(["sudo", "ip", "link", "add", "dev", "vcan0", "type", "vcan"], check=True)
        subprocess.run(["sudo", "ip", "link", "set", "up", "vcan0"], check=True)
        print("vcan0 created and brought up.")
    else:
        print("vcan0 already exists, skipping setup.")

def print_help():
    print()
    print("=" * 60)
    print("  CAN Bridge: Canalyst-II CAN1 --> vcan0  [running]")
    print("=" * 60)
    print("  m              monitor vcan0 (Ctrl+C to return here)")
    print("  s <frame>      send a frame to vcan0, e.g.:")
    print("                   s 00000040#E803401F08003F00")
    print("  h              show this help")
    print("  q              quit the bridge")
    print("=" * 60)
    print()

running      = True
hw_bus       = None
vcan_bus     = None
bridge_thread = None

def bridge_loop():
    while running:
        try:
            msg = hw_bus.recv(timeout=0.1)
            if msg:
                msg.channel = None  # strip channel info before forwarding
                vcan_bus.send(msg)
        except Exception:
            if not running:
                break

try:
    ensure_vcan0()
    hw_bus   = can.Bus(interface='canalystii', channel=0, bitrate=500000)
    vcan_bus = can.Bus(interface='socketcan', channel='vcan0')

    bridge_thread = threading.Thread(target=bridge_loop, daemon=True)
    bridge_thread.start()

    print_help()

    while True:
        try:
            cmd = input("bridge> ").strip()
        except EOFError:
            break

        if cmd == 'q':
            break
        elif cmd == 'm':
            print("  Monitoring vcan0 — Ctrl+C to return to prompt.")
            try:
                subprocess.run(["candump", "vcan0"])
            except KeyboardInterrupt:
                print()
        elif cmd.startswith('s '):
            frame = cmd[2:].strip()
            try:
                subprocess.run(["cansend", "vcan0", frame], check=True)
                print(f"  Sent: {frame}")
            except subprocess.CalledProcessError as e:
                print(f"  Error: {e}")
        elif cmd in ('h', ''):
            print_help()
        else:
            print(f"  Unknown command '{cmd}'. Type h for help.")

except KeyboardInterrupt:
    pass
finally:
    running = False
    if bridge_thread:
        bridge_thread.join(timeout=1.0)
    print("\nBridge stopped.")
    if hw_bus:    hw_bus.shutdown()
    if vcan_bus:  vcan_bus.shutdown()
