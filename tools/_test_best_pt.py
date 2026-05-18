import sys
from ultralytics import YOLO
m = YOLO("D:/Camera Screw Project/best.pt")
print("OK, classes:", m.names)
