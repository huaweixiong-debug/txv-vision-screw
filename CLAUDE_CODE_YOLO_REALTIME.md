# Claude Code 操作说明：使用 `best.pt` 对实时画面做推理

## 目标

请在 Windows 环境下，使用已安装好的 `ultralytics` 与 `opencv-python`，加载下面这个模型，并对默认摄像头进行实时目标检测：

- 模型路径：`D:\Camera Screw Project\best.pt`
- 类别名称：`['NG', 'O_Ring_L', 'O_Ring_S', 'QR', 'TXV']`

已知环境信息：

- 已激活环境：`conda activate pytorch`
- Python 版本：`3.10.20`
- `ultralytics` 版本：`8.4.50`

## 你要做的事

请直接执行，不要讨论多种方案。

### 第 1 步：创建脚本

请在 `D:\Camera Screw Project` 目录下创建文件：

- `realtime_infer.py`

脚本要求如下：

1. 使用 `from ultralytics import YOLO`
2. 加载模型 `D:\Camera Screw Project\best.pt`
3. 使用 OpenCV 打开默认摄像头 `0`
4. 优先使用 `cv2.CAP_DSHOW` 以兼容 Windows
5. 对每一帧执行实时推理
6. 在窗口中显示：
   - 检测框
   - 类别名
   - 置信度
   - FPS
7. 启动时在终端打印 `model.names`
8. 按 `q` 或 `ESC` 退出
9. 默认参数：
   - `conf=0.25`
   - `iou=0.45`
   - `imgsz=640`
10. 代码尽量简洁稳定，可直接运行

请使用下面这份代码作为目标实现，除非你发现当前环境必须做兼容调整，否则不要改动整体结构：

```python
import time
import cv2
from ultralytics import YOLO

MODEL_PATH = r"D:\Camera Screw Project\best.pt"
CAMERA_INDEX = 0
CONF = 0.25
IOU = 0.45
IMGSZ = 640
WINDOW_NAME = "Screw Camera - YOLO Live"


def main():
    model = YOLO(MODEL_PATH)
    print("Model loaded:", MODEL_PATH)
    print("Classes:", model.names)

    cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开摄像头: {CAMERA_INDEX}")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 30)

    prev_time = time.time()

    while True:
        ok, frame = cap.read()
        if not ok:
            print("读取摄像头画面失败，退出。")
            break

        results = model.predict(
            source=frame,
            conf=CONF,
            iou=IOU,
            imgsz=IMGSZ,
            verbose=False
        )

        annotated = results[0].plot()

        now = time.time()
        fps = 1.0 / max(now - prev_time, 1e-6)
        prev_time = now

        cv2.putText(
            annotated,
            f"FPS: {fps:.1f}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 0),
            2
        )

        boxes = results[0].boxes
        if boxes is not None and len(boxes) > 0:
            y = 80
            for box in boxes[:5]:
                cls_id = int(box.cls[0].item())
                score = float(box.conf[0].item())
                cls_name = model.names[cls_id]
                color = (0, 0, 255) if cls_name == "NG" else (0, 255, 255)

                cv2.putText(
                    annotated,
                    f"{cls_name}: {score:.2f}",
                    (20, y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    color,
                    2
                )
                y += 30

        cv2.imshow(WINDOW_NAME, annotated)

        key = cv2.waitKey(1) & 0xFF
        if key == 27 or key == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
```

### 第 2 步：运行脚本

请在终端执行：

```bat
conda activate pytorch
cd /d "D:\Camera Screw Project"
python realtime_infer.py
```

### 第 3 步：如果启动失败，按下面顺序排查并修复

1. 如果摄像头打不开：
   - 将 `CAMERA_INDEX = 0` 改为 `1`
   - 如果还不行，再试 `2`

2. 如果画面卡顿明显：
   - 将 `IMGSZ = 640` 改为 `512`
   - 还卡的话改为 `416`

3. 如果窗口显示正常但没有检测框：
   - 检查镜头里是否有训练目标
   - 将 `CONF = 0.25` 改为 `0.15`

4. 如果显卡推理有异常：
   - 保持当前写法，不要强制指定 `device=0`
   - 先让 Ultralytics 自动选择设备

### 第 4 步：完成后回报结果

请告诉我以下内容：

1. 脚本是否已成功创建
2. 是否成功打开实时画面
3. `model.names` 实际打印结果
4. 推理是否正常
5. 如果有报错，贴出完整报错

## 补充要求

1. 不要修改 `best.pt`
2. 不要把任务改成图片推理或视频文件推理
3. 不要输出大段解释，直接创建脚本并运行
4. 如果只需要最小改动，请优先改 `CAMERA_INDEX`、`CONF`、`IMGSZ`

## 参考

- Ultralytics 官方文档说明：`model.predict(source=0)` 可直接用于 webcam 推理
- 官方 Python 用法文档也明确支持 `source=0`
