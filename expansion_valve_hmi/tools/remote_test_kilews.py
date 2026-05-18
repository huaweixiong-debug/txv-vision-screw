"""
远程测试脚本 v3：解码 ASCII 字符串，识别拧紧枪型号
用法: python tools/remote_test_kilews.py
"""
import paramiko
import sys

TARGET_SSH_HOST = "100.79.19.71"
TARGET_SSH_USER = "a"
TARGET_SSH_PASS = "0000"

REMOTE_SCRIPT = """import struct
import socket
import sys

TIGHTENING_IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.105"
TIGHTENING_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 502

def modbus_read(ip, port, unit_id, func_code, start, count, timeout=2.0):
    tid = 1
    pdu = struct.pack(">BHH", func_code, start, count)
    mbap = struct.pack(">HHHB", tid, 0, len(pdu) + 1, unit_id)
    sock = socket.create_connection((ip, port), timeout=timeout)
    try:
        sock.sendall(mbap + pdu)
        header = sock.recv(7)
        if len(header) < 7:
            return None
        rx_tid, _, length, rx_unit = struct.unpack(">HHHB", header)
        remaining = length - 1
        payload = bytearray()
        while len(payload) < remaining:
            chunk = sock.recv(remaining - len(payload))
            if not chunk:
                break
            payload.extend(chunk)
    finally:
        sock.close()
    if not payload or payload[0] != func_code:
        return None
    byte_count = payload[1]
    data = payload[2:2+byte_count]
    return [struct.unpack(">H", data[i:i+2])[0] for i in range(0, len(data), 2)]

def decode_ascii(values, offset=0):
    chars = []
    for v in values:
        hi = (v >> 8) & 0xFF
        lo = v & 0xFF
        if 32 <= hi < 127:
            chars.append(chr(hi))
        else:
            chars.append('.')
        if 32 <= lo < 127:
            chars.append(chr(lo))
        else:
            chars.append('.')
    return ''.join(chars)

def print_block(label, values, base_addr):
    print("--- %s (addr %d) ---" % (label, base_addr))
    print("  ASCII: %s" % decode_ascii(values))
    for i, v in enumerate(values):
        addr = base_addr + i
        print("  [%5d] %6d  0x%04X" % (addr, v, v))

print("=== Kilews Device Identification ===")
print("Target: %s:%d  Unit=1" % (TIGHTENING_IP, TIGHTENING_PORT))
print()

# Read key address blocks
blocks = [
    ("Block 0-99", 0, 100),
    ("Block 250-350", 250, 100),
    ("Block 400-550", 400, 150),
    ("Block 1000-1200", 1000, 200),
    ("Block 1250-1300", 1250, 50),
    ("Block 1400-1550", 1400, 150),
    ("Block 2100-2150", 2100, 50),
    ("Block 4050-4350", 4050, 300),
]

for label, start, count in blocks:
    print()
    values = modbus_read(TIGHTENING_IP, TIGHTENING_PORT, 1, 3, start, count, timeout=3.0)
    if values:
        non_zero = [(start+i, v) for i, v in enumerate(values) if v != 0]
        print("--- %s: %d non-zero registers ---" % (label, len(non_zero)))
        print("  ASCII: %s" % decode_ascii(values, start))
        # Print only interesting registers (non-zero or ASCII-printable)
        shown = 0
        for i, v in enumerate(values):
            addr = start + i
            if v != 0 or (32 <= (v>>8) < 127 and 32 <= (v&0xFF) < 127):
                print("  [%5d] %6d  0x%04X" % (addr, v, v))
                shown += 1
                if shown > 30:
                    print("  ... (showing first 30)")
                    break
    else:
        print("--- %s: read failed ---" % label)

print()
print("=== Done ===")
"""


def main():
    print("Connecting to %s@%s ..." % (TARGET_SSH_USER, TARGET_SSH_HOST))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(TARGET_SSH_HOST, username=TARGET_SSH_USER, password=TARGET_SSH_PASS, timeout=10)
    except Exception as e:
        print("SSH connection failed: %s" % e)
        sys.exit(1)

    print("SSH connected. Uploading script...")

    sftp = client.open_sftp()
    remote_path = "C:\\Users\\A\\_modbus_test.py"
    try:
        with sftp.file(remote_path, "w") as f:
            f.write(REMOTE_SCRIPT)
    finally:
        sftp.close()

    print("Running device identification scan...")
    print("=" * 60)

    stdin, stdout, stderr = client.exec_command(
        'python "C:\\Users\\A\\_modbus_test.py" 192.168.0.105 502',
        timeout=120,
    )

    for line in stdout:
        print(line.rstrip())

    err_output = stderr.read().decode("utf-8", errors="ignore")
    if err_output:
        print("[STDERR]", err_output)

    client.exec_command('del "C:\\Users\\A\\_modbus_test.py"', timeout=10)
    client.close()
    print("=" * 60)
    print("Done")


if __name__ == "__main__":
    main()
