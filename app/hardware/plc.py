from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


V_AREA_TABLE_VERSION = "v0.6"

# ---------------------------------------------------------------------------
# V-area address tables (preserved from existing system)
# ---------------------------------------------------------------------------

V_BITS = {
    # PLC inputs (PLC → PC)
    "VB10.0": "auto_mode",
    "VB10.1": "manual_mode",
    "VB10.2": "estop_ok",
    "VB10.3": "safety_ok",
    "VB10.4": "clamp_ok",
    "VB10.5": "home_ok",
    "VB10.6": "part_present",
    "VB10.7": "plc_comm_allow",
    "VB11.0": "plc_alarm",
    "VB11.1": "safety_alarm",
    "VB11.2": "clamp_alarm",
    "VB11.3": "part_missing_alarm",
    "VB11.4": "rework_selected",
    "VB11.5": "plc_tightening_forbidden",
    "VB11.6": "auto_cycle_running",
    # PC outputs (PC → PLC)
    "VB20.0": "pc_online",
    "VB20.1": "vision_ok",
    "VB20.2": "allow_preassemble",
    "VB20.3": "allow_tightening",
    "VB20.4": "bolt1_ok",
    "VB20.5": "bolt2_ok",
    "VB20.6": "part_ok",
    "VB20.7": "part_ng",
    "VB21.0": "qr_bound",
    "VB21.1": "qr_rule_ok",
    "VB21.2": "qr_duplicate",
    "VB21.3": "wait_qr_binding",
    "VB21.4": "data_saved",
    "VB21.5": "excel_export_ok",
    "VB21.6": "excel_export_failed",
    "VB21.7": "manual_qr_patch",
}

V_WORDS = {
    "VB0": "plc_heartbeat",
    "VB1": "pc_heartbeat",
    "VB70": "vision_result",
    "VB71": "qr_binding_result",
    "VB72": "tightening_permission",
    "VB73": "final_result",
    "VW30": "plc_alarm_code",
    "VW32": "product_model_code",
    "VW34": "recipe_no",
    "VW36": "pc_alarm_code",
    "VW40": "bolt_count",
    "VW42": "current_bolt_no",
    "VW44": "rework_choice_code",
    "VW46": "rework_count",
    "VD50": "bolt1_torque_x100",
    "VD54": "bolt1_angle_x100",
    "VD58": "bolt2_torque_x100",
    "VD62": "bolt2_angle_x100",
    "VD66": "torque_target_x100",
    "VD70": "torque_min_x100",
    "VD74": "torque_max_x100",
    "VD78": "angle_target_x100",
    "VD82": "angle_min_x100",
    "VD86": "angle_max_x100",
}

# ---------------------------------------------------------------------------
# M-bit address tables — automation handshake (Snap7)
# ---------------------------------------------------------------------------

# PC → PLC outputs
M_BITS_OUT: dict[str, tuple[int, int, str]] = {
    "M0.0": (0, 0, "product_ready"),     # O型圈合格
    "M0.1": (0, 1, "tightening_ok"),     # 拧紧合格
    "M0.2": (0, 2, "scan_complete"),     # 扫码合格
    "M0.7": (0, 7, "disable_scan"),      # 屏蔽扫码
    "M1.0": (1, 0, "tightening_ng"),     # 拧紧不合格
}

# PLC → PC inputs
M_BITS_IN: dict[str, tuple[int, int, str]] = {
    "M0.3": (0, 3, "manual_mode"),       # =1 手动模式, =0 自动模式
    "M0.4": (0, 4, "plc_estop"),         # 急停
    "M0.5": (0, 5, "plc_ready"),         # 1s脉冲/1s间隔
    "M0.6": (0, 6, "plc_reset"),         # PLC复位信号
    "M10.2": (10, 2, "plc_tightening_done"),
}


# ---------------------------------------------------------------------------
# PlcState dataclass
# ---------------------------------------------------------------------------

@dataclass
class PlcState:
    # V-area inputs (from PLC)
    auto_mode: bool = True
    manual_mode: bool = False
    estop_ok: bool = True
    safety_ok: bool = True
    clamp_ok: bool = True
    home_ok: bool = True
    part_present: bool = True
    plc_comm_allow: bool = True
    plc_alarm: bool = False
    safety_alarm: bool = False
    clamp_alarm: bool = False
    part_missing_alarm: bool = False
    rework_selected: bool = False
    plc_tightening_forbidden: bool = False
    auto_cycle_running: bool = False
    plc_alarm_code: int = 0
    rework_choice_code: int = 0
    heartbeat: int = 0
    last_seen: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # M-bit inputs (from PLC, automation handshake)
    m_manual_mode: bool = False          # M0.3: 1=手动, 0=自动
    m_estop: bool = False                # M0.4: 急停
    m_plc_ready: bool = False            # M0.5: 1s脉冲/1s间隔
    m_plc_reset: bool = False            # M0.6: PLC复位信号
    m_plc_tightening_done: bool = False  # M10.2

    # PC output M-bit state (sent to PLC)
    m_product_ready: bool = False
    m_tightening_ok: bool = False
    m_scan_complete: bool = False
    m_disable_scan: bool = False         # M0.7: 屏蔽扫码
    m_tightening_ng: bool = False        # M1.0: 拧紧不合格

    def is_ready_for_tightening(self) -> bool:
        return all(
            [
                self.auto_mode,
                self.estop_ok,
                self.safety_ok,
                self.clamp_ok,
                self.home_ok,
                self.part_present,
                self.plc_comm_allow,
                not self.plc_alarm,
                not self.safety_alarm,
                not self.clamp_alarm,
                not self.part_missing_alarm,
                not self.plc_tightening_forbidden,
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


# ---------------------------------------------------------------------------
# Mock PLC client (development without hardware)
# ---------------------------------------------------------------------------

class MockPLCClient:
    def __init__(self) -> None:
        self.state = PlcState()
        self.pc_outputs: dict[str, Any] = {}

    def connect(self) -> bool:
        # Simulate M-bit PLC inputs as ready by default
        self.state.m_manual_mode = False  # M0.3=0 = 自动模式
        self.state.m_plc_ready = True
        return True

    def disconnect(self) -> None:
        pass

    def read_state(self) -> PlcState:
        self.state.heartbeat = (self.state.heartbeat + 1) % 256
        self.state.last_seen = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return self.state

    def write_outputs(self, outputs: dict[str, Any]) -> None:
        self.pc_outputs.update(outputs)
        # Also update M-bit state from outputs
        if "m_product_ready" in outputs:
            self.state.m_product_ready = bool(outputs["m_product_ready"])
        if "m_tightening_ok" in outputs:
            self.state.m_tightening_ok = bool(outputs["m_tightening_ok"])
        if "m_scan_complete" in outputs:
            self.state.m_scan_complete = bool(outputs["m_scan_complete"])

    def update_mock_inputs(self, updates: dict[str, Any]) -> PlcState:
        for key, value in updates.items():
            if hasattr(self.state, key):
                setattr(self.state, key, value)
        self.state.last_seen = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return self.state


# ---------------------------------------------------------------------------
# Real S7-200 Smart PLC client via Snap7
# ---------------------------------------------------------------------------

class S7200SmartClient:
    """Real Siemens S7-200 Smart PLC communication via Snap7.

    Reads M-bit inputs and V-area state; writes M-bit outputs and V-area
    data values.
    """

    def __init__(
        self,
        ip: str,
        port: int = 102,
        rack: int = 0,
        slot: int = 1,
        timeout: float = 2.0,
        reconnect_interval: float = 5.0,
    ) -> None:
        self.ip = ip
        self.port = port
        self._rack = rack
        self._slot = slot
        self._timeout = timeout
        self._reconnect_interval = reconnect_interval
        self.pc_outputs: dict[str, Any] = {}
        self._snap7: Any = None  # Snap7Client from snap7_plc
        self._plc_ready_seen_at: float = 0.0  # timestamp of last M0.5=1

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Establish Snap7 connection to PLC."""
        try:
            from .snap7_plc import Snap7Client
            self._snap7 = Snap7Client(
                ip=self.ip,
                rack=self._rack,
                slot=self._slot,
                timeout=self._timeout,
                reconnect_interval=self._reconnect_interval,
            )
            return self._snap7.connect()
        except Exception as exc:
            print(f"[PLC] Snap7 init failed: {exc}")
            self._snap7 = None
            return False

    def disconnect(self) -> None:
        if self._snap7 is not None:
            self._snap7.disconnect()
            self._snap7 = None

    @property
    def connected(self) -> bool:
        return self._snap7 is not None and self._snap7.connected

    # ------------------------------------------------------------------
    # State read
    # ------------------------------------------------------------------

    def read_state(self) -> PlcState:
        """Read PLC inputs (M bits + V area) and return PlcState."""
        if self._snap7 is None or not self._snap7.connected:
            return PlcState(last_seen="PLC disconnected")

        try:
            # Read M-bit inputs
            m_inputs = self._snap7.read_all_m_inputs()

            # M0.5 pulse latch: PLC sends 1s high / 1s low
            raw_plc_ready = m_inputs.get("plc_ready", False)
            now = time.monotonic()
            if raw_plc_ready:
                self._plc_ready_seen_at = now
            plc_ready_latched = raw_plc_ready or (now - self._plc_ready_seen_at < 1.5)

            state = PlcState(
                auto_mode=not m_inputs.get("manual_mode", True),  # M0.3=0→自动
                estop_ok=not m_inputs.get("plc_estop", False),  # M0.4=1 means estop ACTIVE
                # V-area bits default to last known values (read on demand)
                m_manual_mode=m_inputs.get("manual_mode", True),
                m_estop=m_inputs.get("plc_estop", False),
                m_plc_ready=plc_ready_latched,  # M0.5 pulse latched
                m_plc_reset=m_inputs.get("plc_reset", False),
                m_plc_tightening_done=m_inputs.get("plc_tightening_done", False),
                last_seen=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            return state
        except Exception as exc:
            print(f"[PLC] read_state error: {exc}")
            return PlcState(last_seen=f"Error: {exc}")

    # ------------------------------------------------------------------
    # Output write
    # ------------------------------------------------------------------

    def write_outputs(self, outputs: dict[str, Any]) -> None:
        """Write PC outputs to PLC (M bits + V area)."""
        self.pc_outputs.update(outputs)

        if self._snap7 is None or not self._snap7.connected:
            return

        try:
            # Collect M-bit signals from outputs
            m_signals: dict[str, bool] = {}
            for label in ("product_ready", "tightening_ok", "scan_complete"):
                if label in outputs:
                    m_signals[label] = bool(outputs[label])

            if m_signals:
                self._snap7.write_all_m_outputs(m_signals)

            # Write V-area word values if present
            # Map from existing V_WORDS labels to their V addresses
            for v_addr, label in V_WORDS.items():
                if label in outputs:
                    val = int(outputs[label])
                    if v_addr.startswith("VB"):
                        # Byte value
                        offset = int(v_addr[2:])
                        self._snap7.write_v_bytes(offset, bytes([val & 0xFF]))
                    elif v_addr.startswith("VW"):
                        offset = int(v_addr[2:])
                        self._snap7.write_v_word(offset, val)
                    elif v_addr.startswith("VD"):
                        offset = int(v_addr[2:])
                        self._snap7.write_v_dword(offset, val)

        except Exception as exc:
            print(f"[PLC] write_outputs error: {exc}")

    # ------------------------------------------------------------------
    # Direct M-bit helpers (for automation thread)
    # ------------------------------------------------------------------

    def write_m_bit(self, byte_offset: int, bit_index: int, value: bool) -> None:
        """Write a single M bit directly."""
        if self._snap7 is not None and self._snap7.connected:
            self._snap7.write_m_bit(byte_offset, bit_index, value)

    def read_m_bit(self, byte_offset: int, bit_index: int) -> bool:
        """Read a single M bit directly."""
        if self._snap7 is not None and self._snap7.connected:
            return self._snap7.read_m_bit(byte_offset, bit_index)
        return False

    def update_mock_inputs(self, updates: dict[str, Any]) -> PlcState:
        """No-op for real PLC (can't write inputs). For compatibility only."""
        return self.read_state()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plc_client(settings: dict[str, Any]) -> MockPLCClient | S7200SmartClient:
    """Create the appropriate PLC client based on settings."""
    pcfg = settings.get("plc", {})
    if pcfg.get("enabled", False):
        client = S7200SmartClient(
            ip=pcfg.get("ip", "192.168.0.10"),
            port=int(pcfg.get("port", 102)),
            rack=int(pcfg.get("rack", 0)),
            slot=int(pcfg.get("slot", 1)),
            timeout=float(pcfg.get("timeout", 2.0)),
            reconnect_interval=float(pcfg.get("reconnect_interval_s", 5.0)),
        )
        if pcfg.get("auto_connect", False):
            client.connect()
        return client
    return MockPLCClient()
