# 膨胀阀拧紧防错追溯 HMI

本项目是膨胀阀自动装配工位的软件 MVP：Windows 工控机本地运行，浏览器全屏作为 HMI，Python 后端负责流程、配置、追溯、日报导出和设备通讯抽象。

## 当前能力

- 生产主界面：O 型圈视觉状态、PLC 条件、两颗螺丝扭矩/角度、流程结束扫码绑定。
- 设置页面：YOLO 模型路径、相机 IP、PLC、奇力速 MODBUS TCP、网口扫码枪、配方参数。
- 数据追溯：SQLite 本地数据库，支持按条件查询。
- 日报导出：每日自动/手动导出 `.xlsx` 到 `D:\膨胀阀装配数据\YYYY-MM\YYYY-MM-DD.xlsx`。
- 图片采集：按 O 型圈、膨胀阀、螺栓、NG、其他分类保存。
- Roboflow 数据：只生成本地 YOLO datasets 结构与 `data.yaml`。
- 硬件抽象：PLC、奇力速、扫码枪均已预留真实接入接口，未接硬件时可模拟跑通流程。

## 启动

在本目录执行：

```powershell
.\start_hmi.ps1
```

如果 PowerShell 提示脚本未签名，可改用：

```powershell
.\start_hmi.bat
```

或临时绕过当前窗口的执行策略：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_hmi.ps1
```

或：

```powershell
python .\run.py --host 127.0.0.1 --port 8010
```

浏览器打开：

```text
http://127.0.0.1:8010
```

## 现场接入说明

- PLC：按 `软件方案/PLC-上位机V区通讯表-v0.5.xlsx` 做 V 区映射，心跳超时 1 秒。
- 奇力速：设置页面录入 MODBUS TCP IP、端口、寄存器地址。
- 扫码枪：当前按网口模式设计，默认 PC 作为 TCP Server 接收扫码内容。
- Roboflow：本软件只负责导出本地 datasets，标注在 Roboflow 中完成。
