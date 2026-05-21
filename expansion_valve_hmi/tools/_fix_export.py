path = r"S:\expansion_valve_hmi\web\app.js"
with open(path, "rb") as f:
    data = f.read()

# Match by unique key
old_key = b'exportDailyBtn").addEventListener("click", async () => {'
idx = data.find(old_key)
if idx < 0:
    print("NOT FOUND")
    exit(1)

# Find end: "$("#captureBtn")" after this idx
end = data.find(b'$("#captureBtn")', idx)

new_block = b'''exportDailyBtn").addEventListener("click", async () => {
    await runAction(async () => {
      const body = {};
      const ds = $("#recordDateStart").value;
      const de = $("#recordDateEnd").value;
      const kw = $("#recordKeyword").value.trim();
      const st = $("#recordStatus").value;
      if (ds) body.date_start = ds;
      if (de) body.date_end = de;
      if (kw) body.keyword = kw;
      if (st) body.status = st;
      const payload = await api("/api/export/daily", body);
      $("#exportPath").textContent = `\xe5\xae\xb8\xe6\x8f\x92\xee\x87\xb1\xe9\x8d\x91\xe7\x8c\xb4\xe7\xb4\xb0${payload.export_path}`;
    }, "\\u65e5\\u62a5 Excel \\u5df2\\u5bfc\\u51fa");
  });

'''

data = data[:idx] + new_block + data[end:]
with open(path, "wb") as f:
    f.write(data)
print("DONE")
