# ecom-copilot · 电商智能客服

一个能完成**商品咨询、订单查询、售后受理**的电商客服 Agent，回答中的每个事实都能溯源到数据库或知识库。
本项目用于跑通生产级 AI 应用的六条链路：意图识别、工具调用、检索增强、多轮记忆、流式体验、可观测与评测。

> 当前阶段：**P5 体验与交付已完成**（P0 基座 → P1 数据检索 → P2 流式对话 → P3 售后闭环 → P4 质量安全 → P5 体验交付）。
> 验收实测：20 条业务场景 **21/21 通过**；P4 评测集意图 0.983 / 工具 0.983 / 首字 P95 2.36s / 单轮 ¥0.00086；
> 注入拦截 5/5、越权泄漏 0；移动端 375px 可用、停库可降级。数据见 `docs/eval.md` 与 `docs/demo.md`。
> 范围与验收见 `docs/IMPLEMENTATION_PLAN.md`，工程规范见 `agent.md`，接口契约见 `docs/api.md`，界面规范见 `docs/ui.md`。

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

### 五条命令的实测记录（2026-11-13，本机 Windows 11 + Docker Desktop）

| # | 命令 | 预期 | 实测 | 耗时 |
|---|---|---|---|---|
| 1 | `docker compose up -d` | `ecom-copilot-db` Up (healthy)，宿主 5433 | ✅ 一致（首次拉镜像除外） | 0.5s（镜像已存在） |
| 2 | `cp .env.example .env` 后填 `LLM_API_KEY`/`EMBEDDING_API_KEY` | 两把 key 非空；缺 key 时 `ingest_kb.py` 会明确报错 | ✅ 19 个配置项齐备 | — |
| 3 | `cd backend && uv sync && uv run alembic upgrade head && uv run python scripts/seed.py && uv run python scripts/ingest_kb.py` | 迁移到 head；seed 幂等（3 用户/8 分类/40 商品/30 订单/40 明细/12 物流/3 售后）；KB 25 篇 127 块 | ✅ 完全一致 | uv sync 5.4s（有缓存）· alembic 1.2s · seed --check 0.9s · ingest --dry-run 0.9s |
| 4 | `uv run uvicorn app.main:app --reload --port 8000` | `/health` 返回 `db:ok` `vector:ok` | ✅ | 启动约 3s |
| 5 | `cd ../frontend && npm install && npm run dev` | `localhost:5173` 返回 200，登录后可对话 | ✅ 360 包 8s；构建与单测全绿 | npm install 8s |

> 冷安装说明：本轮把 `frontend/node_modules` 移走后重装（360 包 / 8s，走 npmmirror）。
> `backend/.venv` 因文件被占用无法移走，改用**同一份 `pyproject.toml` + `uv.lock` 在临时目录冷同步**验证（5.4s，命中 uv 本地缓存）。
> `npm install` 会提示 `esbuild` 的 postinstall 未被 allow-scripts 放行，但 `@esbuild/win32-x64` 已作为可选依赖安装，`npm run dev`/`build` 实测正常。

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
uv run python scripts/eval_scenarios.py      # 20 条业务场景验收（需先起后端，用真实模型）
uv run python scripts/eval.py                # P4 评测：意图/工具/延迟/成本/对抗集（需先起后端）
uv run python scripts/demo_check.py         # P5 演示排练：S1–S7 全场景跑一遍并打印证据（需先起后端）

# 运维（后端需配置 ADMIN_TOKEN）
curl -H "X-Admin-Token: local-admin-token" "localhost:8000/api/v1/admin/metrics?hours=24"

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
docs/         IMPLEMENTATION_PLAN.md · api.md · data-model.md · eval.md · ui.md · demo.md
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
| P3 | 业务闭环（售后受理 / 转人工 / 混合检索） | ✅ 已完成（2026-11-13） |
| P4 | 质量、安全与可观测（限流 / 计量 / 看板 / 评测） | ✅ 已完成（2026-11-13） |
| P5 | 体验与交付（UI 打磨 / README 五命令 / 演示脚本） | ✅ 已完成（2026-11-13） |

---

## 售后受理（P3）

对话里说"我要退货，订单 20261101008"，服务端**不会直接建单**：

```
用户：我要退货，订单 20261101008
客服：我核对到这笔订单：
      · 订单号：20261101008（已发货）
      · 商品：极光 65W 双口充电器×1
      · 金额：¥159.00
      · 申请事项：退货退款
      确认无误的话回复「确认提交」…            [确认提交] [先不申请]
```

点"确认提交"才真的建单（也可以直接打字），返回工单号 `AS20261113xxxx`；
重复点只会返回**同一张单**，不会产生第二张。

也可绕过对话直接调接口：

```bash
# 申请售后（幂等，同订单同类型只留一张未完结单）
curl -s -X POST http://127.0.0.1:8000/api/v1/after-sales \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"orderNo":"20261101008","type":"return","reason":"耳机有杂音"}'

# 我的售后单
curl -s http://127.0.0.1:8000/api/v1/after-sales -H "Authorization: Bearer $TOKEN"

# 转人工（同一会话幂等）/ 状态流转
curl -s -X POST http://127.0.0.1:8000/api/v1/handoff \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"sessionId":"<id>","reason":"想找人核实"}'
curl -s -X PATCH http://127.0.0.1:8000/api/v1/handoff/HO202611130001 \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"status":"accepted"}'
```

**可受理判定在代码里，不在 prompt 里**：未付款/待发货/已关闭/退款中一律不收；
超 7 天无理由仅受理质量问题（关键词判定）。判定表见 `docs/api.md §2.6.1`。

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
