# Codex 任务：奇力速控制器参数写入失败

## 问题

从控制器**读取**数据没问题（`refresh()` 返回的 torque/angle/result 都正确）。但**写入参数**不生效——切换产品型号后，控制器的目标扭矩、上下限等不变化。

## 项目路径

```
S:\expansion_valve_hmi
```

## 关键文件

- `app/hardware/kilews.py` — `write_all_flow()` 方法（13 步写入序列），`ModbusClient` 类
- `app/workflow.py` — `write_kilews_params()` 调用 `write_all_flow()`
- `web/app.js` — 产品切换时调用 `POST /api/kilews/write-params`

## 当前写入流程

### 前端触发

产品切换 → `POST /api/kilews/write-params` 带 `{product_model: "E22H"}`

### 后端 (`write_kilews_params`)

1. 从 `settings.products` 找到产品配置
2. 调用 `self.kilews.write_all_flow(torque_target, torque_min, torque_max, angle_target, angle_min, angle_max, speed, target_type=2)`

### 写入序列 (`write_all_flow`, 约 487 行)

一共 13 步，每次写入后都验证：
1. REG_STEP_ENABLE(1135) = 1
2. REG_TARGET_TYPE(1144) = 2 (扭矩控制)
3. REG_TARGET_ANGLE(1145-1146) = angle * 10
4. REG_TARGET_TORQUE(1147-1148) = torque * multiplier
5. REG_SPEED(1151) = speed
6. REG_TORQUE_HI(1155-1156) = torque_max * multiplier
7. REG_TORQUE_LO(1157-1158) = torque_min * multiplier
8. REG_ANGLE_HI(1160-1161) = angle_max * 10
9. REG_ANGLE_LO(1162-1163) = angle_min * 10
10. REG_SWITCH_JOB(463) = 221 → 加载 EEPROM
11. REG_SWITCH_SEQ(464) = 1
12. REG_ANGLE_HI(1160-1161) = angle_max * 10 (再次写，Job 切换会覆盖)
13. REG_ANGLE_LO(1162-1163) = angle_min * 10 (再次写)

### MODBUS 通信 (`ModbusClient`)

- 写 16-bit：FC 06 (write single register)
- 写 32-bit：FC 16 (write multiple registers, 写 2 个寄存器)
- 读：FC 03 (read holding registers)
- 验证：写入后立刻回读，对比值是否匹配

## 已验证正常的

- MODBUS 读取：`refresh()` 能读到实时扭矩/角度/结果码
- 连接：TCP 192.168.0.105:502 能通
- multiplier：从寄存器 264 读取扭矩单位，N·m = 1000
- 前端：API 调用路径正确 `/api/kilews/write-params`

## 排查方向

1. **`write_with_verify` 返回值**：写入后回读是否匹配？如果匹配但控制器不生效，可能是 Job/SEQ 切换逻辑有问题
2. **寄存器地址**：确认 KL-NTCS-M7 的参数缓冲区地址 1144-1163 是否正确
3. **Job 切换时机**：当前先写参数 → 再切 Job 221 → 再补写角度限。顺序是否对？
4. **multiplier**：如果 `read_unit()` 失败，multiplier 默认 1000，值可能不对
5. **STEP_ENABLE**：写参数前是否需要先 DISABLE 再 ENABLE？
6. **_write_lock**：写入时是否有锁被持有导致跳过？
7. **`write_all_flow` 返回值**：检查日志中 `steps` 数组每个条目的 `writeOk` 是否为 true

## 调试方法

在远程机器查看 stdout.log：
```
type C:\Users\A\expansion_valve_hmi\stdout.log | findstr Kilews
```

或者直接调用 API 测试：
```
curl -X POST http://localhost:8010/api/kilews/write-params -H "Content-Type: application/json" -d "{\"product_model\":\"HB11\"}"
```

## 你的任务

找出为什么参数没有写入控制器，直接改代码修复。不要只给建议。
