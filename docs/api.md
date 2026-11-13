# API 契约 · ecom-copilot

> 版本：v0.1.0（P0）
> 本文件是**前后端唯一契约**。改动接口必须先改本文件，再改代码（agent.md §6）。
> 表内 `状态` 列含义：`已实现` = P0 已可调用；`规划` = 后续阶段实现，字段可提前对齐。

---

## 1. 通用约定

### 1.1 响应 envelope

所有非流式接口（含错误）统一返回：

```json
{
  "code": 0,
  "message": "ok",
  "data": {},
  "traceId": "5ef6b9b8140e479e"
}
```

- `code` 为 `0` 表示成功，非 0 见 §3 错误码。
- `data` 在错误时为 `null`。
- `traceId` 同时写入响应头 `X-Trace-Id`，客户端可回传同名字段复用（便于串联日志）。

### 1.2 数据类型约定

| 类型 | 约定 |
|---|---|
| 时间 | ISO 8601 UTC 字符串，带 `Z`，如 `2026-11-13T01:44:07Z`；前端负责本地化 |
| 金额 | **整数分**，字段名以 `Cents` 结尾；前端展示时除以 100 |
| ID | 用户/商品/订单用整数或业务号字符串；会话用 UUID |
| 布尔 | `true` / `false`，不用 0/1 |

### 1.3 分页

统一 cursor 分页，禁止 offset 深翻页：

```
GET /api/v1/sessions?limit=20&cursor=<上一页最后一条 id>
```

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [],
    "page": { "nextCursor": "128", "hasMore": true, "total": null }
  },
  "traceId": "..."
}
```

`limit` 默认 20，上限 100；越界按上限截断。

### 1.4 鉴权

- 头：`Authorization: Bearer <jwt>`
- 需要登录：会话、聊天、售后、我的订单。
- 游客查单：`GET /orders/{orderNo}?phoneTail=1234`（订单号 + 手机尾号 4 位）。
- 越权与不存在**返回同一个错误码 2003**，防订单号探测（计划 §5.3）。

### 1.5 幂等

`POST /chat/stream` 接受 `clientMsgId`（会话内唯一）。重复提交返回同一 `messageId` 与已生成内容，不重复计费。服务端以 `uk_messages_session_client_msg` 唯一索引兜底。

---

## 2. 端点清单

### 2.1 基础设施

| 方法 | 路径 | 状态 | 说明 |
|---|---|---|---|
| GET | `/health` | 已实现 | 存活 + DB + pgvector 探测 |
| GET | `/api/v1/meta` | 已实现 | 服务名/版本/接口前缀，前端启动自检用 |

**GET /health**

真实执行 `select 1` 与一次向量距离运算，任一失败返回 `503`（envelope 结构不变，`data.status = degraded`）。

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "status": "ok",
    "db": "ok",
    "vector": "ok",
    "vectorVersion": "0.8.7",
    "version": "0.1.0",
    "env": "local"
  },
  "traceId": "26aa80ff89ce4c98"
}
```

`vector` 取值：`ok` / `missing`（扩展未装）/ `broken`（装了但运算失败）/ `unknown`（DB 不可用）。

### 2.2 账号（P1）

| 方法 | 路径 | 状态 | 请求 | 响应 data |
|---|---|---|---|---|
| POST | `/api/v1/auth/register` | 规划 | `{phone, password, nickname}` | `{userId, token}` |
| POST | `/api/v1/auth/login` | 规划 | `{phone, password}` | `{token, expiresAt, user}` |
| GET | `/api/v1/auth/me` | 规划 | — | `{id, phone(masked), nickname}` |

### 2.3 会话（P2）

| 方法 | 路径 | 状态 | 说明 |
|---|---|---|---|
| GET | `/api/v1/sessions` | 规划 | 按 `updated_at` 倒序，cursor 分页 |
| POST | `/api/v1/sessions` | 规划 | 新建，返回 `{id, title}` |
| PATCH | `/api/v1/sessions/{id}` | 规划 | 重命名 `{title}` |
| DELETE | `/api/v1/sessions/{id}` | 规划 | 软删（`status='deleted'`） |
| GET | `/api/v1/sessions/{id}/messages` | 规划 | 历史消息，cursor 分页 |

### 2.4 对话（P2）

| 方法 | 路径 | 状态 | 说明 |
|---|---|---|---|
| POST | `/api/v1/chat/stream` | 规划 | SSE，body `{sessionId, message, clientMsgId}`，见 §4 |
| POST | `/api/v1/messages/{id}/feedback` | 规划 | `{rating: 1|-1, comment?}` |

### 2.5 商品（P1）

| 方法 | 路径 | 状态 | 说明 |
|---|---|---|---|
| GET | `/api/v1/products` | 规划 | `q / category / priceMin / priceMax / sort / limit / cursor` |
| GET | `/api/v1/products/{id}` | 规划 | 详情；不存在返回 2004（不猜） |

### 2.6 订单与售后（P1/P3）

| 方法 | 路径 | 状态 | 说明 |
|---|---|---|---|
| GET | `/api/v1/orders` | 规划 | 我的订单（必须登录） |
| GET | `/api/v1/orders/{orderNo}?phoneTail=` | 规划 | 详情，带鉴权；越权 2003 |
| GET | `/api/v1/orders/{orderNo}/shipment` | 规划 | 承运商 + 轨迹；无记录表示未发货 |
| POST | `/api/v1/after-sales` | 规划 | `{orderNo, type, reason}`，返回工单号 |
| POST | `/api/v1/handoff` | 规划 | `{sessionId, reason}`，建转人工工单 |

### 2.7 运营（P4）

| 方法 | 路径 | 状态 | 说明 |
|---|---|---|---|
| GET | `/api/v1/admin/metrics` | 规划 | 会话数 / 意图分布 / P95 延迟 / 成本 / 工具失败率 |

---

## 3. 错误码

| code | 含义 | HTTP |
|---|---|---|
| 0 | 成功 | 200 |
| 1001 | 参数校验失败 | 400 |
| 2001 | 未认证 | 401 |
| 2003 | 越权或资源不存在（不区分） | 403 |
| 2004 | 资源不存在 | 404 |
| 3001 | 模型超时 | 504 |
| 3002 | 上游限流 | 429 |
| 3003 | 内容被安全策略拦截 | 200（SSE `error` 事件） |
| 4009 | 会话忙（同会话并发） | 409 |
| 5000 | 内部错误 | 500 |

错误示例：

```json
{ "code": 2003, "message": "资源不存在或无权访问", "data": null, "traceId": "..." }
```

约定：`message` 面向用户可读，不暴露堆栈、SQL、内部路径。

---

## 4. SSE 协议（P2 实现，先冻结字段）

`POST /api/v1/chat/stream`，`Content-Type: text/event-stream`。
**HTTP 状态恒为 200**，错误通过 `error` 事件传递（流已开头无法改状态码）。

| event | data | 时机 |
|---|---|---|
| `meta` | `{messageId, traceId, intent, confidence}` | 意图判定完成 |
| `tool` | `{name, status: "start"\|"end", summary}` | 工具调用前后 |
| `delta` | `{text}` | 正文增量 |
| `slots` | `{...}` | 槽位变更 |
| `citation` | `{index, title, docId, snippet}` | 生成结束前批量推送 |
| `done` | `{messageId, usage:{prompt, completion}, latencyMs}` | 正常结束 |
| `error` | `{code, message, retryable}` | 异常兜底 |

帧格式示例：

```
event: delta
data: {"text":"这款耳机的"}

event: done
data: {"messageId":"1024","usage":{"prompt":812,"completion":96},"latencyMs":1840}
```

客户端要求：
- 必须处理七种事件 + 网络中断；中断后按 `messageId` 拉取补全。
- `delta` 追加到当前 assistant 消息；`done` 后落库。
- 用户点"停止"即 abort，服务端收到断开后把该消息标 `incomplete`。

---

## 5. 变更记录

| 版本 | 阶段 | 内容 |
|---|---|---|
| v0.1.0 | P0 | 建立 envelope、错误码、`/health`、`/meta`；其余端点冻结字段待实现 |
