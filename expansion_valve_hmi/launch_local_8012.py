import pathlib, subprocess, sys
root = pathlib.Path(r"S:\expansion_valve_hmi")
log = open(root / "preview_local_8012.log", "ab")
subprocess.Popen(
    [sys.executable, "run.py", "--host", "127.0.0.1", "--port", "8012"],
    cwd=str(root),
    stdout=log,
    stderr=subprocess.STDOUT,
    creationflags=subprocess.CREATE_NO_WINDOW,
)
