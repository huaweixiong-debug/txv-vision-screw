"""Kilews KL-NTCS-M7 MODBUS TCP integration.

Real implementation ported from the proven tools/kilews_test_panel.py test panel.
Supports MODBUS FC 03 (read holding), FC 06 (write single), FC 16 (write multiple).
"""

from __future__ import annotations

import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Any

# ============================================================
# Register address constants — KL-NTCS-M7
# ============================================================

REG_TORQUE_UNIT = 264

# Parameter buffer (1144-1163) — Step 1 fastening params
REG_TARGET_TYPE = 1144      # 16-bit, 1=angle 2=torque
REG_TARGET_ANGLE = 1145     # 32-bit (1145-1146), raw degrees
REG_TARGET_TORQUE = 1147    # 32-bit (1147-1148), raw = N.m × multiplier
REG_SPEED = 1151            # 16-bit, RPM
REG_TORQUE_HI = 1155        # 32-bit (1155-1156)
REG_TORQUE_LO = 1157        # 32-bit (1157-1158)
REG_ANGLE_HI = 1160         # 32-bit (1160-1161), raw degrees
REG_ANGLE_LO = 1162         # 32-bit (1162-1163), raw degrees

REG_STEP_ENABLE = 1135      # 16-bit, 1=enable step

# Job / sequence switching
REG_SWITCH_JOB = 463
REG_SWITCH_SEQ = 464

# Tool control
REG_START_STOP = 456        # 1=start, 0=stop
REG_REVERSE = 457           # 1=reverse
REG_CONFIRM = 458           # 1=confirm unlock
REG_CLEAR_COUNT = 459       # 1=clear count
REG_CLEAR_SEQ = 460         # 1=clear sequence
REG_TOOL_ENABLE = 461       # 1=enable, 0=disable
REG_REBOOT = 462            # 1=reboot controller

# Tightening results (4155-4164, 10 registers)
REG_RESULT_START = 4155
REG_TORQUE_RESULT = 4155    # 32-bit (4155-4156)
REG_TIGHTEN_TIME = 4158     # 16-bit, ms
REG_ANGLE_RESULT = 4159     # 32-bit (4159-4160)
REG_RESULT_CODE = 4164      # 16-bit

# Live status (4305-4346, 42 registers)
REG_STATUS_START = 4305

# RTC (4096-4101, 6 registers)
REG_RTC = 4096

# Barcode (4192-4241, 50 registers)
REG_BARCODE = 4192

# Serial number (4285-4286, 2 registers, 32-bit)
REG_SERIAL = 4285

# Special job number
JOB_MODBUS_WORK = 221

# Torque unit map: code -> (name, multiplier)
UNIT_MAP: dict[int, tuple[str, int]] = {
    0: ("kgf.m", 10000),
    1: ("N.m", 1000),
    2: ("kgf.cm", 100),
    3: ("lbf.in", 100),
    4: ("cN.m", 10),
}

RESULT_CODES: dict[int, str] = {4: "OK", 5: "OK-SEQ", 6: "OK-JOB", 7: "NG", 8: "NS"}
TOOL_MODES: dict[int, str] = {0: "锁附", 1: "退锁"}


# ============================================================
# TighteningResult dataclass — preserved for MockKilewsClient
# ============================================================

@dataclass
class TighteningResult:
    bolt_no: int
    torque_nm: float
    angle_deg: float
    controller_ok: bool
    raw_code: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "bolt_no": self.bolt_no,
            "torque_nm": self.torque_nm,
            "angle_deg": self.angle_deg,
            "controller_ok": self.controller_ok,
            "raw_code": self.raw_code,
        }


# ============================================================
# ModbusClient — raw-socket MODBUS TCP (FC 03 / 06 / 16)
# ============================================================

class ModbusClient:
    """Raw-socket MODBUS TCP client supporting read holding, write single,
    and write multiple registers.  Thread-safe transaction IDs."""

    def __init__(self, ip: str = "192.168.3.10", port: int = 502,
                 unit_id: int = 1, timeout: float = 2.0) -> None:
        self.ip = ip
        self.port = port
        self.unit_id = unit_id
        self.timeout = timeout
        self.connected = False
        self._lock = threading.Lock()
        self._tid = 0

    def connect(self, ip: str = "", port: int = 0, unit_id: int = 0) -> bool:
        """Test TCP reachability and set connection parameters."""
        if ip:
            self.ip = ip
        if port:
            self.port = port
        if unit_id:
            self.unit_id = unit_id
        try:
            s = socket.create_connection((self.ip, self.port), timeout=3.0)
            s.close()
            self.connected = True
            return True
        except OSError:
            self.connected = False
            return False

    def disconnect(self) -> None:
        self.connected = False

    # ---- read ----

    def read_registers(self, start: int, count: int, func: int = 3) -> list[int] | None:
        """Read holding registers (FC 03) or input registers (FC 04)."""
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
            return [struct.unpack(">H", data[i:i + 2])[0] for i in range(0, len(data), 2)]
        except OSError:
            self.connected = False
            return None

    # ---- write ----

    def write_register(self, addr: int, value: int) -> bool:
        """Write single holding register (FC 06)."""
        with self._lock:
            self._tid = (self._tid + 1) % 65536
            tid = self._tid
        pdu = struct.pack(">BHH", 6, addr, value & 0xFFFF)
        mbap = struct.pack(">HHHB", tid, 0, len(pdu) + 1, self.unit_id)
        try:
            sock = socket.create_connection((self.ip, self.port), timeout=self.timeout)
            try:
                sock.sendall(mbap + pdu)
                resp = sock.recv(12)
            finally:
                sock.close()
            return len(resp) == 12 and resp[7] == 6
        except OSError:
            return False

    def write_registers(self, start: int, values: list[int]) -> bool:
        """Write multiple holding registers (FC 16 / 0x10)."""
        count = len(values)
        with self._lock:
            self._tid = (self._tid + 1) % 65536
            tid = self._tid
        pdu = struct.pack(">BHHB", 0x10, start, count, count * 2)
        for v in values:
            pdu += struct.pack(">H", v & 0xFFFF)
        mbap = struct.pack(">HHHB", tid, 0, len(pdu) + 1, self.unit_id)
        try:
            sock = socket.create_connection((self.ip, self.port), timeout=self.timeout)
            try:
                sock.sendall(mbap + pdu)
                resp = sock.recv(12)
            finally:
                sock.close()
            return len(resp) == 12 and resp[7] == 0x10
        except OSError:
            return False


# ============================================================
# KilewsDevice — full KL-NTCS-M7 state management
# ============================================================

class KilewsDevice:
    """Full Kilews KL-NTCS-M7 device driver.

    Reads all relevant register blocks on refresh() and provides a
    proven write_all_flow() sequence for changing fastening parameters
    through the MODBUS-dedicated Job 221 work area.
    """

    def __init__(self, modbus: ModbusClient) -> None:
        self.modbus = modbus

        # --- live status (4305-4346) ---
        self.current_job = 0
        self.current_seq = 0
        self.current_step = 0
        self.current_count = 0
        self.tool_mode = 0
        self.enabled = False
        self.running = False

        # --- tightening results (4155-4164) ---
        self.torque_raw = 0
        self.angle_raw = 0
        self.result_code = 0
        self.tighten_time_ms = 0

        # --- RTC ---
        self.rtc: dict[str, int] = {"year": 0, "month": 0, "day": 0,
                                     "hour": 0, "min": 0, "sec": 0}

        # --- barcode ---
        self.barcode = ""

        # --- serial number ---
        self.serial_no = 0

        # --- torque unit (register 264) ---
        self.torque_unit_code = -1
        self.torque_unit_name = "?"
        self.torque_multiplier = 1000

        # --- fastening parameters (1144-1163) ---
        self.param_target_type = 0
        self.param_target_angle = 0
        self.param_target_torque = 0
        self.param_speed = 0
        self.param_torque_hi = 0
        self.param_torque_lo = 0
        self.param_angle_hi = 0
        self.param_angle_lo = 0

        # --- raw register caches ---
        self.reg_status: dict[int, int] = {}
        self.reg_result: dict[int, int] = {}
        self.reg_rtc: dict[int, int] = {}
        self.reg_params: dict[int, int] = {}
        self.last_update = ""

        # write lock prevents refresh interleaving with write_all_flow
        self._write_lock = threading.Lock()

    # ---- decoding ----

    def _decode_torque(self, raw: int) -> float:
        return raw / self.torque_multiplier

    def _decode_angle(self, raw: int) -> float:
        """Angle values are transmitted as-is (no ×10/÷10 conversion)."""
        return float(raw)

    @property
    def torque_nm(self) -> float:
        return self._decode_torque(self.torque_raw)

    @property
    def angle_deg(self) -> float:
        return self._decode_angle(self.angle_raw)

    # ---- read operations ----

    def read_unit(self) -> bool:
        """Read torque unit register (264)."""
        vals = self.modbus.read_registers(REG_TORQUE_UNIT, 1)
        if vals and len(vals) >= 1:
            self.torque_unit_code = vals[0]
            name, mult = UNIT_MAP.get(vals[0], ("?", 1000))
            self.torque_unit_name = name
            self.torque_multiplier = mult
            return True
        return False

    def read_parameters(self) -> bool:
        """Read fastening parameters from 1144-1163 (20 regs)."""
        vals = self.modbus.read_registers(REG_TARGET_TYPE, 20)
        if vals and len(vals) >= 20:
            self.reg_params = {REG_TARGET_TYPE + i: v
                               for i, v in enumerate(vals) if v != 0}
            self.param_target_type = vals[0]                              # 1144
            self.param_target_angle = (vals[1] << 16) | vals[2]          # 1145-1146
            self.param_target_torque = (vals[3] << 16) | vals[4]         # 1147-1148
            self.param_speed = vals[7]                                    # 1151
            self.param_torque_hi = (vals[11] << 16) | vals[12]            # 1155-1156
            self.param_torque_lo = (vals[13] << 16) | vals[14]           # 1157-1158
            self.param_angle_hi = (vals[16] << 16) | vals[17]            # 1160-1161
            self.param_angle_lo = (vals[18] << 16) | vals[19]            # 1162-1163
            return True
        return False

    def write_parameter(self, addr: int, value: int, is_32bit: bool = False) -> bool:
        """Write a single parameter, auto 16-bit vs 32-bit (two registers)."""
        if is_32bit:
            hi = (value >> 16) & 0xFFFF
            lo = value & 0xFFFF
            return self.modbus.write_registers(addr, [hi, lo])
        return self.modbus.write_register(addr, value)

    # ---- full refresh (on-demand, replaces polling thread) ----

    def refresh(self) -> None:
        """Read all register blocks.  Skip if write is in progress."""
        if not self.modbus.connected:
            return
        if self._write_lock.locked():
            return  # skip — write_all_flow in progress

        # 0. torque unit
        self.read_unit()

        # 1. RTC
        vals = self.modbus.read_registers(REG_RTC, 6)
        if vals and len(vals) >= 6:
            self.reg_rtc = {REG_RTC + i: v for i, v in enumerate(vals)}
            self.rtc = {"year": vals[0], "month": vals[1], "day": vals[2],
                        "hour": vals[3], "min": vals[4], "sec": vals[5]}

        # 2. tightening results
        vals = self.modbus.read_registers(REG_RESULT_START, 10)
        if vals and len(vals) >= 10:
            self.reg_result = {REG_RESULT_START + i: v
                               for i, v in enumerate(vals) if v != 0}
            self.torque_raw = (vals[0] << 16) | vals[1]
            self.angle_raw = (vals[4] << 16) | vals[5]
            self.tighten_time_ms = vals[3]
            self.result_code = vals[9]

        # 3. fastening parameters
        self.read_parameters()

        # 4. live status
        vals = self.modbus.read_registers(REG_STATUS_START, 42)
        if vals and len(vals) >= 42:
            self.reg_status = {REG_STATUS_START + i: v
                               for i, v in enumerate(vals) if v != 0}
            self.current_job = vals[0]
            self.current_seq = vals[1]
            self.current_step = vals[2]
            self.current_count = vals[3]
            self.tool_mode = vals[39]
            self.enabled = vals[40] == 1
            self.running = vals[41] == 1

        # 5. barcode
        vals = self.modbus.read_registers(REG_BARCODE, 50)
        if vals:
            chars: list[str] = []
            for v in vals:
                hi = (v >> 8) & 0xFF
                lo = v & 0xFF
                if hi:
                    chars.append(chr(hi) if 32 <= hi < 127 else '.')
                if lo:
                    chars.append(chr(lo) if 32 <= lo < 127 else '.')
            self.barcode = ''.join(chars).strip('\x00 .')

        # 6. serial number
        vals = self.modbus.read_registers(REG_SERIAL, 2)
        if vals and len(vals) >= 2:
            self.serial_no = (vals[0] << 16) | vals[1]

        self.last_update = time.strftime("%Y-%m-%d %H:%M:%S")

    # ---- serialization ----

    def status_dict(self) -> dict[str, Any]:
        """Lightweight status dict for HMI snapshot endpoint."""
        return {
            "connected": self.modbus.connected,
            "enabled": self.enabled,
            "running": self.running,
            "current_job": self.current_job,
            "current_seq": self.current_seq,
            "current_step": self.current_step,
            "current_count": self.current_count,
            "tool_mode": self.tool_mode,
            "tool_mode_label": TOOL_MODES.get(self.tool_mode, str(self.tool_mode)),
            "torque_raw": self.torque_raw,
            "torque_nm": round(self.torque_nm, 3),
            "angle_raw": self.angle_raw,
            "angle_deg": round(self.angle_deg, 1),
            "result_code": self.result_code,
            "result_label": RESULT_CODES.get(self.result_code,
                                              str(self.result_code)),
            "tighten_time_ms": self.tighten_time_ms,
            "torque_unit_name": self.torque_unit_name,
            "torque_multiplier": self.torque_multiplier,
            "last_update": self.last_update,
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
        }

    # ---- write-all flow (proven 13-step sequence) ----

    def _write_with_verify(self, addr: int, value: int, is_32bit: bool,
                           label: str) -> dict[str, Any]:
        """Write a register and verify by reading back.  Returns step report."""
        # read before
        before = None
        if not is_32bit:
            r = self.modbus.read_registers(addr, 1)
            if r and len(r) >= 1:
                before = r[0]
        else:
            r = self.modbus.read_registers(addr, 2)
            if r and len(r) >= 2:
                before = (r[0] << 16) | r[1]

        ok = self.write_parameter(addr, value, is_32bit)
        time.sleep(0.15)

        # read after
        after = None
        if not is_32bit:
            r = self.modbus.read_registers(addr, 1)
            if r and len(r) >= 1:
                after = r[0]
        else:
            r = self.modbus.read_registers(addr, 2)
            if r and len(r) >= 2:
                after = (r[0] << 16) | r[1]

        changed = (after == value) if after is not None else False
        item: dict[str, Any] = {
            "label": label, "addr": addr, "is32bit": is_32bit,
            "writeOk": ok, "before": before, "after": after,
            "expected": value, "changed": changed,
        }
        if not ok:
            item["note"] = "MODBUS write failed"
        elif not changed and after is not None:
            item["note"] = (f"写入成功但值未变: 期望{value} 实际{after}")
        return item

    def write_all_flow(
        self,
        torque_target: float,
        torque_min: float,
        torque_max: float,
        angle_target: float = 0.0,
        angle_min: float = 0.0,
        angle_max: float = 0.0,
        speed: int = 500,
        target_type: int = 2,
    ) -> dict[str, Any]:
        """Execute the proven 13-step parameter write sequence.

        Torque values are in N·m (converted to raw via multiplier).
        Angle values are in degrees (sent as-is).
        Speed is RPM.
        """
        with self._write_lock:
            # ensure unit is known
            self.read_unit()
            mult = self.torque_multiplier

            steps: list[dict[str, Any]] = []
            errors: list[str] = []

            def do_write(addr: int, val: int, is32: bool, label: str) -> None:
                item = self._write_with_verify(addr, val, is32, label)
                steps.append(item)
                if not item["writeOk"]:
                    errors.append(f"{label}[{addr}]=MODBUS_FAIL")

            # 1. enable step
            do_write(REG_STEP_ENABLE, 1, False, "开启步骤")

            # 2. write all parameters to 1144-1163 buffer
            do_write(REG_TARGET_TYPE, target_type, False, "目标类型")
            do_write(REG_TARGET_ANGLE, int(angle_target), True, "目标角度")
            do_write(REG_TARGET_TORQUE, int(torque_target * mult), True, "目标扭矩")
            do_write(REG_SPEED, speed, False, "转速")
            do_write(REG_TORQUE_HI, int(torque_max * mult), True, "扭矩上限")
            do_write(REG_TORQUE_LO, int(torque_min * mult), True, "扭矩下限")
            do_write(REG_ANGLE_HI, int(angle_max), True, "角度监控上限")
            do_write(REG_ANGLE_LO, int(angle_min), True, "角度监控下限")

            # 3. switch to MODBUS work area (loads EEPROM, may overwrite angle limits)
            do_write(REG_SWITCH_JOB, JOB_MODBUS_WORK, False, "切工作221")
            do_write(REG_SWITCH_SEQ, 1, False, "切工序1")

            # 4. re-write angle limits (overwritten by job switch)
            angle_hi_val = int(angle_max)
            angle_lo_val = int(angle_min)
            do_write(REG_ANGLE_HI, angle_hi_val, True, "角度监控上限(补写)")
            do_write(REG_ANGLE_LO, angle_lo_val, True, "角度监控下限(补写)")

            # final read-back
            self.read_parameters()

        return {
            "ok": len(errors) == 0,
            "written": len(steps),
            "steps": steps,
            "params_after": {
                "targetType": self.param_target_type,
                "targetAngle": self.param_target_angle,
                "targetTorque": self.param_target_torque,
                "speed": self.param_speed,
                "torqueHi": self.param_torque_hi,
                "torqueLo": self.param_torque_lo,
                "angleHi": self.param_angle_hi,
                "angleLo": self.param_angle_lo,
            },
            "multiplier": mult,
            "error": "; ".join(errors) if errors else None,
        }


# ============================================================
# MockKilewsClient — enhanced mock for offline / development
# ============================================================

class MockKilewsClient:
    """Mock Kilews client for development without hardware."""

    def __init__(self) -> None:
        self.connected = True
        self.enabled = False
        self.running = False
        self.current_job = 221
        self.current_seq = 1
        self.current_step = 1
        self.current_count = 0
        self.tool_mode = 0
        self.torque_raw = 0
        self.angle_raw = 0
        self.result_code = 0
        self.tighten_time_ms = 0
        self.torque_unit_code = 1
        self.torque_unit_name = "N.m"
        self.torque_multiplier = 1000
        self.last_update = ""

    def read_latest(self, bolt_no: int, torque_nm: float = 4.5,
                    angle_deg: float = 90.0) -> TighteningResult:
        return TighteningResult(
            bolt_no=bolt_no, torque_nm=torque_nm, angle_deg=angle_deg,
            controller_ok=True,
        )

    def status_dict(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "enabled": self.enabled,
            "running": self.running,
            "current_job": self.current_job,
            "current_seq": self.current_seq,
            "current_step": self.current_step,
            "current_count": self.current_count,
            "tool_mode": self.tool_mode,
            "tool_mode_label": "锁附",
            "torque_raw": self.torque_raw,
            "torque_nm": 0.0,
            "angle_raw": self.angle_raw,
            "angle_deg": 0.0,
            "result_code": self.result_code,
            "result_label": "",
            "tighten_time_ms": self.tighten_time_ms,
            "torque_unit_name": self.torque_unit_name,
            "torque_multiplier": self.torque_multiplier,
            "last_update": self.last_update,
            "params": {
                "targetType": 2,
                "targetAngle": 0,
                "targetTorque": 0,
                "speed": 0,
                "torqueHi": 0,
                "torqueLo": 0,
                "angleHi": 0,
                "angleLo": 0,
            },
        }

    def write_all_flow(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "written": 0,
            "steps": [],
            "params_after": {},
            "multiplier": 1000,
            "error": "Mock 模式下不支持写入控制器",
        }

    def refresh(self) -> None:
        pass
