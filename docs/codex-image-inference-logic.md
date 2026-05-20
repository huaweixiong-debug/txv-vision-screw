# 图像获取与推理逻辑

## 项目路径

```
S:\expansion_valve_hmi
```

## 涉及文件

| 文件 | 作用 |
|------|------|
| `app/hardware/camera.py` | 海康相机 MVS SDK，抓帧 + 调用推理 |
| `app/vision.py` | YOLO 模型加载、推理、去重、画框 |
| `app/workflow.py` | 初始化相机和推理，流程状态机调用推理 |

## 图像获取（camera.py）

### 相机配置

- 型号：海康 MV-CU060-10GM
- 分辨率：2048×1536（set in `_configure_gige`）
- 触发模式：连续自由采集（TriggerMode=OFF）
- 像素格式：Mono8
- 帧率：≤ 1 FPS（通过 `_frame_interval` 节流）

### 抓帧线程 `_grab_loop()`

1. 循环调用 `MV_CC_GetImageBuffer(timeout=1000ms)` 获取原始帧
2. 节流：`_frame_interval` 秒间隔（默认 1.0s）
3. 调用 `_process_frame()` 处理

### 帧处理 `_process_frame()`

流程：

1. **像素格式转换** → BGR（Mono8 → cv2.cvtColor GRAY2BGR 或其他格式转换）
2. 保存为 `self._latest_frame_bgr`（全分辨率 BGR 数组）
3. **YOLO 推理**（受 `_inference_interval` 节流，默认 1.0s）
   - 调用 `self._vision_inference.infer(frame_bgr)`
   - 得到 `{detections: [...], o_ring_count, o_ring_ok}`
4. **画框** → `self._vision_inference.draw_results(frame_bgr.copy(), infer_result)` → 得到带标注的 `display_img`
5. **缩放显示图**：如果宽度 > `_display_max_width`（1280px），等比缩放到 1280px 宽
6. JPEG 编码 `display_img` → `self._latest_jpeg`（质量 55）
7. HTTP 轮询 `/api/vision/latest-frame` 返回此 JPEG

## YOLO 推理（vision.py）

### VisionInference 初始化参数

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `confidence_threshold` | 0.15 | 全局置信度阈值 |
| `iou_threshold` | 0.3 | NMS IoU 阈值 |
| `dedup_overlap` | 0.7 | 同类去重 IoU 阈值 |
| `yolo_classes` | `['NG','O_Ring_L','O_Ring_S','QR','TXV']` | 5 类（模型原生） |
| `inference_size` | 416 | 推理输入尺寸 |
| `class_conf_map` | `{'TXV':0.15, 'QR':0.15}` | 单类置信度覆盖 |
| `roi_rect` | `None` 或 `(x,y,w,h)` | 显示区域过滤（可选，检测框必须完整落在 ROI 内） |

### infer(bgr_image) 流程

1. 中心裁切 → resize 到 `inference_size × inference_size`
2. `model.predict(input_img, conf=threshold, iou=iou, verbose=False)`
3. 遍历检测框：
   - `cls_id` → `yolo_classes[cls_id]` 得到类名
   - `_normalize_class_name()` 将 `O_Ring_L`/`O_Ring_S` → `O_Ring`
   - 映射坐标到全分辨率
   - 检查 `class_conf_map` 单独阈值
   - 检查 `roi_rect`：检测框必须完整在 ROI 内；部分进入或完全在外都直接丢弃
   - 添加到 detections 列表
4. **同类去重**：`_dedup_per_class(detections, 0.7)` — NG 最多 2，O_Ring 最多 2，QR/TXV 各 1
5. **跨类去重**：`_dedup_ng_vs_oring(detections, 0.001)` — NG 和 O_Ring 重叠时保留高置信度
6. **互斥规则**：
   - 2+ O_Ring → 移除 TXV
   - TXV 出现 → 移除 O_Ring
7. 返回 `{o_ring_count, o_ring_ok, detections, confidence}`

### draw_results() 画框

- 用 BGR 颜色画框（框宽 5px，字号 1.0，字粗 3px）
- 左上角叠加 O-Rings 状态文字

### _normalize_class_name()

映射表：`o_ring_l`→`O_Ring`, `o_ring_s`→`O_Ring`, `expansion_valve`→`TXV`, `qr`→`QR`, `ng`→`NG`

## 推理初始化（workflow.py `_init_camera`）

1. 连接 MVS 相机
2. 创建 `VisionInference` 实例
3. 如果有 `camera_roi` 设置 → `vision_infer.roi_rect = (x, y, w, h)`
4. `camera.set_inference(vision_infer, interval=1.0s, should_infer=state_predicate)`

## 自动拍照

`_auto_capture("vision_stable")` 在 `_on_stability_ok()` 中调用（检测到 2 个 O_Ring 时）。使用 `get_latest_raw_jpeg()` 保存原始画面（无 YOLO 框）。保存到 `data/images/{产品}/{日期}/`。

## 你的任务

需要改什么就改什么。不要只给建议。
