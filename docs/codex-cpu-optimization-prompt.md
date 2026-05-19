# Codex 任务：优化 HMI CPU 占用

## 问题

Python 进程占 60%+ CPU，加上浏览器渲染，整机 100%。帧率已降到 1 FPS 仍不行。

## 项目路径

```
S:\expansion_valve_hmi
```

## 你必须先读这些文件

- `app/hardware/camera.py` — 海康相机 MVS SDK 封装，_grab_loop 抓帧 + _process_frame 处理
- `app/vision.py` — YOLO 推理 + 去重 + 画框
- `app/workflow.py` — 自动化流程 tick（250ms 循环）
- `web/app.js` — 前端 1000ms 轮询 /api/vision/latest-frame

## 当前配置

- 相机：海康 MV-CU060-10GM @ 192.168.0.101，Mono8，3072×2048
- 推理：best.pt (4 类 NG/O_Ring/QR/TXV)，480×480，间隔 1000ms
- 画面轮询：1000ms
- _grab_loop 已限制最高 1 FPS（sleep 0.5s）

## CPU 瓶颈分析

每帧 _process_frame 做了这些事：

1. **像素格式转换** — 6MB 原始帧 → OpenCV BGR（内存拷贝+转换）
2. **JPEG 编码 2 次** — 原始帧一次（_latest_raw_jpeg），推理叠加后又一次（_latest_jpeg）
3. **YOLO 推理** — CPU 上跑 480×480（每 1000ms 一次，受 _inference_interval 限制）
4. **画框** — cv2.rectangle + cv2.putText

问题不在帧率，在于**每帧都做全分辨率 JPEG 编码**。3072×2048 的 Mono8 → JPEG 编码在 CPU 上非常慢（~100-300ms）。

## 你要改的文件

只改下面 3 个，不要碰其他文件：
- `app/hardware/camera.py`
- `app/vision.py`
- `web/app.js`

绝对不要改通讯、PLC、扫码、设置页。

## 优化方向（按优先级）

### 1. 降低相机分辨率（最有效）

在 `_configure_gige()` 中，加上：

```python
self._cam.MV_CC_SetIntValue("Width", 2048)
self._cam.MV_CC_SetIntValue("Height", 1536)
```

或者在 MVS SDK 中用 `MV_CC_SetImageNodeNum` 设置 ROI/缩放。如果相机支持 binning（像素合并），用 binning 更快。

### 2. 减少 JPEG 编码次数

当前每帧编码 2 次。对于原始帧，不要每帧都编码——只在有推理结果时保存即可。或者降低 JPEG 质量从 80 到 50-60。

### 3. 用更小的推理尺寸

当前 480，试试 416 或 320。对检测精度影响小，对 CPU 影响大。

### 4. 推理只在需要时跑

_automation_tick 每 250ms 循环一次，每次都读 `get_latest_inference()`。推理只需要在 `vision_wait_stable` 和 `vision_check_cover` 状态跑，其他状态（plc_handshake, tightening_wait 等）不需要推理。

### 5. 前端只用一个 feed

当前有两个 `setInterval` 轮询 /api/vision/latest-frame——生产页一个（1000ms），训练数据页还有一个（200ms `startDatasetsFeed`）。停止非活跃 tab 的轮询。

### 6. 降低 JPEG 质量

在 `_process_frame` 中，`cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])` 改成 50。

## 验收标准

- Python CPU < 30%
- 画面延迟 < 1 秒
- 推理间隔 ≤ 1000ms
- 自动化流程不中断

## 不要做的事

- 不要改 PLC、Kilews、扫码枪代码
- 不要改设置页
- 不要换模型或改推理逻辑
- 不要引入新依赖
