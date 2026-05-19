# Codex 任务：修复产品/配方显示不切换的 Bug

## 问题

在「操作员与流程」面板切换产品型号后，顶部「产品/配方」区域的文字不更新。

## 项目路径

```
S:\expansion_valve_hmi
```

## 涉及文件（只读这几个）

- `web/app.js` — 前端逻辑
- `web/index.html` — 顶部摘要区 `#productText` 和 `#recipeText`
- `app/main.py` — 服务端 settings API
- `app/workflow.py` — `snapshot()` 方法，返回 `settings_summary`

## 现象

1. 用户在下拉框切换产品（HB11 → E22H）
2. 下拉框自身正常切换
3. 顶部「产品/配方」文字不变化，仍显示旧产品
4. 1.5s 后轮询刷新也不变

## 现有逻辑（可能有问题的地方）

### 切换时 (`productSelect.change` 事件，约 1663 行)

当前代码：
- 找到 product 配置
- 写 Kilews 参数
- 设置 `window.__selectedProduct`
- 更新 `settings.station.active_product_model`
- 直接更新 DOM `$("#productText")` 和 `$("#recipeText")`

### 轮询刷新 (`renderStatus`，约 1223 行)

```
displayProduct = window.__selectedProduct || settings.station.active_product_model || snapshot.settings_summary.product_model
  → 在 settings.products 里找对应配置
  → 找到就用客户端的值
  → 找不到就用服务端快照值
```

### 服务端快照 (`workflow.py snapshot()`)

```
settings_summary.product_model = 来自 self.settings["station"]["active_product_model"]
```

服务端的 `active_product_model` 不会随前端切换自动更新（前端没有调 `POST /api/settings`）。

## 可能的根因

1. 客户端 `settings.products` 没加载或为空 → `prodCfg` 找不到 → 回退到快照值
2. `renderStatus` 轮询覆盖了切换时的 DOM 更新
3. 切换时更新的 `settings.station.active_product_model` 被某些代码重置
4. 快照的 `settings_summary` 始终返回旧产品（服务端未同步）

## 你的任务

找出为什么切换后显示不更新，直接改代码修好。不要只给建议。
