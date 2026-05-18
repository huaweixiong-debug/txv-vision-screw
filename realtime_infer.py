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
        raise RuntimeError(f"Cannot open camera: {CAMERA_INDEX}")

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_FPS, 30)

    prev_time = time.time()

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Camera read failed, exiting.")
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
