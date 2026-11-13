# ecom-copilot · 电商智能客服

一个能完成**商品咨询、订单查询、售后受理**的电商客服 Agent，回答中的每个事实都能溯源到数据库或知识库。
本项目用于跑通生产级 AI 应用的六条链路：意图识别、工具调用、检索增强、多轮记忆、流式体验、可观测与评测。

> 当前阶段：**P2 对话主链路已完成**（P0 基座 + P1 数据检索 + P2 流式对话/多轮/会话历史）。
> 验收实测：3 轮指代接续正确、首 token 中位数 1.16s、同会话并发串行、中断落 `incomplete`，
> 数据见 `docs/eval.md`。
> 范围与验收见 `docs/IMPLEMENTATION_PLAN.md`，工程规范见 `agent.md`，接口契约见 `docs/api.md`。

---

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.13 · FastAPI · SQLAlchemy 2.0 async · Alembic |
| 数据库 | PostgreSQL 16 + pgvector（Docker） |
| Agent | LangGraph 1.2（guard → understand → 路由 → 工具/检索 → compose）· DeepSeek `deepseek-chat` · bge-m3 |
| 前端 | Vue 3.5 · Vite · TypeScript · Tailwind · Pinia · vue-router |
| 包管理 | 后端 `uv` · 前端 `npm` |

---

## 快速开始

前置：Docker Desktop 已启动、`uv` 与 Node 20+ 可用。

```bash
# 1. 起数据库（pgvector/pg16，宿主端口 5433）
docker compose up -d

# 2. 填环境变量（项目根目录）
cp .env.example .env      # 首次；然后填入 EMBEDDING_API_KEY（P1 灌库必需）

# 3. 后端依赖 + 建表 + 演示数据
cd backend && uv sync && uv run alembic upgrade head
uv run python scripts/seed.py          # 40 商品 / 30 订单 / 3 账号，幂等
uv run python scripts/ingest_kb.py     # 25 篇政策 → 127 块 → 向量入库（需要 key）

# 4. 起后端（http://127.0.0.1:8000）
uv run uvicorn app.main:app --reload --port 8000

# 5. 起前端（http://localhost:5173）
cd ../frontend && npm install && npm run dev
```

验证：

```bash
curl http://127.0.0.1:8000/health
# {"code":0,"message":"ok","data":{"status":"ok","db":"ok","vector":"ok","vectorVersion":"0.8.7",...}}
```

打开 <http://localhost:5173/chat> ，右上角应显示「服务正常」。

> Windows 提示：Vite 默认只监听 `[::1]`，请用 `localhost` 而非 `127.0.0.1` 访问前端。

---

## 常用命令

```bash
# 后端（在 backend/）
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run pytest -q
uv run alembic revision --autogenerate -m "说明"   # 新增迁移
uv run alembic downgrade -1                        # 验证可回滚

# 前端（在 frontend/）
npm run lint
npm run test           # vitest：组件渲染 + composable 状态机
npm run build          # vue-tsc 类型检查 + 构建

# 数据与检索（在 backend/）
uv run python scripts/seed.py                # 灌/更新演示数据（幂等）
uv run python scripts/seed.py --check        # 只打行数
uv run python scripts/ingest_kb.py --dry-run # 只分块，不调 embedding（无需 key）
uv run python scripts/ingest_kb.py           # 灌库（需要 EMBEDDING_API_KEY）
uv run python scripts/eval_retrieval.py      # 10 条 query 的 hit@3，写入 docs/eval.md

# 数据库
docker compose exec db psql -U app -d ecom
```

---

## 目录结构

```
backend/
  src/app/
    core/     配置、日志、错误码、trace、依赖注入
    api/      routers（薄）+ schemas
    agent/    图、节点、状态、prompt、工具、守卫、执行器（P2）
    tools/    5 个工具（P3 起）
    rag/      分块 / 向量化 / 检索 / 重排
    domain/   services + policies（业务规则与鉴权）
    infra/    db（models / session）
  alembic/    迁移
  tests/      unit / api / graph / eval
frontend/
  src/
    views/ components/ composables/ stores/ lib/ types/ styles/
docs/         IMPLEMENTATION_PLAN.md · api.md · data-model.md
infra/db/init/001_extensions.sql   首启建 vector / pg_trgm
```

依赖方向只能向下：`api → agent → tools/rag → domain → infra`，`core` 横切。

---

## 阶段进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 基座与契约 | ✅ 已完成 |
| P1 | 数据、检索与只读 API | ✅ 代码与接口已完成（检索验收待 API Key） |
| P2 | 对话主链路（SSE + 多轮 + 会话历史） | ✅ 已完成（2026-11-13） |
| P3 | 业务闭环（工具 / 订单 / 售后） | 待开始 |
| P4 | 质量、安全与可观测 | 待开始 |
| P5 | 体验与交付 | 待开始 |

---

## 对话链路（P2）

```bash
# 登录拿 token（后续请求带 Authorization: Bearer <token>）
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"phone":"13800000001","password":"Test123456"}'

# 新建会话
curl -s -X POST http://127.0.0.1:8000/api/v1/sessions \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}'

# 流式对话（SSE 七事件：meta/tool/delta/citation/slots/done/error）
curl -N -X POST http://127.0.0.1:8000/api/v1/chat/stream \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"sessionId":"<id>","message":"1000 以内的降噪耳机有哪些","clientMsgId":"c-1"}'
```

一轮对话里发生了什么（`agent/graph.py`）：

```
guard → understand → 条件路由
        ├─ sales_agent  商品：search_products / get_product / compare_products
        ├─ order_flow   订单：鉴权 → get_order → get_shipment（确定性链路，不让模型自由编排）
        ├─ retrieve     政策：向量检索 + 引用编号
        ├─ clarify      缺槽/低置信：追问（连续 2 次低置信 → 转人工）
        └─ handoff      建工单
     → compose（流式生成 + hold-back 输出校验） → 落库（含不完整内容）
```

前端：`npm run dev` 后打开 `http://localhost:5173/login`，用演示账号登录即可对话。
侧边栏切换/删除会话、刷新后历史完整；生成中可"停止"，已生成内容会标为「未完成」并提供「重试本条」。

---

## 演示账号

| 账号 | 手机号 | 口令 | 用途 |
|---|---|---|---|
| 主测账号 A | 13800000001 | Test123456 | 14 笔订单 |
| 他人账号 B | 13800000002 | Test123456 | 8 笔订单，越权测试用 |
| 第二用户 C | 13800000003 | Test123456 | 8 笔订单 |

订单号形如 `20261101001`（A 的首单，已发货，带物流轨迹）。
游客查单：`GET /api/v1/orders/20261101023?phoneTail=0002`。

---

## 常见问题

| 现象 | 处理 |
|---|---|
| `/health` 返回 503 且 `db: down` | Docker 未启动或端口不是 5433：`docker compose ps` 后 `docker compose up -d` |
| `vector: missing` | 库是旧卷且未跑 init 脚本：`docker compose exec db psql -U app -d ecom -c "CREATE EXTENSION vector"` |
| `alembic` 报 `UnicodeDecodeError: 'gbk'` | `alembic.ini` 必须保持纯 ASCII（Windows 用系统 locale 读 ini） |
| 前端 502 / 打不开 | 用 `localhost:5173`；Vite 默认不监听 IPv4 回环 |
| `ingest_kb.py` 报未配置 EMBEDDING_API_KEY | 在项目根 `.env` 填 `EMBEDDING_API_KEY=sk-...` 后重跑 |
| `ingest_kb.py` 报维度不符 | `EMBEDDING_MODEL` 与 `EMBEDDING_DIM` 必须匹配（bge-m3 = 1024） |
| 检索总是返回空 | `RAG_MAX_DISTANCE` 太严（默认 0.45），先放宽到 0.6 看召回 |
| `uv sync` 很慢 | 配置国内 PyPI 镜像（`UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple`） |
