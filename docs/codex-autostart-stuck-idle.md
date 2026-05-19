# Codex 任务：自动模式下 O 型圈已检测到但卡在「待开始」

## 问题

PLC M0.3=0（自动模式），YOLO 已检测到 2 个 O_Ring，但页面显示「待开始」（idle），步进条不动。

## 预期行为

PLC M0.3=0 时，HMI 应自动启动自动化（state: idle → vision_wait_stable），然后 O 型圈检测到后立即进入下一步。

## 项目路径

```
S:\expansion_valve_hmi
```

## 涉及文件

- `web/app.js` — `renderAutomation()` 函数，检测 M0.3 并自动调用 `/api/automation/start`
- `app/workflow.py` — `_automation_tick()` idle 状态处理，`start_cycle()` 方法
- `app/main.py` — `/api/automation/start` 端点，`/api/status` 端点

## 排查方向

### 1. 前端自动启动 (`renderAutomation`)

当前逻辑：检测 `plcAuto && !isAuto` → 调用 `/api/automation/start`

可能问题：
- `plcAuto` 是否 = true（M0.3=0）？
- `renderAutomation` 是否被调用（状态轮询间隔 1.5s）？
- `/api/automation/start` 是否返回成功？

### 2. 后端 idle 状态

`_automation_tick` 中 idle 处理：调用 `start_cycle()` → 设置 `state = "vision_wait_stable"`

可能问题：
- `automation_enabled` 是否为 True？
- `start_cycle` 是否被调用？
- 状态是否真的变成了 `vision_wait_stable`？

### 3. 调试方法

打开 `http://192.168.0.99:8010/api/automation/status` 查看：
- `enabled` 是否为 true
- `state` 当前值
- `active` 是否为 true

如果 `active` 是 false 且 `enabled` 是 false，说明自动化没启动。

## 你的任务

找出为什么 M0.3=0 时自动化不自启，直接改代码修复。
