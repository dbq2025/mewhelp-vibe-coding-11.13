# 数据模型 · ecom-copilot

> 版本：v0.1.0（P0，对应迁移 `20261113_3567da1bb39f_init_schema.py`）
> 事实来源：`backend/src/app/infra/db/models/`。本文件与模型不一致时以模型为准，但必须同步修订本文件。

---

## 1. 全局规则

| 规则 | 说明 |
|---|---|
| 主键 | 业务表用 `bigint` 自增；会话用 `uuid`（防枚举） |
| 时间 | 一律 `timestamptz`，默认 `now()`；禁止存本地时区字符串 |
| 金额 | 一律整数分 `bigint`，字段名 `*_cents`；不用 float/numeric 存金额 |
| 结构不固定 | 商品属性、工具调用、引用、槽位一律 `jsonb`，不硬造稀疏列 |
| 删除 | 会话走软删 `status='deleted'`；其余物理删（仅测试环境） |
| 命名 | 表复数 snake_case，约束名由命名约定自动生成（`pk_/fk_/uq_/ix_`） |
| 隐私 | 不落明文手机号/地址；订单只存 `receiver_phone_tail`（4 位）与脱敏地址 |

关系概览：

```
users 1─┬─* sessions 1─┬─* messages
        │              ├─1 session_states
        │              └─* handoff_tickets
        ├─* orders 1─┬─* order_items *─1 products *─1 categories
        │            ├─1 shipments
        │            └─* after_sales
        └─* after_sales

kb_docs 1─* kb_chunks (embedding vector(1024))
llm_usage / audit_events：独立运维表，按 trace_id 与业务关联
```

---

## 2. 表定义

### 2.1 users

| 字段 | 类型 | 约束 |
|---|---|---|
| id | bigint | PK |
| phone | varchar(20) | unique，登录名 |
| nickname | varchar(50) | 默认 `''` |
| password_hash | varchar(255) | scrypt，salt 内嵌 |
| created_at | timestamptz | `now()` |

### 2.2 sessions

| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK，默认 `uuid4()` |
| user_id | bigint | FK users，`ON DELETE CASCADE` |
| title | varchar(100) | 默认 `新会话`，首轮后按首问截断 20 字 |
| status | varchar(16) | `active` / `deleted` |
| created_at / updated_at | timestamptz | `updated_at` 应用层 onupdate |

索引：`idx_sessions_user_updated (user_id, updated_at)`、`ix_sessions_user_id`。

### 2.3 messages

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint | PK |
| session_id | uuid | FK sessions，级联删 |
| role | varchar(16) | `user` / `assistant` / `system` / `tool` |
| content | text | 正文 |
| intent | varchar(32) | 本轮意图（assistant 行记录判定结果） |
| tool_calls | jsonb | 工具轨迹 `[{name, args, ok, latencyMs}]` |
| citations | jsonb | 引用 `[{index, title, docId, snippet}]` |
| prompt_tokens / completion_tokens | int | 计量 |
| latency_ms | int | 本轮耗时 |
| trace_id | varchar(32) | 与日志、`llm_usage` 对齐 |
| status | varchar(16) | `ok` / `incomplete` / `blocked` |
| client_msg_id | varchar(64) | 幂等键，可空 |
| created_at | timestamptz | |

索引：
- `idx_messages_session_id (session_id, id)` —— 历史分页
- `uk_messages_session_client_msg (session_id, client_msg_id) WHERE client_msg_id IS NOT NULL` —— 幂等

### 2.4 session_states（单一真源）

| 字段 | 类型 | 说明 |
|---|---|---|
| session_id | uuid | PK + FK sessions，级联删 |
| slots | jsonb | `order_no / product_id / category / price_max / after_sales_type` |
| last_intent | varchar(32) | 上轮意图 |
| turn_count | int | 轮次，>20 触发摘要 |
| summary | text | 超长会话摘要 |
| handoff_status | varchar(20) | `none` / `pending` / `done` |
| updated_at | timestamptz | |

> 不引入 LangGraph checkpointer：状态每轮从本表 + messages 重建，避免双真源。

### 2.5 categories / products

**categories**：`id` PK、`name`、`parent_id`（自引用，`SET NULL`）、`path`（如 `/耳机/降噪`）。

**products**

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint | PK |
| sku | varchar(40) | unique |
| name | varchar(200) | |
| category_id | int | FK categories |
| brand | varchar(50) | 索引 |
| price_cents | bigint | 整数分 |
| stock | int | |
| status | varchar(16) | `on_sale` / `off_shelf` |
| attrs | jsonb | 类目差异化属性（降噪深度、防水等级…） |
| description | text | |
| image_url | varchar(500) | |
| created_at / updated_at | timestamptz | |

索引：`idx_products_cat_price (category_id, price_cents) WHERE status='on_sale'` —— 对应"类目 + 价格区间"列表查询；`ix_products_brand`；`uq_products_sku`。

### 2.6 orders / order_items / shipments

**orders**

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint | PK |
| order_no | varchar(32) | unique，业务单号 |
| user_id | bigint | FK users，**所有查询必须带此条件** |
| status | varchar(20) | `pending_pay/pending_ship/shipped/signed/refunding/closed` |
| total_cents | bigint | |
| receiver_phone_tail | varchar(4) | 游客查单凭据 |
| receiver_address_masked | varchar(200) | 只到市级 |
| created_at / paid_at | timestamptz | `paid_at` 可空 |

索引：`ix_orders_user_id`、`uq_orders_order_no`、`idx_orders_user_created (user_id, created_at)`。

**order_items**：`order_id` FK 级联删、`product_id` FK、`sku_snapshot`、`name_snapshot`、`qty`、`unit_price_cents`。
> 快照设计：商品改名/调价不得改变历史订单展示。

**shipments**：`order_id` FK **unique**（一单一物流记录）、`carrier`、`tracking_no`、`status`、`events jsonb`（轨迹数组）、`updated_at`。

### 2.7 after_sales

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint | PK |
| ticket_no | varchar(32) | unique，售后单号 |
| order_id | bigint | FK orders 级联删 |
| order_no | varchar(32) | 快照，便于直接按单号排查 |
| user_id | bigint | FK users |
| type | varchar(16) | `return` / `exchange` / `repair` |
| status | varchar(20) | 默认 `pending` |
| reason | text | 用户原话（脱敏后） |
| created_at | timestamptz | |

### 2.8 kb_docs / kb_chunks

**kb_docs**：`id`、`title varchar(200)`、`category varchar(50)`（索引）、`source`、`version`、时间戳。

**kb_chunks**

| 字段 | 类型 | 说明 |
|---|---|---|
| id | bigint | PK |
| doc_id | bigint | FK kb_docs 级联删 |
| seq | int | 文档内序号 |
| content | text | 原文片段 |
| content_seg | text | jieba 预分词文本（空格分隔），供全文检索 |
| meta | jsonb | 标题/章节等 |
| embedding | vector(1024) | bge-m3；可空，灌库时写入 |

索引：
- `uk_kb_chunks_doc_seq (doc_id, seq)` unique —— 灌库幂等
- `idx_kb_chunks_hnsw (embedding) USING hnsw (vector_cosine_ops) WITH (m=16, ef_construction=64)` —— 向量召回
- `idx_kb_chunks_tsv USING gin (to_tsvector('simple', content_seg))` —— 关键词召回
- `ix_kb_chunks_doc_id`

> 中文不装 zhparser（Windows 编译坑），改 jieba 预分词 + `simple` 配置，效果可接受且零依赖。

### 2.9 运维表

**handoff_tickets**：`session_id` FK、`reason varchar(200)`、`status`（`pending/done`）。

**llm_usage**：`trace_id`（索引）、`session_id`、`model`、`prompt_tokens`、`completion_tokens`、`latency_ms`、`ok`、`error_code`、`created_at`（索引）。成本与稳定性看板唯一数据源。

**audit_events**：`trace_id`、`actor`、`action`（`order_query` / `prompt_injection` / `pii_blocked`…）、`target`、`result`（`allowed/denied`）、`meta jsonb`、`created_at`（索引）。

---

## 3. 必须由代码保证的不变量

1. **越权即无记录**：订单/会话查询的归属条件写在 SQL `WHERE` 里，禁止查出来再在 Python 判断。
2. **金额只增不减的整数**：写入前断言 `>= 0`；禁止用浮点做金额运算。
3. **状态流转白名单**：订单/售后状态变更只允许既定迁移（P3 在 `domain` 层实现状态机），禁止任意字符串写入。
4. **PII 不入库**：任何新表新增列若可能含手机号/地址，必须脱敏后再存，并在本文件登记。
5. **槽位与会话同生命周期**：`session_states` 与 `sessions` 一一对应，会话软删后槽位不再参与路由。
6. **单会话串行**：写消息前取 `pg_advisory_xact_lock(hash(session_id))`（P2 实现），避免并发交错。

---

## 4. 迁移约定

```bash
cd backend
uv run alembic revision --autogenerate -m "描述"
uv run alembic upgrade head
uv run alembic downgrade -1      # 验证可回滚
```

- 每个迁移必须能 `downgrade`，否则视为不合格。
- `env.py` 从 `app.core.config` 读 DSN，禁止在 `alembic.ini` 里写连接串（防错库）。
- 索引与表达式索引在模型里声明（`__table_args__`），不在迁移里手写，保证 autogenerate 一致。
- 初始迁移显式 `CREATE EXTENSION IF NOT EXISTS vector / pg_trgm`：新机器没跑过 init 脚本也能建表。
