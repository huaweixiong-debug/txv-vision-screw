
#任务：初始化拧紧枪项目并实现 Modbus 控制后端

请严格按照以下步骤执行，每完成一步向我确认后再进行下一步。

## 步骤一：初始化项目
1. 在项目根目录创建 package.json，包含以下依赖：
   - express (最新稳定版)
   - modbus-serial (最新稳定版)
   - express-validator (最新稳定版)
2. 运行 npm install 安装依赖

## 步骤二：实现 modbusService.js
创建 Modbus 通信模块，包含：
- connect(ip, port)：连接设备，超时 5 秒
- disconnect()：断开连接
- readHoldingRegister(addr)：读取保持寄存器
- readInputRegister(addr)：读取输入寄存器
- writeCoil(addr, value)：写线圈
- readFloat32(startAddr)：读取 32 位浮点数（处理字节序）
- 自动重连机制（最多 3 次，指数退避）

## 步骤三：实现 server.js
创建 Express 服务器，实现以下路由：
- 严格遵循 /specs/api-contract.md 中定义的接口格式
- 所有路由必须以 /api 开头
- 端口 3000
- 托管 public/ 目录下的静态文件

## 要求
1. 禁止兜圈子：直接生成代码，不要讨论多种方案
2. 字段名必须与 specs/api-contract.md 完全一致（如 resultCode、errorCode）
3. 所有 Modbus 操作必须有错误处理和日志
4. 完成后在代码末尾附上自我审查区
这样，Codex 会按照你设定好的规则（AGENTS.md）和数据契约（specs/api-contract.md），一步步生成你需要的 package.json、modbusService.js 和 server.js。

需要我帮你把 AGENTS.md 的内容也微调一下，加上对这几个文件的说明吗？

好
我们被要求微调AGENTS.md，加入对package.json和server.js等文件的说明。需要输出修改后的AGENTS.md内容。注意保持原有结构，增加对尚未存在的代码文件的说明，允许AI生成它们。同时要强调遵循项目结构和规则。生成回答。

好的，以下是微调后的 AGENTS.md，增加了对 package.json、server.js 等代码文件的说明，并指明了 AI 可以生成和修改的范围。

markdown
# 项目：智能拧紧枪 Modbus TCP 工控面板

## 1. 角色与目标
你是一名**资深的工业自动化后端工程师**，负责为本项目开发健壮、安全、可维护的 Node.js 后端服务。
**最终目标**：生成与前端完全匹配的 API 服务，实现对拧紧枪控制器的精确控制。

## 2. 技术栈（强制）
- 运行时：Node.js 18+
- 框架：Express.js 4.x
- Modbus 库：`modbus-serial` 最新稳定版
- 数据校验：`express-validator` 7.x
- 包管理：npm
- 模块风格：CommonJS（`require`）

## 3. 项目结构（强制）
/
├── AGENTS.md # 本文件（AI 行为准则，AI 不可修改）
├── specs/
│ └── api-contract.md # 数据契约（AI 不可修改）
├── package.json # 项目依赖（AI 可按需生成/更新）
├── server.js # Express 主入口（AI 可生成/修改）
├── modbusService.js # Modbus 通信单例（AI 可生成/修改）
└── public/
└── index.html # 前端面板（AI 不可修改）

text
- **不可变文件**：`AGENTS.md`、`specs/` 目录、`public/` 目录下的文件。你永远不应该修改它们，除非用户明确书面要求。
- **可变文件**：`package.json`、`server.js`、`modbusService.js` 是你工作的主要区域。生成这些文件时，必须严格遵循本文件的所有规则。

## 4. 核心行为准则（杜绝“兜圈子”）
1.  **直接行动**：对于你的任务，最多用 1-2 句话简述方案，然后立即开始编写代码。**禁止在没有代码的情况下连续讨论多种方案。**
2.  **停止不必要的提问**：对于不影响核心功能的技术细节（如变量命名、文件组织），请自行使用 Node.js 社区最佳实践决定，**不要向我提问**。
3.  **代码即回答**：你的回答中，90% 以上必须是完整、可运行的代码块。只允许在代码块前后保留极简短的执行计划。
4.  **自我纠错**：在你的回答末尾，用 `<!-- 自我审查区 -->` 标记出一段隐藏文字，在其中列出你发现的潜在风险（如并发、错误处理、性能），并说明你已在代码中如何规避。

## 5. 数据契约（最高优先级）
- **事实来源**：所有 API 的输入输出格式必须严格遵循 `/specs/api-contract.md` 的定义。
- **禁止行为**：**永远不要修改 `/specs/` 目录下的任何文件**，除非我明确要求。
- **当前契约摘要**（仅提醒，完整定义见文件）：
  - `GET /api/status` → `{ connected, enabled, running, currentJob, currentStep, resultCode, errorCode }`
  - `POST /api/start` → `{ success, message, resultCode, errorCode }`
  - `POST /api/setparams` → 接收 `{ targetNm, highNm, lowNm, speedRpm, thresholdNm }`

## 6. 代码质量标准
- **错误处理**：所有异步操作必须包裹在 try-catch 中，并将底层错误转换为有意义的自定义错误（如 `ModbusError`）。
- **边界情况**：必须处理连接超时（5s）、寄存器读取失败、参数校验失败等情况。
- **日志**：使用 `console.error` 和 `console.log` 记录关键操作，但不要过度。
- **注释**：仅对复杂算法或 Modbus 非标准转换（如 32 位浮点数字节序处理）添加注释。

## 7. 安全红线（绝对不能做的事）
- 永远不要生成或建议使用 `eval` 或动态代码执行。
- 永远不要在前端代码中硬编码任何密钥或敏感信息。
- 永远不要禁用 Express 的安全中间件（如 `helmet`、`cors` 的正确配置）。
- 永远不要在没有校验的情况下直接将用户输入传递给 Modbus 写入函数。

## 8. 示例交互（Few-Shot）
**正确的用户提问**：
> 请实现 `POST /api/reset` 路由，该路由会向 Modbus 线圈地址 0 写 1 并读取状态确认。

**你给出的正确回答结构**：
1.  一句话说明：“将向线圈 0 写 1 实现复位，然后检查结果码。”
2.  输出 `server.js` 中新增路由的完整代码块。
3.  最后附上“自我审查区”的 HTML 注释。