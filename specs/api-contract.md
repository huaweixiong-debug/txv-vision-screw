# 拧紧枪控制面板 API 数据契约

> 此文件定义了前端和后端的接口协议。所有后端 API 的实现必须严格遵守此契约。
> **AI 助手注意**：此文件是最高优先级约束，**永远不要修改它**，除非用户明确指示。

---

## 通用约定
- 基础路径：`http://localhost:3000/api`
- 所有响应均为 JSON 格式：`Content-Type: application/json`
- 成功响应通常包含 `{ "success": true, ... }`
- 失败响应包含 `{ "success": false, "message": "错误描述" }`

---

## 1. 设备连接

### POST /api/connect
- **请求体**：
  ```json
  {
    "ip": "192.168.0.105",
    "port": 502
  }
成功响应：

json
{
  "success": true,
  "message": "连接成功"
}
失败响应：

json
{
  "success": false,
  "message": "连接失败: 网络不可达"
}
2. 获取设备状态
GET /api/status
请求体：无

成功响应：

json
{
  "connected": true,
  "enabled": true,
  "running": false,
  "currentJob": 201,
  "currentStep": 1,
  "resultCode": 4,
  "errorCode": 0
}
字段说明：

connected：Modbus 连接是否正常

enabled：起子是否已启用（对应你前端 JS 中的 status.enabled）

running：是否正在运转（对应 status.running）

currentJob：当前工作号（如 JOB 201）

currentStep：当前步骤

resultCode：最近一次拧紧结果码

4：OK（单颗螺丝合格）

5：OK-SEQ（工序顺序完成）

6：OK-JOB（整个工作完成）

7：NG（扭矩不合格）

8：NS（NG 并已停止）

errorCode：当前故障码（0 表示无故障）

3. 启动拧紧
POST /api/start
请求体：无

成功响应：

json
{
  "success": true,
  "message": "拧紧完成，结果 OK",
  "resultCode": 4,
  "errorCode": 0
}
失败响应：

json
{
  "success": false,
  "message": "拧紧未通过: NG",
  "resultCode": 7,
  "errorCode": 15
}
4. 设置拧紧参数并切换智能工作
POST /api/setparams
请求体：

json
{
  "targetNm": 2.0,
  "highNm": 2.5,
  "lowNm": 1.8,
  "speedRpm": 1000,
  "thresholdNm": 0.5
}
成功响应：

json
{
  "success": true,
  "message": "参数已写入并激活 JOB 201"
}
5. 复位设备
POST /api/reset
请求体：无

成功响应：

json
{
  "success": true,
  "message": "复位成功，报警已清除"
}
6. 紧急停止
POST /api/stop
请求体：无

成功响应：

json
{
  "success": true,
  "message": "停止指令已发送"
}
text
