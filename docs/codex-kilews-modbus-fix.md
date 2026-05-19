# Codex 任务：修正奇力速 MODBUS 通讯参数

## 设备

奇力速 KL-NTCS-M7 @ 192.168.0.105:502，MODBUS TCP

## 问题

发送给控制器的参数不对。拧紧方式是**扭矩控制 + 角度监控**（不是角度控制）。当前代码在 `app/hardware/kilews.py`。

## 项目路径

```
S:\expansion_valve_hmi
```

## 需要改的文件

- `app/hardware/kilews.py` — 寄存器定义 + `write_all_flow()` 方法
- `app/workflow.py` — `write_kilews_params()` 调用方，传递产品参数

## 当前寄存器定义（约 20-76 行）

| 地址 | 名称 | 位宽 | 含义 |
|------|------|------|------|
| 1144 | REG_TARGET_TYPE | 16-bit | 1=角度控制, 2=扭矩控制 |
| 1145-1146 | REG_TARGET_ANGLE | 32-bit | 目标角度，单位 0.1° |
| 1147-1148 | REG_TARGET_TORQUE | 32-bit | 目标扭矩，单位 N·m × multiplier |
| 1151 | REG_SPEED | 16-bit | 转速 RPM |
| 1155-1156 | REG_TORQUE_HI | 32-bit | 扭矩上限 |
| 1157-1158 | REG_TORQUE_LO | 32-bit | 扭矩下限 |
| 1160-1161 | REG_ANGLE_HI | 32-bit | 角度监控上限(0.1°) |
| 1162-1163 | REG_ANGLE_LO | 32-bit | 角度监控下限(0.1°) |
| 1135 | REG_STEP_ENABLE | 16-bit | 启用步骤 |
| 463 | REG_SWITCH_JOB | 16-bit | 切换作业(221) |
| 464 | REG_SWITCH_SEQ | 16-bit | 切换工序(1) |

## 当前写流程（`write_all_flow()`，约 487 行）

13 步写入序列：
1. 写 REG_STEP_ENABLE = 1
2. 写所有参数到 1144-1163 缓冲区（目标类型、角度、扭矩、转速、上下限）
3. 写 REG_SWITCH_JOB = 221 → 加载 EEPROM
4. 写 REG_SWITCH_SEQ = 1
5. 再次写角度监控上限/下限（因为 Job 切换会把它们覆盖）
6. 再次写角度监控上限/下限（重复确认）

## 拧紧结果读取（约 4155-4164）

| 地址 | 含义 |
|------|------|
| 4155-4156 | 扭矩结果 (32-bit, raw × multiplier = N·m) |
| 4158 | 拧紧时间 (ms) |
| 4159-4160 | 角度结果 (32-bit, raw × 0.1 = 度) |
| 4164 | 结果码 (4=OK,5=OK-SEQ,6=OK-JOB,7=NG,8=NS) |

## torque_multiplier 获取

从地址 264 读取扭矩单位码，通过 UNIT_MAP 查找对应的 multiplier（如 N·m = 1000）。

## 你的任务

1. 确认当前寄存器地址和参数缩放是否正确（对照 KL-NTCS-M7 MODBUS 手册）
2. 确认 `write_all_flow` 中 target_type=2（扭矩控制）是否设置正确
3. 角度监控上下限（1160-1163）的值和单位是否正确
4. 如果发现地址或缩放不对，直接修改代码

产品参数在 `app/config.py` DEFAULT_PRODUCT 和 `runtime/settings.json` 中定义。
