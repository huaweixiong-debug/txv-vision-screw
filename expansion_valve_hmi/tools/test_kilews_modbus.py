"""
拧紧枪 MODBUS TCP 通讯测试脚本
在目标工控机上运行: python tools\test_kilews_modbus.py --ip 192.168.0.105
"""
import argparse
import struct
import socket
import sys


def read_holding_registers(ip: str, port: int, unit_id: int, start: int, count: int, timeout: float = 2.0) -> list[int]:
    """读取 MODBUS TCP 保持寄存器 (功能码 03)"""
    if count < 1 or count > 125:
        raise ValueError("count 必须在 1~125 之间")

    transaction_id = 1
    function_code = 3
    pdu = struct.pack(">BHH", function_code, start, count)
    mbap = struct.pack(">HHHB", transaction_id, 0, len(pdu) + 1, unit_id)
    request = mbap + pdu

    sock = socket.create_connection((ip, port), timeout=timeout)
    try:
        sock.sendall(request)
        # 读 MBAP 头 7 字节
        header = sock.recv(7)
        if len(header) < 7:
            raise OSError(f"MODBUS 响应头不完整，收到 {len(header)} 字节")
        rx_tid, _, length, rx_unit = struct.unpack(">HHHB", header)
        if rx_tid != transaction_id:
            raise OSError(f"事务 ID 不匹配: 期望 {transaction_id}, 收到 {rx_tid}")
        # 读剩余数据
        remaining = length - 1
        payload = bytearray()
        while len(payload) < remaining:
            chunk = sock.recv(remaining - len(payload))
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) < remaining:
            raise OSError(f"响应数据不完整: 期望 {remaining} 字节, 收到 {len(payload)}")
    finally:
        sock.close()

    if payload[0] != function_code:
        if payload[0] == 0x83:
            err_code = payload[1] if len(payload) > 1 else 0
            err_msgs = {
                1: "非法功能码",
                2: "非法数据地址",
                3: "非法数据值",
                4: "从站设备故障",
            }
            raise OSError(f"MODBUS 异常响应: 功能码=0x83, 异常码={err_code} ({err_msgs.get(err_code, '未知')})")
        raise OSError(f"MODBUS 功能码错误: {payload[0]:02X}")

    byte_count = payload[1]
    data = payload[2 : 2 + byte_count]
    return [struct.unpack(">H", data[i : i + 2])[0] for i in range(0, len(data), 2)]


def main():
    parser = argparse.ArgumentParser(description="Kilews 拧紧枪 MODBUS TCP 通讯测试")
    parser.add_argument("--ip", default="192.168.0.105", help="拧紧枪 IP")
    parser.add_argument("--port", type=int, default=502, help="MODBUS TCP 端口")
    parser.add_argument("--unit", type=int, default=1, help="MODBUS 单元 ID")
    parser.add_argument("--start", type=int, default=0, help="起始寄存器地址")
    parser.add_argument("--count", type=int, default=20, help="读取寄存器数量")
    parser.add_argument("--timeout", type=float, default=3.0, help="超时秒数")
    parser.add_argument("--scan", type=int, default=0, help="扫描范围上限 (max 5000)")
    args = parser.parse_args()

    print(f"=== 拧紧枪 MODBUS TCP 通讯测试 ===")
    print(f"目标: {args.ip}:{args.port}  Unit ID={args.unit}")
    print()

    # 1. 网络连通性
    print("[1/3] 检查网络连通性...")
    import subprocess
    import platform
    param = "-n" if platform.system().lower() == "windows" else "-c"
    result = subprocess.run(["ping", param, "2", args.ip], capture_output=True, text=True, timeout=5)
    if "TTL=" in result.stdout or "ttl=" in result.stdout:
        print(f"  OK - ping 通")
    else:
        print(f"  FAIL - ping 不通 {args.ip}")
        print(f"  请检查网线连接和 IP 配置")
        sys.exit(1)

    # 2. TCP 端口
    print("[2/3] 检查 TCP 端口 {}...".format(args.port))
    try:
        s = socket.create_connection((args.ip, args.port), timeout=args.timeout)
        s.close()
        print(f"  OK - 端口 {args.port} 可连接")
    except Exception as e:
        print(f"  FAIL - 端口 {args.port} 不可达: {e}")
        sys.exit(1)

    # 3. MODBUS 读取
    if args.scan > 0:
        print(f"[3/3] 扫描寄存器 0~{args.scan}...")
        scan_modbus(args.ip, args.port, args.unit, args.scan, args.timeout)
    else:
        print(f"[3/3] 读取 {args.count} 个寄存器 (地址 {args.start}~{args.start + args.count - 1})...")
        try:
            values = read_holding_registers(args.ip, args.port, args.unit, args.start, args.count, args.timeout)
            print(f"  OK - 收到 {len(values)} 个寄存器值:")
            print(f"  {'地址':>6}  {'Hex':>8}  {'Dec':>8}  {'Bin':>18}")
            print(f"  {'-'*6}  {'-'*8}  {'-'*8}  {'-'*18}")
            for i, v in enumerate(values):
                addr = args.start + i
                print(f"  {addr:6d}  0x{v:06X}  {v:8d}  0b{v:016b}")
        except Exception as e:
            print(f"  FAIL - MODBUS 读取失败: {e}")
            sys.exit(1)

    print()
    print("=== 测试全部通过 ===")


def scan_modbus(ip: str, port: int, unit: int, max_addr: int, timeout: float):
    """扫描寄存器地址范围，找到有响应的地址"""
    found = []
    step = 10
    for start in range(0, min(max_addr, 5000), step):
        end = min(start + step, max_addr)
        try:
            values = read_holding_registers(ip, port, unit, start, step, timeout=max(timeout * 0.5, 0.5))
            for i, v in enumerate(values):
                addr = start + i
                if v != 0:
                    found.append((addr, v))
            print(f"  [{start:4d}-{end-1:4d}] OK ({len([x for x in values if x != 0])} 个非零)")
        except Exception as e:
            print(f"  [{start:4d}-{end-1:4d}] FAIL: {e}")

    if found:
        print(f"\n  发现 {len(found)} 个非零寄存器:")
        for addr, val in found:
            print(f"    地址 {addr:5d}: {val:6d} (0x{val:04X})")
    else:
        print(f"\n  未发现非零寄存器，所有读取位置均为 0")


if __name__ == "__main__":
    main()
