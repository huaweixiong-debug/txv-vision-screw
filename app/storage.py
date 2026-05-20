from __future__ import annotations

import html
import sqlite3
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import resolve_path


SOFTWARE_VERSION = "0.1.0"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_text() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


class ProductionStorage:
    def __init__(self, database_path: str) -> None:
        self.database_path = resolve_path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS serial_counters (
                    serial_date TEXT NOT NULL,
                    product_model TEXT NOT NULL,
                    station_id TEXT NOT NULL,
                    last_no INTEGER NOT NULL,
                    PRIMARY KEY (serial_date, product_model, station_id)
                );

                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    internal_serial TEXT NOT NULL UNIQUE,
                    qr_code TEXT,
                    product_model TEXT NOT NULL,
                    recipe_no INTEGER NOT NULL,
                    operator TEXT,
                    shift TEXT,
                    status TEXT NOT NULL,
                    vision_status TEXT,
                    o_ring_count INTEGER,
                    bolt_count INTEGER NOT NULL,
                    bolt1_torque REAL,
                    bolt1_angle REAL,
                    bolt1_result TEXT,
                    bolt2_torque REAL,
                    bolt2_angle REAL,
                    bolt2_result TEXT,
                    final_result TEXT,
                    rework_choice TEXT,
                    rework_count INTEGER NOT NULL DEFAULT 0,
                    qr_bind_status TEXT,
                    alarm_code TEXT,
                    alarm_message TEXT,
                    image_path TEXT,
                    model_version TEXT,
                    software_version TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    scanned_at TEXT,
                    stability_duration_ms INTEGER,
                    coverage_confidence REAL,
                    expansion_valve_detected INTEGER,
                    plc_product_ready_sent INTEGER,
                    plc_tightening_ok_sent INTEGER,
                    plc_scan_complete_sent INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_records_created_at ON records(created_at);
                CREATE INDEX IF NOT EXISTS idx_records_qr_code ON records(qr_code);
                CREATE INDEX IF NOT EXISTS idx_records_status ON records(status);
                CREATE INDEX IF NOT EXISTS idx_records_product ON records(product_model);

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id INTEGER,
                    event_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(record_id) REFERENCES records(id)
                );
                """
            )
            # Safe schema migration — add columns that may not exist yet
            self._migrate_schema(conn)

    @staticmethod
    def _migrate_schema(conn: sqlite3.Connection) -> None:
        """Add new columns if they don't exist (safe for existing databases)."""
        migrations = [
            "ALTER TABLE records ADD COLUMN stability_duration_ms INTEGER",
            "ALTER TABLE records ADD COLUMN coverage_confidence REAL",
            "ALTER TABLE records ADD COLUMN expansion_valve_detected INTEGER",
            "ALTER TABLE records ADD COLUMN plc_product_ready_sent INTEGER",
            "ALTER TABLE records ADD COLUMN plc_tightening_ok_sent INTEGER",
            "ALTER TABLE records ADD COLUMN plc_scan_complete_sent INTEGER",
        ]
        for sql in migrations:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # column already exists

    def next_serial(self, product_model: str, station_id: str) -> str:
        now = datetime.now()
        serial_date = now.strftime("%Y%m%d")
        with self._lock, self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT last_no FROM serial_counters
                WHERE serial_date = ? AND product_model = ? AND station_id = ?
                """,
                (serial_date, product_model, station_id),
            ).fetchone()
            next_no = 1 if row is None else int(row["last_no"]) + 1
            conn.execute(
                """
                INSERT INTO serial_counters(serial_date, product_model, station_id, last_no)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(serial_date, product_model, station_id)
                DO UPDATE SET last_no = excluded.last_no
                """,
                (serial_date, product_model, station_id, next_no),
            )
            serial = f"{product_model}-{serial_date}-{station_id}-{next_no:04d}"
            conn.commit()
            return serial

    def create_record(
        self,
        *,
        product_model: str,
        recipe_no: int,
        station_id: str,
        operator: str,
        shift: str,
        bolt_count: int,
        model_version: str,
    ) -> dict[str, Any]:
        internal_serial = f"TMP-{product_model}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        stamp = now_text()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO records(
                    internal_serial, product_model, recipe_no, operator, shift, status,
                    vision_status, o_ring_count, bolt_count, qr_bind_status,
                    model_version, software_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    internal_serial,
                    product_model,
                    recipe_no,
                    operator,
                    shift,
                    "RUNNING",
                    "WAIT",
                    0,
                    bolt_count,
                    "WAIT",
                    model_version,
                    SOFTWARE_VERSION,
                    stamp,
                    stamp,
                ),
            )
            record_id = int(cur.lastrowid)
        self.add_event(record_id, "record.created", f"创建生产记录 {internal_serial}")
        record = self.get_record(record_id)
        assert record is not None
        return record

    def assign_serial(self, record_id: int, product_model: str, station_id: str, operator: str = "") -> str:
        """Assign the next daily counter-based serial to a record (only for OK parts)."""
        serial = self.next_serial(product_model, station_id)
        stamp = now_text()
        with self.connect() as conn:
            if operator:
                conn.execute(
                    "UPDATE records SET internal_serial = ?, created_at = ?, product_model = ?, operator = ? WHERE id = ?",
                    (serial, stamp, product_model, operator, record_id),
                )
            else:
                conn.execute(
                    "UPDATE records SET internal_serial = ?, created_at = ? WHERE id = ?",
                    (serial, stamp, record_id),
                )
        self.add_event(record_id, "record.serial_assigned", f"分配序列号 {serial}")
        return serial

    def get_record(self, record_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
            return row_to_dict(row)

    def update_record(self, record_id: int, **fields: Any) -> dict[str, Any]:
        if not fields:
            record = self.get_record(record_id)
            assert record is not None
            return record
        allowed = {
            "qr_code",
            "status",
            "vision_status",
            "o_ring_count",
            "bolt1_torque",
            "bolt1_angle",
            "bolt1_result",
            "bolt2_torque",
            "bolt2_angle",
            "bolt2_result",
            "final_result",
            "rework_choice",
            "rework_count",
            "qr_bind_status",
            "alarm_code",
            "alarm_message",
            "image_path",
            "completed_at",
            "scanned_at",
            "stability_duration_ms",
            "coverage_confidence",
            "expansion_valve_detected",
            "plc_product_ready_sent",
            "plc_tightening_ok_sent",
            "plc_scan_complete_sent",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unsupported record fields: {sorted(unknown)}")
        fields["updated_at"] = now_text()
        assignments = ", ".join(f"{name} = ?" for name in fields)
        values = list(fields.values())
        values.append(record_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE records SET {assignments} WHERE id = ?", values)
        record = self.get_record(record_id)
        assert record is not None
        return record

    def add_event(self, record_id: int | None, event_type: str, message: str, payload: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO events(record_id, event_type, message, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (record_id, event_type, message, payload, now_text()),
            )

    def qr_exists(self, qr_code: str, exclude_record_id: int | None = None) -> bool:
        with self.connect() as conn:
            if exclude_record_id is None:
                row = conn.execute(
                    "SELECT id FROM records WHERE qr_code = ? LIMIT 1",
                    (qr_code,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT id FROM records WHERE qr_code = ? AND id <> ? LIMIT 1",
                    (qr_code, exclude_record_id),
                ).fetchone()
        return row is not None

    def bind_qr(self, record_id: int, qr_code: str, reject_duplicate: bool = True) -> dict[str, Any]:
        record = self.get_record(record_id)
        if record is None:
            raise ValueError("当前生产记录不存在")
        if reject_duplicate and self.qr_exists(qr_code, exclude_record_id=record_id):
            self.update_record(record_id, qr_bind_status="DUPLICATE", alarm_code="QR_DUP", alarm_message="二维码重复")
            raise ValueError("二维码重复，已绑定到其他记录")
        updated = self.update_record(
            record_id,
            qr_code=qr_code,
            qr_bind_status="BOUND",
            status="COMPLETED",
            scanned_at=now_text(),
            alarm_code="",
            alarm_message="",
        )
        self.add_event(record_id, "qr.bound", f"二维码绑定完成：{qr_code}")
        return updated

    def list_records(
        self,
        *,
        limit: int = 100,
        keyword: str = "",
        status: str = "",
        product_model: str = "",
        date: str = "",
        date_start: str = "",
        date_end: str = "",
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        where: list[str] = []
        params: list[Any] = []
        if keyword:
            like = f"%{keyword}%"
            where.append("(internal_serial LIKE ? OR qr_code LIKE ? OR operator LIKE ?)")
            params.extend([like, like, like])
        if date:
            where.append("substr(created_at, 1, 10) = ?")
            params.append(date)
        if date_start:
            where.append("created_at >= ?")
            params.append(date_start)
        if date_end:
            where.append("created_at <= ?")
            params.append(date_end + " 23:59:59")
        if status:
            where.append("status = ?")
            params.append(status)
        if product_model:
            where.append("product_model = ?")
            params.append(product_model)
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM records
                {where_sql}
                ORDER BY id DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [row_to_dict(row) for row in rows if row is not None]

    def records_for_date(self, date_text: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM records
                WHERE substr(created_at, 1, 10) = ?
                ORDER BY id ASC
                """,
                (date_text,),
            ).fetchall()
        return [row_to_dict(row) for row in rows if row is not None]

    def export_daily(self, export_root: str, date_text_value: str | None = None) -> Path:
        export_date = date_text_value or today_text()
        rows = self.records_for_date(export_date)
        root = Path(export_root)
        month_dir = root / export_date[:7]
        month_dir.mkdir(parents=True, exist_ok=True)
        output_path = month_dir / f"{export_date}.xlsx"
        headers = [
            "序号",
            "状态",
            "生产日期",
            "生产时间",
            "内部序列号",
            "产品二维码",
            "产品型号",
            "配方号",
            "操作员",
            "班次",
            "O型圈识别结果",
            "O型圈数量",
            "螺丝1扭矩Nm",
            "螺丝1角度°",
            "螺丝1结果",
            "螺丝2扭矩Nm",
            "螺丝2角度°",
            "螺丝2结果",
            "整件结果",
            "返修选择",
            "返修次数",
            "二维码绑定状态",
            "报警代码",
            "报警信息",
            "图片路径",
            "稳定性检测ms",
            "覆盖率置信度",
            "膨胀阀检测",
            "PLC就绪信号",
            "PLC拧紧信号",
            "PLC扫码信号",
            "软件版本",
            "模型版本",
        ]
        matrix: list[list[Any]] = [headers]
        for index, row in enumerate(rows, start=1):
            created = row.get("created_at") or ""
            matrix.append(
                [
                    index,
                    row.get("status") or "",
                    created[:10],
                    created[11:19],
                    row.get("internal_serial") or "",
                    row.get("qr_code") or "",
                    row.get("product_model") or "",
                    row.get("recipe_no") or "",
                    row.get("operator") or "",
                    row.get("shift") or "",
                    row.get("vision_status") or "",
                    row.get("o_ring_count") or 0,
                    row.get("bolt1_torque") if row.get("bolt1_torque") is not None else "",
                    row.get("bolt1_angle") if row.get("bolt1_angle") is not None else "",
                    row.get("bolt1_result") or "",
                    row.get("bolt2_torque") if row.get("bolt2_torque") is not None else "",
                    row.get("bolt2_angle") if row.get("bolt2_angle") is not None else "",
                    row.get("bolt2_result") or "",
                    row.get("final_result") or "",
                    row.get("rework_choice") or "",
                    row.get("rework_count") or 0,
                    row.get("qr_bind_status") or "",
                    row.get("alarm_code") or "",
                    row.get("alarm_message") or "",
                    row.get("image_path") or "",
                    row.get("stability_duration_ms") if row.get("stability_duration_ms") is not None else "",
                    row.get("coverage_confidence") if row.get("coverage_confidence") is not None else "",
                    row.get("expansion_valve_detected") if row.get("expansion_valve_detected") is not None else "",
                    row.get("plc_product_ready_sent") if row.get("plc_product_ready_sent") is not None else "",
                    row.get("plc_tightening_ok_sent") if row.get("plc_tightening_ok_sent") is not None else "",
                    row.get("plc_scan_complete_sent") if row.get("plc_scan_complete_sent") is not None else "",
                    row.get("software_version") or "",
                    row.get("model_version") or "",
                ]
            )
        write_xlsx(output_path, matrix)
        return output_path


def excel_col(index: int) -> str:
    index += 1
    result = ""
    while index:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def xml_text(value: Any) -> str:
    return html.escape(str(value), quote=True)


def sheet_xml(matrix: list[list[Any]]) -> str:
    rows_xml: list[str] = []
    for r_index, row in enumerate(matrix, start=1):
        cells: list[str] = []
        for c_index, value in enumerate(row):
            cell_ref = f"{excel_col(c_index)}{r_index}"
            if value is None:
                cells.append(f'<c r="{cell_ref}"/>')
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{cell_ref}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{cell_ref}" t="inlineStr"><is><t>{xml_text(value)}</t></is></c>')
        rows_xml.append(f'<row r="{r_index}">{"".join(cells)}</row>')
    max_cols = max((len(row) for row in matrix), default=1)
    max_rows = max(len(matrix), 1)
    dimension = f"A1:{excel_col(max_cols - 1)}{max_rows}"
    cols_xml = "".join(f'<col min="{i}" max="{i}" width="16" customWidth="1"/>' for i in range(1, max_cols + 1))
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="{dimension}"/>
  <sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
  <cols>{cols_xml}</cols>
  <sheetData>{"".join(rows_xml)}</sheetData>
</worksheet>"""


def write_xlsx(output_path: Path, matrix: list[list[Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>""",
        )
        zf.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        )
        zf.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="日报" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>""",
        )
        zf.writestr(
            "xl/styles.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1"><font><sz val="11"/><name val="Microsoft YaHei"/></font></fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border/></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs>
</styleSheet>""",
        )
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml(matrix))
