# Codex 任务：确认/修改自动化完整流程

## 项目路径

```
S:\expansion_valve_hmi
```

## 你需要先读的文件

- `app/workflow.py` — 自动化状态机（_automation_tick 每 250ms 循环）
- `app/hardware/plc.py` — PLC M 位通讯（Snap7）
- `app/hardware/camera.py` — 相机抓帧 + YOLO 推理绑定
- `app/main.py` — HTTP API 路由
- `web/app.js` — 前端状态显示 + 步进条更新

## 需求：完整自动化流程（7 步）

### 流程步骤

| 步骤 | 状态 | 条件 | 动作 | M 位 |
|------|------|------|------|-------|
| 1 | `vision_wait_stable` | 连续 1.5s 检测到 2 个不重叠 O_Ring + 0 NG | → 步骤 2 |
| 2 | `vision_check_cover` | 连续 1.5s 检测到 TXV | → 步骤 3 |
| 3 | `plc_handshake` | PLC M0.5=1（就绪脉冲） | **M0.0=1**（产品就绪） |
| 4 | `tightening_wait` | — | 等待拧紧完成 |
| 5 | `tightening_eval` | 两颗螺丝结果出炉 | 判定 OK/NG | NG→M1.0=1 |
| 6 | `pending_scan` | — | 等扫码 | 可跳过 |
| 7 | `complete` | 扫码完成或跳过 | 记录保存 | M0.2=1 |

### M 位通讯表

**PC → PLC（输出）**：
| 地址 | 含义 | 何时置 1 |
|------|------|----------|
| M0.0 | 产品就绪 | 步骤 2→3 过渡时（TXV 检测通过）|
| M0.1 | 拧紧合格 | 两颗螺栓都 OK |
| M0.2 | 扫码完成 | 扫码绑定后 |
| M0.7 | 屏蔽扫码 | 用户选择跳过扫码时 |
| M1.0 | 拧紧不合格 | 任意螺栓 NG 时 |

**PLC → PC（输入）**：
| 地址 | 含义 |
|------|------|
| M0.3 | =1 手动模式，=0 自动模式 |
| M0.4 | =1 急停 |
| M0.5 | =1 就绪信号（1s 脉冲/1s 间隔，需 1.5s 锁存） |
| M0.6 | =1 PLC 复位 |
| M10.2 | =1 拧紧完成 |

### O 型圈判定规则

- 模型：`best.pt`，4 类：`NG, O_Ring, QR, TXV`
- 同类去重：每类最多 N 个（NG=2, O_Ring=2, QR=1, TXV=1），重叠 >70% 则保留置信度高的
- TXV 和 O_Ring 互斥：同帧不会同时出现
- O 型圈合格条件：`o_ring_count == 2 AND 无 NG`

### 拧紧逻辑

- Kilews MODBUS 寄存器 4155-4164 读取最新扭矩/角度/结果码
- result_code: 4=OK, 5=OK-SEQ, 6=OK-JOB, 7=NG, 8=NS
- 扭矩解码：raw × 0.001 = N·m
- 每次进入 `tightening_wait` 清空 bolt 状态
- 跳过旧结果：同一 result_code 不重复处理

### 前端步进条

7 个步骤：O型圈 → 膨胀阀 → 压紧 → 拧紧 → 判定 → 扫码 → 完成
- 当前步骤：黄色
- 已完成：绿色
- 未开始：灰色

### 页面关闭行为

关闭浏览器时 `beforeunload` 发送 `POST /api/shutdown`，断开所有连接。

## 你的任务

1. **确认**当前 `workflow.py` 的 `_automation_tick` 状态机流程是否正确
2. **确认** PLC M 位读写逻辑是否正确（`plc.py` + `snap7_plc.py`）
3. **确认** O 型圈 + TXV 检测去重逻辑（`vision.py`）
4. **确认** Kilews 拧紧数据读取和 bolt 状态管理
5. **确认** 前端步进条 7 步显示和颜色切换

如果发现问题直接改代码，不要只给建议。

## 你可以改的文件

- `app/workflow.py`
- `app/vision.py`
- `app/hardware/plc.py`
- `app/hardware/snap7_plc.py`
- `app/hardware/camera.py`
- `app/main.py`
- `web/app.js`
- `web/index.html`
- `web/styles.css`

## 不能改

- 通讯协议本身（Snap7/Modbus/MVS SDK 调用方式）
- 设置页
- 扫码枪
