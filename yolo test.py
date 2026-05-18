from ultralytics import YOLO

# Load a model
model = YOLO(r"D:\ultralytics-main\best.pt")

# Predict on an image or folder
results = model(r"C:\Users\A\expansion_valve_hmi\data\images\NEW-004\2026-05-17")