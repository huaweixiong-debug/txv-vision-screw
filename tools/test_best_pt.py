"""best.pt 加载测试 — 直接双击或 python test_best_pt.py"""
import os
import zipfile

MODEL = r"D:\Camera Screw Project\best.pt"

print("=" * 50)
print("文件:", MODEL)
print("存在:", os.path.exists(MODEL))
print("大小:", os.path.getsize(MODEL), "bytes")

# 检查是否是有效 ZIP
try:
    with zipfile.ZipFile(MODEL, "r") as z:
        names = z.namelist()
        print("ZIP条目:", len(names), "(正常)")
        for n in names[:5]:
            print("  ", n)
except Exception as e:
    print("ZIP检查失败:", e)
    print(">>> 文件已损坏，请重新导出 best.pt <<<")
    input("按回车退出...")
    exit(1)

# 尝试加载
print("\n加载模型中...")
try:
    from ultralytics import YOLO
    model = YOLO(MODEL)
    print("OK! 类别:", model.names)
except Exception as e:
    print("加载失败:", e)
    input("按回车退出...")
    exit(1)

print("\n=== 测试通过，best.pt 正常 ===")
input("按回车退出...")
