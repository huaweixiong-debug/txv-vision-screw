# Claude Code 操作说明：二维码识别不要走纯 OCR，改走专用解码器

## 结论先说

这张图上的二维码 **不要按“OCR 大模型识别文本”来处理**。

原因：

1. 图里可见的是 **二维码矩阵本体**，不是清晰的人类可读文本
2. 这种场景本质上应该用 **二维码解码器**，不是普通 OCR
3. 已经验证过：
   - 全图直接 `cv2.QRCodeDetector().detectAndDecode(...)` 失败
   - 基于 YOLO 提供的 ROI 裁剪后，多种增强重试仍失败
   - 使用 `zxing-cpp` 在该 ROI 上做多版本增强重试，仍失败
4. 所以当前问题更像是：
   - 码太小
   - 有轻微模糊
   - 有透视/标签弯曲
   - 静区不足或局部对比度不够

## 当前已知 ROI

YOLO 检测到的二维码区域坐标（原图 3072 × 2048）：

- 左上角：`(1749, 1114)`
- 右下角：`(2284, 1457)`
- 宽高：`535 × 343`

## 正确策略

请不要继续把任务理解成“换一个 OCR 大模型就能读出来”。

请直接改成下面的策略：

### 1. 用 YOLO 的 `QR` 框做 ROI

1. 使用全分辨率原图，不要先缩放整图
2. 以 YOLO 框为中心，向四周扩边 `25% ~ 40%`
3. 裁剪出 ROI 后再做后续处理

### 2. 优先使用专用二维码解码器

解码顺序建议：

1. `zxing-cpp`
2. `cv2.QRCodeDetector().detectAndDecode(...)`
3. `cv2.QRCodeDetector().detectAndDecodeMulti(...)`
4. 如果你手头有 OpenCV WeChat QR 的模型文件，再试 `WeChatQRCode`

### 3. 对 ROI 做多版本增强

对 ROI 至少生成这些版本，并逐个交给解码器：

1. 灰度图
2. 直方图均衡 `equalizeHist`
3. CLAHE
4. 2x / 3x / 4x / 6x / 8x 放大
5. 放大后锐化
6. OTSU 二值化
7. 自适应阈值

### 4. 实时画面不要只看一帧

如果是相机实时识别，不要只拿单帧做结果判定。

请改成：

1. 当 YOLO 检到 `QR` 后，连续缓存最近 `5~10` 帧 ROI
2. 用 `Laplacian variance` 选择最清晰的一帧
3. 对多帧 ROI 都做增强和解码
4. 只要任意一帧解码成功，就输出结果
5. 连续多帧失败，才判为 `NO_QR_READ`

### 5. 不要硬编码推断这串码

理论期望值可能是：

`FTHB11H1405520260330A001000282`

但这只能作为 **校验参考**，不能在没有真实解码成功的情况下直接返回。

## Claude Code 需要直接创建的 Python 脚本

请在项目里创建一个独立脚本，例如：

- `qr_read_debug.py`

要求：

1. 输入图片路径
2. 使用给定 ROI 及扩边参数裁剪二维码区域
3. 生成多种增强版本
4. 依次用 `zxing-cpp` 和 OpenCV 解码
5. 打印：
   - 是否成功
   - 成功使用的解码器
   - 成功使用的增强版本
   - 最终字符串
6. 如果失败，把中间图保存到 `debug_qr/`

请使用下面这份代码：

```python
import os
import cv2
import zxingcpp
import numpy as np

IMAGE_PATH = r"C:\Users\Administrator\Downloads\20260517_161205_NEW-004_NOQR.jpg"
OUT_DIR = r".\debug_qr"

# YOLO 提供的全分辨率 ROI
X1, Y1, X2, Y2 = 1749, 1114, 2284, 1457
EXPAND_RATIO = 0.35


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def crop_roi(img, x1, y1, x2, y2, expand_ratio=0.35):
    w = x2 - x1
    h = y2 - y1
    pad_x = int(w * expand_ratio)
    pad_y = int(h * expand_ratio)

    nx1 = max(0, x1 - pad_x)
    ny1 = max(0, y1 - pad_y)
    nx2 = min(img.shape[1], x2 + pad_x)
    ny2 = min(img.shape[0], y2 + pad_y)

    return img[ny1:ny2, nx1:nx2].copy(), (nx1, ny1, nx2, ny2)


def build_variants(roi_bgr):
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    variants = []
    variants.append(("gray", gray))
    variants.append(("eq", cv2.equalizeHist(gray)))
    variants.append(("clahe", clahe.apply(gray)))

    for scale in [2, 3, 4, 6, 8]:
        up = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        variants.append((f"up_{scale}", up))
        variants.append((f"up_{scale}_eq", cv2.equalizeHist(up)))
        variants.append((f"up_{scale}_clahe", clahe.apply(up)))

        blur = cv2.GaussianBlur(up, (0, 0), 1.2)
        sharp = cv2.addWeighted(up, 1.8, blur, -0.8, 0)
        variants.append((f"up_{scale}_sharp", sharp))

        _, otsu = cv2.threshold(up, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append((f"up_{scale}_otsu", otsu))

        adap = cv2.adaptiveThreshold(
            up,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            3,
        )
        variants.append((f"up_{scale}_adap", adap))

    return variants


def try_zxing(img):
    try:
        results = zxingcpp.read_barcodes(img)
    except Exception:
        return None

    if not results:
        return None

    for item in results:
        text = getattr(item, "text", "")
        if text:
            return text
    return None


def try_opencv(img):
    detector = cv2.QRCodeDetector()

    try:
        data, points, _ = detector.detectAndDecode(img)
        if data:
            return data
    except Exception:
        pass

    try:
        ok, decoded_info, points, _ = detector.detectAndDecodeMulti(img)
        if ok:
            for text in decoded_info:
                if text:
                    return text
    except Exception:
        pass

    return None


def main():
    ensure_dir(OUT_DIR)

    img = cv2.imread(IMAGE_PATH)
    if img is None:
        raise RuntimeError(f"无法读取图片: {IMAGE_PATH}")

    roi, coords = crop_roi(img, X1, Y1, X2, Y2, EXPAND_RATIO)
    print("Expanded ROI coords:", coords)

    cv2.imwrite(os.path.join(OUT_DIR, "00_roi.png"), roi)

    variants = build_variants(roi)
    print("Variant count:", len(variants))

    for i, (name, variant) in enumerate(variants):
        save_path = os.path.join(OUT_DIR, f"{i:02d}_{name}.png")
        cv2.imwrite(save_path, variant)

        text = try_zxing(variant)
        if text:
            print("SUCCESS")
            print("decoder: zxing-cpp")
            print("variant:", name)
            print("text:", text)
            return

        text = try_opencv(variant)
        if text:
            print("SUCCESS")
            print("decoder: opencv")
            print("variant:", name)
            print("text:", text)
            return

    print("FAILED")
    print("No QR payload decoded from this image.")
    print("Please retry with a sharper frame or multi-frame strategy.")


if __name__ == "__main__":
    main()
```

## 依赖安装

如果缺少 `zxing-cpp`，请安装：

```bat
python -m pip install zxing-cpp
```

## 最重要的工程建议

如果你们的目标是产线稳定识别，请直接按下面的标准改采图，不要只靠后处理补救：

1. 让二维码在 ROI 中至少占到更大的像素面积
2. 提高快门或补光，减少运动模糊
3. 让二维码尽量接近平视，减少透视形变
4. 保证标签区域不要反光、不要弯曲
5. 每次读取时保留多帧，选最清晰的一帧解码

## 输出要求

Claude Code 完成后请回报：

1. 是否成功创建脚本
2. 是否成功安装 `zxing-cpp`
3. 哪个增强版本成功
4. 最终解码结果
5. 如果失败，`debug_qr/` 是否已生成
