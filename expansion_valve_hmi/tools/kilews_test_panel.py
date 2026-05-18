"""
Kilews 拧紧枪 MODBUS TCP 测试面板
在目标工控机上运行: python tools/kilews_test_panel.py
浏览器打开: http://127.0.0.1:8090
"""
from __future__ import annotations

import json
import struct
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# ============================================================
# MODBUS TCP 客户端
# ============================================================

class ModbusClient:
    def __init__(self):
        self.ip = "192.168.0.105"
        self.port = 502
        self.unit_id = 1
        self.timeout = 2.0
        self.connected = False
        self._lock = threading.Lock()
        self._tid = 0

    def connect(self, ip: str, port: int = 502, unit_id: int = 1) -> bool:
        self.ip = ip
        self.port = port
        self.unit_id = unit_id
        try:
            s = socket.create_connection((ip, port), timeout=3)
            s.close()
            self.connected = True
            return True
        except Exception:
            self.connected = False
            return False

    def disconnect(self):
        self.connected = False

    def read_registers(self, start: int, count: int, func: int = 3) -> list[int] | None:
        """读取保持寄存器(3)或输入寄存器(4)"""
        if count < 1 or count > 125:
            return None
        with self._lock:
            self._tid = (self._tid + 1) % 65536
            tid = self._tid
        pdu = struct.pack(">BHH", func, start, count)
        mbap = struct.pack(">HHHB", tid, 0, len(pdu) + 1, self.unit_id)
        try:
            sock = socket.create_connection((self.ip, self.port), timeout=self.timeout)
            try:
                sock.sendall(mbap + pdu)
                header = sock.recv(7)
                if len(header) < 7:
                    return None
                rx_tid, _, length, _ = struct.unpack(">HHHB", header)
                if rx_tid != tid:
                    return None
                remaining = length - 1
                payload = bytearray()
                while len(payload) < remaining:
                    chunk = sock.recv(remaining - len(payload))
                    if not chunk:
                        break
                    payload.extend(chunk)
            finally:
                sock.close()
            if not payload or payload[0] != func:
                return None
            byte_count = payload[1]
            data = payload[2:2 + byte_count]
            return [struct.unpack(">H", data[i:i+2])[0] for i in range(0, len(data), 2)]
        except Exception:
            self.connected = False
            return None

    def write_register(self, addr: int, value: int) -> bool:
        """写单个保持寄存器 (功能码 06)"""
        with self._lock:
            self._tid = (self._tid + 1) % 65536
            tid = self._tid
        pdu = struct.pack(">BHH", 6, addr, value)
        mbap = struct.pack(">HHHB", tid, 0, len(pdu) + 1, self.unit_id)
        try:
            sock = socket.create_connection((self.ip, self.port), timeout=self.timeout)
            try:
                sock.sendall(mbap + pdu)
                resp = sock.recv(12)
            finally:
                sock.close()
            return len(resp) == 12 and resp[7] == 6
        except Exception:
            return False

    def write_registers(self, start: int, values: list[int]) -> bool:
        """写多个保持寄存器 (功能码 16 / 0x10)"""
        count = len(values)
        with self._lock:
            self._tid = (self._tid + 1) % 65536
            tid = self._tid
        pdu = struct.pack(">BHHB", 0x10, start, count, count * 2)
        for v in values:
            pdu += struct.pack(">H", v)
        mbap = struct.pack(">HHHB", tid, 0, len(pdu) + 1, self.unit_id)
        try:
            sock = socket.create_connection((self.ip, self.port), timeout=self.timeout)
            try:
                sock.sendall(mbap + pdu)
                resp = sock.recv(12)
            finally:
                sock.close()
            return len(resp) == 12 and resp[7] == 0x10
        except Exception:
            return False


# ============================================================
# 设备状态缓存 — KL-NTCS-M7
# ============================================================

class KilewsDevice:
    """Kilews KL-NTCS-M7 状态管理 — 正确寄存器映射"""

    # 扭力单位映射 (寄存器 264)
    UNIT_MAP = {0: ("kgf·m", 10000), 1: ("N·m", 1000), 2: ("kgf·cm", 100),
                3: ("lbf·in", 100), 4: ("cN·m", 10)}
    RESULT_CODES = {4: "OK", 5: "OK-SEQ", 6: "OK-JOB", 7: "NG", 8: "NS"}
    TOOL_MODES = {0: "锁附", 1: "退锁"}

    def __init__(self):
        self.modbus = ModbusClient()
        self._thread: threading.Thread | None = None
        self._polling = False

        # --- 实时状态 (4305-4346) ---
        self.current_job = 0
        self.current_seq = 0
        self.current_step = 0
        self.current_count = 0
        self.tool_mode = 0
        self.enabled = False
        self.running = False

        # --- 拧紧结果 (4155-4164) ---
        self.torque_raw = 0        # 4155-4156 32-bit, 扭力×倍率
        self.angle_raw = 0         # 4159-4160 32-bit 角度 (0.1°)
        self.result_code = 0       # 4164: 4=OK, 7=NG
        self.tighten_time_ms = 0   # 4158

        # --- RTC (4096-4101) ---
        self.rtc = {"year": 0, "month": 0, "day": 0, "hour": 0, "min": 0, "sec": 0}

        # --- 条码 (4192, 50 regs) ---
        self.barcode = ""

        # --- 流水号 (4285-4286) ---
        self.serial_no = 0

        # --- 扭力单位 (264) ---
        self.torque_unit_code = -1
        self.torque_unit_name = "?"
        self.torque_multiplier = 1000  # 默认 N·m

        # --- 锁付参数 (1144-1162) 步骤一 ---
        self.param_target_type = 0    # 1144: 1=角度, 2=扭矩
        self.param_target_angle = 0   # 1145-1146: 目标角度 (0.1°)
        self.param_target_torque = 0  # 1147-1148: 目标扭矩 (×倍率)
        self.param_speed = 0          # 1151: 转速
        self.param_torque_hi = 0      # 1155-1156: 扭矩上限
        self.param_torque_lo = 0      # 1157-1158: 扭矩下限
        self.param_angle_hi = 0       # 1160-1161: 角度上限 (32-bit, 0.1°)
        self.param_angle_lo = 0       # 1162-1163: 角度下限 (32-bit, 0.1°)

        # --- 原始寄存器 ---
        self.reg_status = {}
        self.reg_result = {}
        self.reg_rtc = {}
        self.reg_params = {}
        self.last_update = ""

    def _decode_torque(self, raw: int) -> float:
        return raw / self.torque_multiplier

    def _decode_angle(self, raw: int) -> float:
        return raw / 10.0

    @property
    def torque_nm(self) -> float:
        return self._decode_torque(self.torque_raw)

    @property
    def angle_deg(self) -> float:
        return self._decode_angle(self.angle_raw)

    def to_dict(self) -> dict:
        return {
            "connected": self.modbus.connected,
            "ip": self.modbus.ip, "port": self.modbus.port, "unit_id": self.modbus.unit_id,
            "enabled": self.enabled, "running": self.running,
            "currentJob": self.current_job, "currentSeq": self.current_seq,
            "currentStep": self.current_step, "currentCount": self.current_count,
            "toolMode": self.tool_mode,
            "resultCode": self.result_code, "torqueRaw": self.torque_raw,
            "torqueNm": round(self.torque_nm, 3),
            "angleRaw": self.angle_raw, "angleDeg": round(self.angle_deg, 1),
            "tightenTimeMs": self.tighten_time_ms,
            "rtc": self.rtc, "barcode": self.barcode, "serialNo": self.serial_no,
            "torqueUnitCode": self.torque_unit_code,
            "torqueUnitName": self.torque_unit_name,
            "torqueMultiplier": self.torque_multiplier,
            "params": {
                "targetType": self.param_target_type,
                "targetAngle": self.param_target_angle,
                "targetTorque": self.param_target_torque,
                "speed": self.param_speed,
                "torqueHi": self.param_torque_hi,
                "torqueLo": self.param_torque_lo,
                "angleHi": self.param_angle_hi,
                "angleLo": self.param_angle_lo,
            },
            "regStatus": self.reg_status, "regResult": self.reg_result,
            "regRtc": self.reg_rtc, "regParams": self.reg_params,
            "lastUpdate": self.last_update,
        }

    def read_unit(self) -> bool:
        """读取扭力单位寄存器 (264)"""
        vals = self.modbus.read_registers(264, 1)
        if vals and len(vals) >= 1:
            self.torque_unit_code = vals[0]
            name, mult = self.UNIT_MAP.get(vals[0], ("?", 1000))
            self.torque_unit_name = name
            self.torque_multiplier = mult
            return True
        return False

    def read_parameters(self) -> bool:
        """读取锁付参数 (1144-1163, 20 regs)"""
        vals = self.modbus.read_registers(1144, 20)
        if vals and len(vals) >= 20:
            self.reg_params = {1144 + i: v for i, v in enumerate(vals) if v != 0}
            self.param_target_type = vals[0]          # 1144
            self.param_target_angle = (vals[1] << 16) | vals[2]   # 1145-1146
            self.param_target_torque = (vals[3] << 16) | vals[4]  # 1147-1148
            self.param_speed = vals[7]                 # 1151
            self.param_torque_hi = (vals[11] << 16) | vals[12]   # 1155-1156
            self.param_torque_lo = (vals[13] << 16) | vals[14]   # 1157-1158
            self.param_angle_hi = (vals[16] << 16) | vals[17]    # 1160-1161 (32-bit)
            self.param_angle_lo = (vals[18] << 16) | vals[19]    # 1162-1163 (32-bit)
            return True
        return False

    def write_parameter(self, addr: int, value: int, is_32bit: bool = False) -> bool:
        """写入单个参数 (自动判断 16/32-bit)"""
        if is_32bit:
            hi = (value >> 16) & 0xFFFF
            lo = value & 0xFFFF
            return self.modbus.write_registers(addr, [hi, lo])
        return self.modbus.write_register(addr, value)

    def refresh(self):
        if not self.modbus.connected:
            return

        # 0. 扭力单位 (264)
        self.read_unit()

        # 1. RTC (4096, 6)
        vals = self.modbus.read_registers(4096, 6)
        if vals and len(vals) >= 6:
            self.reg_rtc = {4096 + i: v for i, v in enumerate(vals)}
            self.rtc = {"year": vals[0], "month": vals[1], "day": vals[2],
                        "hour": vals[3], "min": vals[4], "sec": vals[5]}

        # 2. 拧紧结果 (4155, 10) 覆盖 4155-4164
        vals = self.modbus.read_registers(4155, 10)
        if vals and len(vals) >= 10:
            self.reg_result = {4155 + i: v for i, v in enumerate(vals) if v != 0}
            self.torque_raw = (vals[0] << 16) | vals[1]
            self.angle_raw = (vals[4] << 16) | vals[5]
            self.tighten_time_ms = vals[3]
            self.result_code = vals[9]

        # 3. 锁付参数 (1144, 20)
        self.read_parameters()

        # 4. 实时状态 (4305, 42)
        vals = self.modbus.read_registers(4305, 42)
        if vals and len(vals) >= 42:
            self.reg_status = {4305 + i: v for i, v in enumerate(vals) if v != 0}
            self.current_job = vals[0]
            self.current_seq = vals[1]
            self.current_step = vals[2]
            self.current_count = vals[3]
            self.tool_mode = vals[39]
            self.enabled = vals[40] == 1
            self.running = vals[41] == 1

        # 5. 条码 (4192, 50)
        vals = self.modbus.read_registers(4192, 50)
        if vals:
            chars = []
            for v in vals:
                hi = (v >> 8) & 0xFF
                lo = v & 0xFF
                if hi: chars.append(chr(hi) if 32 <= hi < 127 else '.')
                if lo: chars.append(chr(lo) if 32 <= lo < 127 else '.')
            self.barcode = ''.join(chars).strip('\x00 .')

        # 6. 流水号 (4285, 2)
        vals = self.modbus.read_registers(4285, 2)
        if vals and len(vals) >= 2:
            self.serial_no = (vals[0] << 16) | vals[1]

        self.last_update = time.strftime("%Y-%m-%d %H:%M:%S")

    def start_polling(self, interval: float = 1.5):
        if self._polling:
            return
        self._polling = True
        self._thread = threading.Thread(target=self._poll_loop, args=(interval,), daemon=True)
        self._thread.start()

    def stop_polling(self):
        self._polling = False

    def _poll_loop(self, interval: float):
        while self._polling:
            try:
                self.refresh()
            except Exception:
                pass
            time.sleep(interval)


# ============================================================
# 全局设备实例
# ============================================================
device = KilewsDevice()

RESULT_CODES = {4: "OK", 5: "OK-SEQ", 6: "OK-JOB", 7: "NG", 8: "NS"}
TOOL_MODES = {0: "锁附", 1: "退锁"}


# ============================================================
# HTTP 服务器
# ============================================================

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>KL-NTCS-M7 拧紧枪测试面板</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI','Microsoft YaHei',sans-serif;background:#1a1d23;color:#e0e0e0;min-height:100vh;padding:1rem}
.container{max-width:1400px;margin:0 auto}
h1{font-size:1.4rem;color:#61dafb;margin-bottom:0.5rem}
h2{font-size:1rem;color:#a0c4ff;margin-bottom:0.6rem}
.card{background:#252830;border-radius:12px;padding:1rem;margin-bottom:0.8rem;border:1px solid #333}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:0.8rem}
.row{display:flex;gap:0.6rem;align-items:end;flex-wrap:wrap}
.row>*{flex:1;min-width:120px}
label{display:block;font-size:0.75rem;color:#8899aa;margin-bottom:0.2rem}
input,select,button{padding:0.5rem 0.7rem;border-radius:6px;border:1px solid #444;background:#1e2127;color:#ddd;font-size:0.85rem;width:100%}
button{cursor:pointer;background:#2c5282;color:white;border:none;font-weight:600;transition:0.15s}
button:hover{opacity:0.85}
button.danger{background:#9b2c2c}
button.success{background:#276749}
button.warn{background:#975a16}
.status-led{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}
.led-green{background:#48bb78;box-shadow:0 0 6px #48bb78}
.led-red{background:#f56565;box-shadow:0 0 6px #f56565}
.info-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:0.4rem}
.info-item{background:#1e2127;padding:0.5rem 0.7rem;border-radius:6px;display:flex;justify-content:space-between;align-items:center}
.info-label{color:#8899aa;font-size:0.78rem}
.info-value{font-family:'JetBrains Mono','Consolas',monospace;font-weight:600;color:#e2e8f0}
.reg-table{font-family:'JetBrains Mono','Consolas',monospace;font-size:0.72rem}
.reg-table th{color:#61dafb;text-align:left;padding:0.2rem 0.4rem;position:sticky;top:0;background:#252830}
.reg-table td{padding:0.15rem 0.4rem;border-bottom:1px solid #1e2127}
.reg-table tr:hover{background:#2d3239}
.reg-table .non-zero{color:#f6e05e}.reg-table .zero{color:#4a5568}
.reg-wrap{max-height:400px;overflow:auto;border:1px solid #333;border-radius:8px}
.alert{background:#742a2a;color:#fed7d7;padding:0.5rem 0.8rem;border-radius:6px;margin-top:0.5rem}
.success-msg{background:#22543d;color:#c6f6d5;padding:0.5rem 0.8rem;border-radius:6px;margin-top:0.5rem}
.tabs{display:flex;gap:0.3rem;margin-bottom:1rem}
.tab-btn{padding:0.4rem 1rem;background:#2d3239;border:1px solid #444;color:#aaa;cursor:pointer;border-radius:8px 8px 0 0;width:auto}
.tab-btn.active{background:#252830;color:#61dafb;border-bottom-color:#252830}
.tab-content{display:none}
.tab-content.active{display:block}
.result-display{font-size:2.5rem;font-weight:700;font-family:'JetBrains Mono','Consolas',monospace}
.result-badge{display:inline-block;font-size:1.8rem;font-weight:700;padding:0.4rem 1.2rem;border-radius:10px;margin:0.3rem}
.badge-ok{background:#22543d;color:#48bb78}.badge-ng{background:#742a2a;color:#f56565}.badge-ns{background:#744210;color:#ecc94b}
@media(max-width:900px){.grid2{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="container">
<h1>KL-NTCS-M7 拧紧枪 MODBUS 测试面板</h1>

<div class="tabs">
  <button class="tab-btn active" data-tab="status">设备状态</button>
  <button class="tab-btn" data-tab="result">拧紧结果</button>
  <button class="tab-btn" data-tab="params">参数设置</button>
  <button class="tab-btn" data-tab="control">远程控制</button>
  <button class="tab-btn" data-tab="registers">寄存器浏览器</button>
</div>

<!-- 连接栏 -->
<div class="card">
  <div class="row">
    <div style="flex:2"><label>拧紧枪 IP</label><input id="ip" value="192.168.0.105"></div>
    <div style="flex:1"><label>端口</label><input id="port" value="502"></div>
    <div style="flex:1"><label>Unit ID</label><input id="unitId" value="1"></div>
    <div style="flex:0 0 auto"><label>&nbsp;</label><button id="connectBtn">连接</button></div>
    <div style="flex:0 0 auto"><label>&nbsp;</label><button id="disconnectBtn" class="danger">断开</button></div>
  </div>
  <div id="connMsg" style="margin-top:0.5rem;font-size:0.85rem">未连接</div>
</div>

<!-- Tab 1: 设备状态 -->
<div id="tab-status" class="tab-content active">
  <div class="grid2">
    <div class="card">
      <h2>实时状态 (4305-4346)</h2>
      <div class="info-grid">
        <div class="info-item"><span class="info-label">连接</span><span class="info-value" id="s_conn">--</span></div>
        <div class="info-item"><span class="info-label">起子启用</span><span class="info-value" id="s_enable">--</span></div>
        <div class="info-item"><span class="info-label">运转状态</span><span class="info-value" id="s_run">--</span></div>
        <div class="info-item"><span class="info-label">当前 JOB</span><span class="info-value" id="s_job">--</span></div>
        <div class="info-item"><span class="info-label">当前工序</span><span class="info-value" id="s_seq">--</span></div>
        <div class="info-item"><span class="info-label">当前步骤</span><span class="info-value" id="s_step">--</span></div>
        <div class="info-item"><span class="info-label">当前颗数</span><span class="info-value" id="s_count">--</span></div>
        <div class="info-item"><span class="info-label">起子模式</span><span class="info-value" id="s_mode">--</span></div>
        <div class="info-item"><span class="info-label">流水号</span><span class="info-value" id="s_serial">--</span></div>
        <div class="info-item"><span class="info-label">更新时间</span><span class="info-value" id="s_time">--</span></div>
      </div>
      <div style="margin-top:0.6rem"><button id="refreshBtn">刷新</button></div>
    </div>
    <div class="card">
      <h2>最近拧紧结果</h2>
      <div class="info-grid">
        <div class="info-item"><span class="info-label">扭力</span><span class="info-value" id="s_torque">--</span></div>
        <div class="info-item"><span class="info-label">扭力原始值</span><span class="info-value" id="s_torqueNm">--</span></div>
        <div class="info-item"><span class="info-label">角度</span><span class="info-value" id="s_angle">--</span></div>
        <div class="info-item"><span class="info-label">角度原始值</span><span class="info-value" id="s_angleDeg">--</span></div>
        <div class="info-item"><span class="info-label">结果码 (4164)</span><span class="info-value" id="s_result">--</span></div>
        <div class="info-item"><span class="info-label">单位 (264)</span><span class="info-value" id="s_unit">--</span></div>
        <div class="info-item"><span class="info-label">锁附时间 (4158)</span><span class="info-value" id="s_time_ms">--</span></div>
        <div class="info-item" style="grid-column:1/-1"><span class="info-label">时间戳</span><span class="info-value" id="s_rtc">--</span></div>
        <div class="info-item" style="grid-column:1/-1"><span class="info-label">条码</span><span class="info-value" id="s_barcode" style="font-size:0.75rem;word-break:break-all">--</span></div>
      </div>
    </div>
  </div>
</div>

<!-- Tab 2: 拧紧结果 (大字体) -->
<div id="tab-result" class="tab-content">
  <div class="card" style="text-align:center">
    <div id="r_badge"></div>
    <div class="grid2" style="margin-top:1rem">
      <div>
        <div style="color:#8899aa;font-size:0.85rem">扭力</div>
        <div class="result-display result-ok" id="r_torque">--</div>
        <div style="color:#4a5568;font-size:0.75rem">4155-4156 (32-bit) / ×倍率</div>
      </div>
      <div>
        <div style="color:#8899aa;font-size:0.85rem">角度</div>
        <div class="result-display" style="color:#61dafb" id="r_angle">--</div>
        <div style="color:#4a5568;font-size:0.75rem">4159-4160 (32-bit) / 0.1°</div>
      </div>
    </div>
    <div class="info-grid" style="margin-top:1rem">
      <div class="info-item"><span class="info-label">锁附时间</span><span class="info-value" id="r_time_ms">--</span></div>
      <div class="info-item"><span class="info-label">流水号</span><span class="info-value" id="r_serial">--</span></div>
      <div class="info-item"><span class="info-label">颗数</span><span class="info-value" id="r_count">--</span></div>
      <div class="info-item"><span class="info-label">JOB / 工序 / 步骤</span><span class="info-value" id="r_jobinfo">--</span></div>
      <div class="info-item" style="grid-column:1/-1"><span class="info-label">时间戳</span><span class="info-value" id="r_rtc">--</span></div>
      <div class="info-item" style="grid-column:1/-1"><span class="info-label">条码</span><span class="info-value" id="r_barcode" style="font-size:0.75rem;word-break:break-all">--</span></div>
    </div>
  </div>
</div>

<!-- Tab 3: 参数设置 -->
<div id="tab-params" class="tab-content">
  <div class="card">
    <h2>扭力单位</h2>
    <div class="info-grid">
      <div class="info-item"><span class="info-label">单位码 (264)</span><span class="info-value" id="p_unitCode">--</span></div>
      <div class="info-item"><span class="info-label">单位名称</span><span class="info-value" id="p_unitName">--</span></div>
      <div class="info-item"><span class="info-label">倍率</span><span class="info-value" id="p_multiplier">--</span></div>
    </div>
    <div style="margin-top:0.5rem"><button id="p_readBtn">读取参数</button></div>
    <div id="p_readMsg" style="margin-top:0.3rem;font-size:0.78rem;color:#8899aa"></div>
  </div>

  <div class="card">
    <h2>步骤一锁付参数 (1144-1162)</h2>
    <div class="grid2">
      <div>
        <div class="info-grid">
          <div class="info-item"><span class="info-label">目标类型 (1144)</span><span class="info-value" id="p_type">-- <small style="color:#8899aa">1=角度 2=扭矩</small></span></div>
          <div class="info-item"><span class="info-label">目标角度 (1145-46)</span><span class="info-value" id="p_angle">-- °</span></div>
          <div class="info-item"><span class="info-label">目标扭矩 (1147-48)</span><span class="info-value" id="p_torque">--</span></div>
          <div class="info-item"><span class="info-label">转速 (1151)</span><span class="info-value" id="p_speed">-- rpm</span></div>
        </div>
      </div>
      <div>
        <div class="info-grid">
          <div class="info-item"><span class="info-label">扭矩上限 (1155-56)</span><span class="info-value" id="p_thi">--</span></div>
          <div class="info-item"><span class="info-label">扭矩下限 (1157-58)</span><span class="info-value" id="p_tlo">--</span></div>
          <div class="info-item"><span class="info-label">角度上限 (1160-61)</span><span class="info-value" id="p_ahi">-- °</span></div>
          <div class="info-item"><span class="info-label">角度下限 (1162-63)</span><span class="info-value" id="p_alo">-- °</span></div>
        </div>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>写入参数 — MODBUS 工作 221 / 工序 1 / 步骤 1</h2>
    <p style="font-size:0.78rem;color:#8899aa;margin-bottom:0.5rem">
      工作号 221 (Modbus专用) / 工序 1 / 步骤 1。目标类型选<strong>2-扭矩控制</strong>时角度为监控上下限；
      选<strong>1-角度控制</strong>时扭矩为监控上下限。
    </p>
    <div class="row" style="align-items:end;margin-bottom:0.5rem">
      <div style="flex:1"><label>目标扭矩 N·m</label><input id="w_torque" type="number" value="4.55" step="0.001"></div>
      <div style="flex:1"><label>扭矩上限 N·m</label><input id="w_thi" type="number" value="5.0" step="0.001"></div>
      <div style="flex:1"><label>扭矩下限 N·m</label><input id="w_tlo" type="number" value="3.5" step="0.001"></div>
    </div>
    <div class="row" style="align-items:end;margin-bottom:0.5rem">
      <div style="flex:1"><label>目标角度 °<br><small style="color:#8899aa">仅角度模式</small></label><input id="w_angle" type="number" value="90.0" step="0.1"></div>
      <div style="flex:1"><label>角度监控上限 °</label><input id="w_ahi" type="number" value="180.0" step="0.1"></div>
      <div style="flex:1"><label>角度监控下限 °</label><input id="w_alo" type="number" value="0" step="0.1"></div>
      <div style="flex:1"><label>转速 rpm</label><input id="w_speed" type="number" value="500"></div>
      <div style="flex:1"><label>目标类型</label><select id="w_type"><option value="2" selected>2-扭矩控制</option><option value="1">1-角度控制</option></select></div>
    </div>
    <button id="w_allBtn" class="success" style="width:100%">一键写入：开步骤 → 写全部参数 → 切221 → 补写角度</button>
    <div id="w_msg" style="margin-top:0.4rem"></div>
  </div>
</div>

<!-- Tab 4: 远程控制 -->
<div id="tab-control" class="tab-content">
  <div class="card">
    <div class="alert" style="margin-top:0;margin-bottom:0.8rem">
      <strong>重要:</strong> KL-NTCS-M7 不支持通过 Modbus 写入拧紧参数。只能切换已在控制器上建好的工作/工序。远程启动前请将控制器设为【远程启动】模式。
    </div>

    <h2>工作/工序切换</h2>
    <div class="row" style="align-items:end;margin-bottom:0.8rem">
      <div style="flex:0 0 auto;min-width:140px">
        <label>切换工作编号 (写 463, 范围 1-99/101-170, 221=Modbus)</label>
        <input id="c_job" type="number" value="1" min="1" max="221">
      </div>
      <div style="flex:0 0 auto;min-width:140px">
        <label>切换工序编号 (写 464, 范围 1-99)</label>
        <input id="c_seq" type="number" value="1" min="1" max="99">
      </div>
      <div style="flex:0 0 auto"><label>&nbsp;</label><button id="c_switchJobBtn" class="success">切换工作</button></div>
      <div style="flex:0 0 auto"><label>&nbsp;</label><button id="c_switchSeqBtn" class="warn">切换工序</button></div>
      <span id="c_switchMsg" style="font-size:0.78rem;color:#8899aa;margin-left:0.5rem"></span>
    </div>

    <h2>起子控制</h2>
    <div style="display:flex;gap:0.4rem;flex-wrap:wrap">
      <button id="c_startBtn" class="success">启动 (456=1)</button>
      <button id="c_stopBtn" class="danger">停止 (456=0)</button>
      <button id="c_reverseBtn" class="warn">退螺丝 (457=1)</button>
      <button id="c_confirmBtn">确认解锁 (458=1)</button>
      <button id="c_clearCountBtn">清除颗数 (459=1)</button>
      <button id="c_clearSeqBtn">清除工序 (460=1)</button>
      <button id="c_disableBtn" class="warn">禁用起子 (461=0)</button>
      <button id="c_enableBtn" class="success">启用起子 (461=1)</button>
    </div>
    <div style="margin-top:0.4rem">
      <button id="c_rebootBtn" style="background:#742a2a;width:auto">重启控制器 (462=1)</button>
    </div>
    <div id="c_ctrlMsg" style="margin-top:0.4rem"></div>
  </div>
</div>

<!-- Tab 4: 寄存器浏览器 -->
<div id="tab-registers" class="tab-content">
  <div class="card">
    <h2>读取寄存器</h2>
    <div class="row" style="align-items:end">
      <div style="flex:1"><label>起始地址</label><input id="regStart" type="number" value="4096"></div>
      <div style="flex:1"><label>数量 (max 125)</label><input id="regCount" type="number" value="10" max="125"></div>
      <div style="flex:0 0 auto"><label>&nbsp;</label><button id="readRegBtn" class="success">读取</button></div>
    </div>
    <div id="regResult" style="margin-top:0.5rem"></div>
  </div>
  <div class="card">
    <h2>写入单寄存器</h2>
    <div class="row" style="align-items:end">
      <div style="flex:1"><label>地址</label><input id="writeAddr" type="number" value="456"></div>
      <div style="flex:1"><label>值 (0-65535)</label><input id="writeVal" type="number" value="1"></div>
      <div style="flex:0 0 auto"><label>&nbsp;</label><button id="writeBtn" class="warn">写入</button></div>
    </div>
    <div id="writeResult" style="margin-top:0.5rem"></div>
  </div>
  <div class="card">
    <h2>快速读取关键区域</h2>
    <div style="display:flex;gap:0.3rem;flex-wrap:wrap;margin-bottom:0.5rem">
      <button id="qrRTC" style="width:auto">RTC (4096,6)</button>
      <button id="qrTorque" style="width:auto">扭力 (4155,2)</button>
      <button id="qrResult" style="width:auto">结果区 (4155,10)</button>
      <button id="qrStatus" style="width:auto">状态 (4305,42)</button>
      <button id="qrBarcode" style="width:auto">条码 (4192,50)</button>
      <button id="qrSerial" style="width:auto">流水号 (4285,2)</button>
    </div>
    <div id="qrResultEl" style="margin-top:0.5rem;font-family:'JetBrains Mono',monospace;font-size:0.72rem"></div>
  </div>
</div>

</div>

<script>
const $ = id => document.getElementById(id);

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    $('tab-' + btn.dataset.tab).classList.add('active');
  });
});

async function api(path, body=null) {
  const opts = body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {};
  const r = await fetch('/api' + path, opts);
  return r.json();
}

function msgEl(id, text, cls, isHtml) {
  const el = $(id);
  if (isHtml) el.innerHTML = text; else el.textContent = text;
  el.className = cls || '';
}

// ============ 连接 ============

$('connectBtn').addEventListener('click', async () => {
  msgEl('connMsg', '连接中...', '');
  const r = await api('/connect', {ip:$('ip').value, port:parseInt($('port').value), unit_id:parseInt($('unitId').value)});
  if(r.ok) {
    msgEl('connMsg', '已连接 ' + r.ip + ':' + r.port, 'success-msg');
    setTimeout(refreshAll, 300);
    startPolling();
  } else {
    msgEl('connMsg', '连接失败: ' + r.error, 'alert');
  }
});

$('disconnectBtn').addEventListener('click', async () => {
  stopPolling();
  await api('/disconnect', {});
  msgEl('connMsg', '已断开', '');
});

// ============ 状态刷新 ============

function decodeRTC(rtc) {
  const y=rtc.year||0, mo=rtc.month||0, d=rtc.day||0, h=rtc.hour||0, mi=rtc.min||0, s=rtc.sec||0;
  if(!y) return '--';
  return y+'-'+String(mo).padStart(2,'0')+'-'+String(d).padStart(2,'0')+' '+
         String(h).padStart(2,'0')+':'+String(mi).padStart(2,'0')+':'+String(s).padStart(2,'0');
}

const RESULT_MAP = {4:'OK',5:'OK-SEQ',6:'OK-JOB',7:'NG',8:'NS'};
const MODE_MAP = {0:'锁附',1:'退锁'};

async function refreshAll() {
  try {
    const s = await api('/status');

    $('s_conn').innerHTML = s.connected ? '<span class="status-led led-green"></span>已连接' : '<span class="status-led led-red"></span>离线';
    $('s_enable').textContent = s.enabled ? '已启用' : '已禁用';
    $('s_run').textContent = s.running ? '运转中' : '停止';
    $('s_job').textContent = s.currentJob || '--';
    $('s_seq').textContent = s.currentSeq || '--';
    $('s_step').textContent = s.currentStep || '--';
    $('s_count').textContent = s.currentCount || '--';
    $('s_mode').textContent = MODE_MAP[s.toolMode] || s.toolMode || '--';
    $('s_serial').textContent = s.serialNo || '--';
    $('s_time').textContent = s.lastUpdate || '--';

    $('s_torque').textContent = s.torqueNm !== undefined ? s.torqueNm + ' ' + s.torqueUnitName : '--';
    $('s_torqueNm').textContent = s.torqueRaw !== undefined ? 'raw: ' + s.torqueRaw : '--';
    $('s_angle').textContent = s.angleDeg !== undefined ? s.angleDeg + ' °' : '--';
    $('s_angleDeg').textContent = s.angleRaw !== undefined ? 'raw: ' + s.angleRaw : '--';
    $('s_unit').textContent = s.torqueUnitName + ' (×' + s.torqueMultiplier + ')';
    const rCode = s.resultCode;
    $('s_result').textContent = RESULT_MAP[rCode] || rCode || '--';
    $('s_time_ms').textContent = s.tightenTimeMs ? s.tightenTimeMs + ' ms' : '--';
    $('s_rtc').textContent = decodeRTC(s.rtc);
    $('s_barcode').textContent = s.barcode || '--';

    // Tab 2: 大字体结果
    const badgeMap = {4:'badge-ok',5:'badge-ok',6:'badge-ok',7:'badge-ng',8:'badge-ns'};
    const badgeCls = badgeMap[rCode] || '';
    $('r_badge').innerHTML = rCode ? '<span class="result-badge '+badgeCls+'">'+(RESULT_MAP[rCode]||rCode)+'</span>' : '--';
    $('r_torque').textContent = s.torqueNm ? s.torqueNm + ' ' + s.torqueUnitName : (s.torqueRaw || '--');
    $('r_angle').textContent = s.angleDeg ? s.angleDeg + ' °' : (s.angleRaw || '--');
    $('r_time_ms').textContent = s.tightenTimeMs ? s.tightenTimeMs + ' ms' : '--';
    $('r_serial').textContent = s.serialNo || '--';
    $('r_count').textContent = s.currentCount || '--';
    $('r_jobinfo').textContent = 'JOB '+(s.currentJob||'?')+' / 工序 '+(s.currentSeq||'?')+' / 步骤 '+(s.currentStep||'?');
    $('r_rtc').textContent = decodeRTC(s.rtc);
    $('r_barcode').textContent = s.barcode || '--';

    // Tab 3: 参数显示
    if (s.params) {
      const p = s.params;
      $('p_unitCode').textContent = s.torqueUnitCode >= 0 ? s.torqueUnitCode : '--';
      $('p_unitName').textContent = s.torqueUnitName || '--';
      $('p_multiplier').textContent = '×' + s.torqueMultiplier;
      $('p_type').innerHTML = (p.targetType || '--') + ' <small style="color:#8899aa">1=角度 2=扭矩</small>';
      $('p_angle').textContent = p.targetAngle ? p.targetAngle + ' °' : '--';
      $('p_torque').textContent = p.targetTorque ? (p.targetTorque / s.torqueMultiplier).toFixed(3) + ' ' + s.torqueUnitName + ' (raw:' + p.targetTorque + ')' : '--';
      $('p_speed').textContent = p.speed ? p.speed + ' rpm' : '--';
      $('p_thi').textContent = p.torqueHi ? (p.torqueHi / s.torqueMultiplier).toFixed(3) + ' ' + s.torqueUnitName + ' (raw:' + p.torqueHi + ')' : '--';
      $('p_tlo').textContent = p.torqueLo ? (p.torqueLo / s.torqueMultiplier).toFixed(3) + ' ' + s.torqueUnitName + ' (raw:' + p.torqueLo + ')' : '--';
      $('p_ahi').textContent = p.angleHi ? p.angleHi + ' °' : '--';
      $('p_alo').textContent = p.angleLo ? p.angleLo + ' °' : '--';
    }
  } catch(e) { console.error(e); }
}

$('refreshBtn').addEventListener('click', refreshAll);

let pollTimer = null;
function startPolling() { if(pollTimer) clearInterval(pollTimer); pollTimer = setInterval(refreshAll, 1500); }
function stopPolling() { if(pollTimer) { clearInterval(pollTimer); pollTimer = null; } }

// ============ 远程控制 ============

async function ctrlWrite(addr, val, label) {
  const r = await api('/write', {addr, value: val});
  msgEl('c_ctrlMsg', label + ' ('+addr+'='+val+'): ' + (r.ok ? 'OK' : 'FAIL: '+r.error), r.ok ? 'success-msg' : 'alert');
  return r.ok;
}

$('c_startBtn').addEventListener('click', () => ctrlWrite(456, 1, '启动'));
$('c_stopBtn').addEventListener('click', () => ctrlWrite(456, 0, '停止'));
$('c_reverseBtn').addEventListener('click', () => ctrlWrite(457, 1, '退螺丝'));
$('c_confirmBtn').addEventListener('click', () => ctrlWrite(458, 1, '确认解锁'));
$('c_clearCountBtn').addEventListener('click', () => ctrlWrite(459, 1, '清除颗数'));
$('c_clearSeqBtn').addEventListener('click', () => ctrlWrite(460, 1, '清除工序'));
$('c_disableBtn').addEventListener('click', () => ctrlWrite(461, 0, '禁用起子'));
$('c_enableBtn').addEventListener('click', () => ctrlWrite(461, 1, '启用起子'));
$('c_rebootBtn').addEventListener('click', async () => {
  if (!confirm('确定要重启控制器吗？')) return;
  await ctrlWrite(462, 1, '重启控制器');
});

$('c_switchJobBtn').addEventListener('click', async () => {
  const job = parseInt($('c_job').value);
  if (job < 1 || (job > 99 && job < 101) || job > 170) {
    msgEl('c_switchMsg', '工作编号范围: 1-99, 101-170', 'alert'); return;
  }
  msgEl('c_switchMsg', '切换中...', '');
  const r = await api('/write', {addr: 463, value: job});
  if (r.ok) { msgEl('c_switchMsg', '已切换到 JOB '+job, 'success-msg'); setTimeout(refreshAll, 500); }
  else msgEl('c_switchMsg', '切换失败: '+r.error, 'alert');
});

$('c_switchSeqBtn').addEventListener('click', async () => {
  const seq = parseInt($('c_seq').value);
  if (seq < 1 || seq > 99) { msgEl('c_switchMsg', '工序编号范围: 1-99', 'alert'); return; }
  msgEl('c_switchMsg', '切换中...', '');
  const r = await api('/write', {addr: 464, value: seq});
  if (r.ok) { msgEl('c_switchMsg', '已切换到工序 '+seq, 'success-msg'); setTimeout(refreshAll, 500); }
  else msgEl('c_switchMsg', '切换失败: '+r.error, 'alert');
});

// ============ 寄存器浏览器 ============

$('readRegBtn').addEventListener('click', async () => {
  const start = parseInt($('regStart').value);
  const count = parseInt($('regCount').value);
  const r = await api('/registers', {start, count});
  if(r.ok) {
    let html = '<div class="reg-wrap"><table class="reg-table"><thead><tr><th>地址</th><th>Dec</th><th>Hex</th><th>ASCII</th></tr></thead><tbody>';
    for(let i=0; i<r.values.length; i++) {
      let v = r.values[i], addr = start+i, cls = v !== 0 ? 'non-zero' : 'zero';
      let hi = String.fromCharCode((v>>8)&0xFF), lo = String.fromCharCode(v&0xFF);
      let ascii = (hi >= ' ' && hi <= '~' ? hi : '.') + (lo >= ' ' && lo <= '~' ? lo : '.');
      html += '<tr class="'+cls+'"><td>'+addr+'</td><td>'+v+'</td><td>0x'+v.toString(16).toUpperCase().padStart(4,'0')+'</td><td>'+ascii+'</td></tr>';
    }
    html += '</tbody></table></div>';
    $('regResult').innerHTML = html;
  } else {
    $('regResult').innerHTML = '<div class="alert">' + r.error + '</div>';
  }
});

$('writeBtn').addEventListener('click', async () => {
  const addr = parseInt($('writeAddr').value), val = parseInt($('writeVal').value);
  const r = await api('/write', {addr, value: val});
  msgEl('writeResult', r.ok ? '写入成功: ['+addr+'] = '+val : '写入失败: '+r.error, r.ok ? 'success-msg' : 'alert');
});

async function quickRead(start, count, label) {
  const r = await api('/registers', {start, count});
  const el = $('qrResultEl');
  if (!r.ok) { el.textContent = label + ' FAIL: ' + r.error; return; }
  let html = '<b>'+label+'</b> ('+start+', '+count+'):<br>';
  for (let i=0; i<r.values.length; i++) {
    const addr = start+i, v = r.values[i];
    html += '['+addr+']=<span style="color:'+(v?'#f6e05e':'#4a5568')+'">'+v+'</span> ';
  }
  el.innerHTML = html;
}
$('qrRTC').addEventListener('click', () => quickRead(4096, 6, 'RTC'));
$('qrTorque').addEventListener('click', () => quickRead(4155, 2, '扭力(32bit)'));
$('qrResult').addEventListener('click', () => quickRead(4155, 10, '结果区'));
$('qrStatus').addEventListener('click', () => quickRead(4305, 42, '状态区'));
$('qrBarcode').addEventListener('click', () => quickRead(4192, 50, '条码'));
$('qrSerial').addEventListener('click', () => quickRead(4285, 2, '流水号'));

// ============ 参数设置 (Tab 3) ============

$('p_readBtn').addEventListener('click', async () => {
  const r = await api('/params/read', {});
  if (r.ok) { msgEl('p_readMsg', '参数已刷新', 'success-msg'); refreshAll(); }
  else msgEl('p_readMsg', '读取失败: ' + r.error, 'alert');
});

$('w_allBtn').addEventListener('click', async () => {
  const params = {
    job: 221,
    seq: 1,
    torque: parseFloat($('w_torque').value),
    torqueHi: parseFloat($('w_thi').value),
    torqueLo: parseFloat($('w_tlo').value),
    angle: parseFloat($('w_angle').value),
    angleHi: parseFloat($('w_ahi').value),
    angleLo: parseFloat($('w_alo').value),
    speed: parseInt($('w_speed').value),
    targetType: parseInt($('w_type').value),
  };
  msgEl('w_msg', '写入中...', '');
  const r = await api('/params/write_all', params);
  if (r.steps) {
    let html = '<table style="font-size:0.78rem;width:100%;border-collapse:collapse">';
    html += '<tr style="color:#8899aa"><th style="text-align:left">步骤</th><th>地址</th><th>写入前</th><th>期望</th><th>写入后</th><th>结果</th></tr>';
    for (const s of r.steps) {
      const changed = s.changed;
      const rowColor = changed ? '#22543d' : (s.writeOk ? '#744210' : '#742a2a');
      const icon = changed ? 'OK' : (s.writeOk ? '?' : 'FAIL');
      html += '<tr style="background:' + rowColor + '">';
      html += '<td>' + s.label + '</td>';
      html += '<td>' + s.addr + '</td>';
      html += '<td>' + (s.before !== null ? s.before : '-') + '</td>';
      html += '<td>' + s.expected + '</td>';
      html += '<td>' + (s.after !== null ? s.after : '-') + '</td>';
      html += '<td><b>' + icon + '</b>' + (s.note ? ' <small>' + s.note + '</small>' : '') + '</td>';
      html += '</tr>';
    }
    html += '</table>';
    const allOk = r.steps.every(s => s.changed);
    const cls = allOk ? 'success-msg' : 'alert';
    msgEl('w_msg', html, cls, true);
  } else {
    msgEl('w_msg', '写入失败: ' + (r.error || 'unknown'), 'alert');
  }
  setTimeout(refreshAll, 800);
});

refreshAll();
</script>
</body>
</html>"""

class PanelHandler(BaseHTTPRequestHandler):
    server_version = "KilewsTestPanel/0.2"

    def log_message(self, fmt, *args):
        print("[%s] %s %s" % (self.log_date_time_string(), self.address_string(), fmt % args))

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        try:
            self._do_GET()
        except Exception:
            import traceback
            traceback.print_exc()

    def _do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self.html_response(HTML_PAGE)
        elif parsed.path == "/api/status":
            self.json_response(device.to_dict())
        else:
            self.json_response({"ok": False, "error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        try:
            self._do_POST()
        except Exception:
            import traceback
            traceback.print_exc()
            try:
                self.json_response({"ok": False, "error": "internal error"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            except Exception:
                pass

    def _do_POST(self):
        parsed = urlparse(self.path)
        body = self.read_json()

        if parsed.path == "/api/connect":
            ok = device.modbus.connect(
                ip=body.get("ip", "192.168.0.105"),
                port=int(body.get("port", 502)),
                unit_id=int(body.get("unit_id", 1)),
            )
            if ok:
                device.start_polling()
                device.refresh()
                self.json_response({"ok": True, "ip": device.modbus.ip, "port": device.modbus.port})
            else:
                self.json_response({"ok": False, "error": "无法连接到设备"}, HTTPStatus.BAD_REQUEST)

        elif parsed.path == "/api/disconnect":
            device.stop_polling()
            device.modbus.disconnect()
            self.json_response({"ok": True})

        elif parsed.path == "/api/status":
            device.refresh()
            self.json_response(device.to_dict())

        elif parsed.path == "/api/registers":
            start = int(body.get("start", 0))
            count = min(int(body.get("count", 100)), 125)
            values = device.modbus.read_registers(start, count)
            if values is not None:
                self.json_response({"ok": True, "start": start, "count": len(values), "values": values})
            else:
                self.json_response({"ok": False, "error": "读取失败"}, HTTPStatus.BAD_REQUEST)

        elif parsed.path == "/api/write":
            addr = int(body.get("addr", 0))
            value = int(body.get("value", 0))
            if not (0 <= value <= 65535):
                self.json_response({"ok": False, "error": "值超出范围 0-65535"}, HTTPStatus.BAD_REQUEST)
                return
            ok = device.modbus.write_register(addr, value)
            if ok:
                self.json_response({"ok": True, "addr": addr, "value": value})
            else:
                self.json_response({"ok": False, "error": "写入失败"}, HTTPStatus.BAD_REQUEST)

        elif parsed.path == "/api/params/read":
            ok = device.read_parameters()
            device.read_unit()
            self.json_response({"ok": ok, "params": device.to_dict()["params"],
                                "unitCode": device.torque_unit_code,
                                "unitName": device.torque_unit_name,
                                "multiplier": device.torque_multiplier})

        elif parsed.path == "/api/params/write_all":
            # 完整流程: 切JOB → 切SEQ → 开步骤 → 写参数 → 生效
            # 每步写入后回读验证，真实反映控制器状态
            job = int(body.get("job", 1))
            seq = int(body.get("seq", 1))
            device.read_unit()
            mult = device.torque_multiplier

            import time

            report = []
            errors = []

            def do_write(addr, val, is32, label):
                """写入并回读验证"""
                # 读前值
                before = None
                if not is32:
                    r = device.modbus.read_registers(addr, 1)
                    if r and len(r) >= 1:
                        before = r[0]
                else:
                    r = device.modbus.read_registers(addr, 2)
                    if r and len(r) >= 2:
                        before = (r[0] << 16) | r[1]

                ok = device.write_parameter(addr, val, is32)
                time.sleep(0.15)

                # 读后值
                after = None
                if not is32:
                    r = device.modbus.read_registers(addr, 1)
                    if r and len(r) >= 1:
                        after = r[0]
                else:
                    r = device.modbus.read_registers(addr, 2)
                    if r and len(r) >= 2:
                        after = (r[0] << 16) | r[1]

                changed = (after == val) if after is not None else False
                item = {
                    "label": label, "addr": addr, "is32bit": is32,
                    "writeOk": ok, "before": before, "after": after,
                    "expected": val, "changed": changed
                }
                if not ok:
                    errors.append(f"{label}[{addr}]=MODBUS_FAIL")
                elif not changed and after is not None:
                    item["note"] = f"写入成功但值未变: 期望{val} 实际{after}"
                report.append(item)

            # 1. 开启步骤 (1135)
            do_write(1135, 1, False, "开启步骤")
            # 2. 写参数 (用户真实值 → raw)
            do_write(1144, int(body.get("targetType", 2)), False, "目标类型")
            do_write(1145, int(float(body.get("angle", 0))), True, "目标角度")
            do_write(1147, int(float(body.get("torque", 0)) * mult), True, "目标扭矩")
            do_write(1151, int(body.get("speed", 0)), False, "转速")
            do_write(1155, int(float(body.get("torqueHi", 0)) * mult), True, "扭矩上限")
            do_write(1157, int(float(body.get("torqueLo", 0)) * mult), True, "扭矩下限")
            do_write(1160, int(float(body.get("angleHi", 0))), True, "角度监控上限")
            do_write(1162, int(float(body.get("angleLo", 0))), True, "角度监控下限")
            # 3. 切工作 221 + 工序 1 (会从EEPROM加载，覆盖角度上下限)
            do_write(463, 221, False, "切工作221")
            do_write(464, 1, False, "切工序1")
            # 4. 补写角度监控上下限 (463=221 从EEPROM加载后会被覆盖，需重新写入)
            angle_hi_val = int(float(body.get("angleHi", 0)))
            angle_lo_val = int(float(body.get("angleLo", 0)))
            do_write(1160, angle_hi_val, True, "角度监控上限(补写)")
            do_write(1162, angle_lo_val, True, "角度监控下限(补写)")

            device.read_parameters()
            resp = {
                "ok": len(errors) == 0,
                "written": len(report),
                "job": job, "seq": seq,
                "steps": report,
                "paramsAfter": device.to_dict()["params"],
                "multiplier": mult,
            }
            if errors:
                resp["error"] = "; ".join(errors)
            self.json_response(resp, HTTPStatus.BAD_REQUEST if errors else HTTPStatus.OK)

        elif parsed.path == "/api/params/write":
            addr = int(body.get("addr", 0))
            value = int(body.get("value", 0))
            is_32bit = bool(body.get("is32bit", False))
            ok = device.write_parameter(addr, value, is_32bit)
            if ok:
                device.read_parameters()
                self.json_response({"ok": True, "addr": addr, "value": value})
            else:
                self.json_response({"ok": False, "error": "写入失败"}, HTTPStatus.BAD_REQUEST)

        else:
            self.json_response({"ok": False, "error": "API not found"}, HTTPStatus.NOT_FOUND)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def json_response(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def html_response(self, html):
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(data)




def main():
    host = "0.0.0.0"
    port = 8090
    server = ThreadingHTTPServer((host, port), PanelHandler)
    print("Kilews 拧紧枪测试面板已启动: http://127.0.0.1:%d" % port)
    print("按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n停止中...")
    finally:
        device.stop_polling()
        server.server_close()


if __name__ == "__main__":
    main()
