# Kilews MODBUS 参数修复说明

这个文件用于把本次奇力速 KL-NTCS-M7 参数写入修复内容转交给 Claude Code 或其他协作者。

## 修复目标

修正奇力速控制器参数写入逻辑，使其符合当前现场要求：

- 拧紧方式：`扭矩控制 + 角度监控`
- 不是：`角度控制`
- 目标扭矩：`3 N·m`
- 扭矩下限：`2 N·m`
- 扭矩上限：`5 N·m`
- 角度下限：`700°`
- 角度上限：`12000°`

注意：

- `700` 和 `12000` 是现实世界角度，不是寄存器原始值。
- 控制器角度寄存器按 `0.1°` 为单位写入，所以实际 raw 值应为：
  - `700° -> 7000`
  - `12000° -> 120000`

## 修改的文件

### 1. `app/hardware/kilews.py`

改动位置主要在 `write_all_flow()` 和角度解码逻辑。

#### 已修改内容

- 新增常量：
  - `TARGET_TYPE_ANGLE = 1`
  - `TARGET_TYPE_TORQUE = 2`
  - `ANGLE_SCALE = 10`

- 明确角度寄存器单位：
  - `REG_TARGET_ANGLE`
  - `REG_ANGLE_HI`
  - `REG_ANGLE_LO`
  - 以上都按 `degrees × 10` 写 raw 值

- `write_all_flow()` 默认改为：
  - `target_type = TARGET_TYPE_TORQUE`

- `write_all_flow()` 内部统一先计算 raw 值，再写寄存器：
  - `target_angle_raw`
  - `target_torque_raw`
  - `torque_hi_raw`
  - `torque_lo_raw`
  - `angle_hi_raw`
  - `angle_lo_raw`

- 原来函数里还残留直接写工程量的旧逻辑，现在已经统一替换为 raw 值写入。

- Job 切换后对角度监控上下限的补写，也已经改成复用：
  - `angle_hi_raw`
  - `angle_lo_raw`

- `_decode_angle()` 改为按 `0.1°` 解码：
  - `raw / 10`

- 返回结果中新增 `raw_values` 字段，便于直接核对本次实际写入值。

#### 这次修复后的关键行为

- `1144` `REG_TARGET_TYPE` 写入 `2`
- `1147-1148` 目标扭矩写入 `3 × torque_multiplier`
- `1155-1156` 扭矩上限写入 `5 × torque_multiplier`
- `1157-1158` 扭矩下限写入 `2 × torque_multiplier`
- `1160-1161` 角度监控上限写入 `120000`
- `1162-1163` 角度监控下限写入 `7000`

### 2. `app/workflow.py`

改动位置在 `write_kilews_params()`。

#### 已修改内容

- 引入 `TARGET_TYPE_TORQUE`
- 调用 `self.kilews.write_all_flow(...)` 时，显式传入：
  - `target_type=TARGET_TYPE_TORQUE`

- 不再直接沿用产品通用配方里的 QC 角度范围 `70 / 120`

- 新增奇力速写参默认值：
  - `kilews_torque_target_nm = 3.0`
  - `kilews_torque_min_nm = 2.0`
  - `kilews_torque_max_nm = 5.0`
  - `kilews_angle_target_deg = 0.0`
  - `kilews_angle_min_deg = 700.0`
  - `kilews_angle_max_deg = 12000.0`

#### 当前实际意义

即使 `runtime/settings.json` 里的产品配方仍然显示：

- `angle_min_deg = 70`
- `angle_max_deg = 120`

这组通用配方值也不会再作为奇力速角度监控上下限默认写入控制器。

## 为什么要这样改

之前的问题有两类：

### 1. 模式风险

虽然寄存器定义里写了 `1=角度控制, 2=扭矩控制`，但需要明确保证当前流程总是写 `2`，否则控制器可能按错误模式工作。

### 2. 角度缩放风险

现场需求是：

- 下限 `700°`
- 上限 `12000°`

但代码路径里混有旧的产品配方角度值：

- `70°`
- `120°`

如果直接按旧配方或按未缩放值写寄存器，就会导致控制器拿到错误的角度监控范围。

## 公开文档确认情况

已确认的内容：

- 设备：`KL-NTCS-M7`
- 通讯：`Modbus TCP`
- 扭矩单位 multiplier 通过寄存器 `264` 获取
- 拧紧结果区包含：
  - `4155-4156` 扭矩结果
  - `4159-4160` 角度结果
  - `4164` 结果码

未完全公开确认的内容：

- 厂家公开资料没有完整开放所有“Read/Set Fields”字段表
- 因此这次没有整体重构寄存器地址映射，只在现有地址映射基础上修正了：
  - 模式
  - 工程量到 raw 的缩放
  - workflow 调用参数

## 建议 Claude Code 接手时注意

- 不要把 `runtime/settings.json` 里的通用配方角度 `70/120` 再接回奇力速写参路径
- 当前奇力速写参默认值是控制器专用值，不是产品 QC 判定值
- 如果后续要做成可配置，建议新增独立字段：
  - `kilews_torque_target_nm`
  - `kilews_torque_min_nm`
  - `kilews_torque_max_nm`
  - `kilews_angle_min_deg`
  - `kilews_angle_max_deg`
- 如果现场继续验证寄存器，优先看 `write_all_flow()` 返回里的 `raw_values`

## 已完成验证

- 已执行：

```bash
python -m py_compile S:\expansion_valve_hmi\app\hardware\kilews.py S:\expansion_valve_hmi\app\workflow.py
```

- 语法检查通过

## 一句话总结

这次修复的本质是：

`强制按扭矩控制写入 + 把 700°/12000° 按 0.1° 单位换算成 7000/120000 后写入角度监控寄存器。`
