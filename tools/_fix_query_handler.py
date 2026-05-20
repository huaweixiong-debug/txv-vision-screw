path = r"S:\expansion_valve_hmi\web\app.js"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

marker = 'queryRecordsBtn").addEventListener("click", async () => {'
idx = content.find(marker)
if idx < 0:
    print("NOT FOUND")
    exit(1)

start_pos = content.rfind("\n", 0, idx) + 1
end_marker = content.find("\n  $(\"#kilewsConnectBtn\")", start_pos)
print(f"Block: {start_pos} -> {end_marker}")

new_block = """  $("#queryRecordsBtn").addEventListener("click", async () => {
    try {
      const params = new URLSearchParams();
      const keyword = $("#recordKeyword").value.trim();
      const status = $("#recordStatus").value;
      const dateStart = $("#recordDateStart").value;
      const dateEnd = $("#recordDateEnd").value;
      if (keyword) params.set("keyword", keyword);
      if (status) params.set("status", status);
      if (dateStart) params.set("date_start", dateStart);
      if (dateEnd) params.set("date_end", dateEnd);
      params.set("limit", "200");
      const payload = await api(`/api/records?${params.toString()}`);
      renderRecordRows(payload.records);
      toast("查询完成");
    } catch (error) {
      toast(error.message);
    }
  });

"""

content = content[:start_pos] + new_block + content[end_marker:]
with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("DONE")
