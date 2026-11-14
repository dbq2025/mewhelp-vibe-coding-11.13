# ecom-copilot · 电商智能客服

一个能完成**商品咨询、订单查询、售后受理**的电商客服 Agent。回答里的每个事实都能溯源到数据库记录或知识库片段，写操作（建售后单、转人工）必须经过用户确认才执行。

项目的核心不是"接了个大模型"，而是**把不确定的模型输出关进确定的工程结构里**：意图识别、工具调用、检索增强、多轮记忆、流式体验、可观测与评测六条链路都有明确的边界和验收口径。

前后端全部代码开源，按 P0–P5 六个阶段推进，每阶段都有可复现的实测记录（见 `docs/`）。

## 功能

- **商品咨询** — 按价格/品类/关键词检索商品，支持多轮指代（"第二个多少钱"），参数缺失时如实说"查不到"而不是编造
- **订单物流** — 凭订单号查状态、商品明细、物流轨迹；登录用户仅能查本人订单，游客需"单号 + 手机尾号"双因子，越权与不存在返回同一错误码
- **政策问答** — 25 篇客服知识库 → 127 个语义块 → pgvector 向量检索 + 标题加权混合检索（RRF），回答带可展开的引用卡片
- **售后受理** — 对话里说"我要退货"不会直接建单：先出确认卡片，用户点"确认提交"才落库，重复提交返回同一张工单（幂等）
- **转人工** — 会话级状态机 `pending → accepted → closed`，同会话幂等；连续两次低置信自动触发
- **流式体验** — SSE 八种事件边生成边推送，首字延迟 P95 2.36s；生成中可停止，已生成内容标为"未完成"并可重试
- **可观测** — 每轮对话的 token、延迟、成本、意图分布、工具失败率落 `llm_usage`，`/admin/metrics` 出聚合看板
- **安全** — 输入注入守卫、输出订单号脱敏（流式输出也不会切开受保护词）、IP 限流、审计日志

### 实测数据

来源：`docs/eval.md`、`docs/demo.md`（真实模型 + 真实库，非估算）

- 业务场景验收 — **21/21 通过**（20 条对话场景 + 1 条数据库校验）
- 意图识别准确率 — **59/60 = 0.983**（门槛 0.90）
- 工具选择（集合精确匹配）— **59/60 = 0.983**（门槛 0.85）
- 首字延迟 — P50 **1.63s** / P95 **2.36s**（门槛 2.5s）
- 单轮完成 — P95 **2.80s**（门槛 12s）
- 单轮成本 — **¥0.00086**（门槛 ¥0.01）
- 对抗集 — 注入拦截 **5/5**，越权泄漏 **0/5**
- 检索 — 10 条 query hit@3 **10/10**，MRR 1.0
- 测试 — 后端 **151** 个用例、前端 **13** 个用例全绿

## 技术栈

- **后端** — Python 3.13 · FastAPI · SQLAlchemy 2.0 async + asyncpg · Alembic · Pydantic v2
- **Agent** — LangGraph 1.2（`StateGraph` + `astream`），状态每轮从 DB 重建，**不使用 checkpointer**
- **模型** — DeepSeek `deepseek-chat`（对话/意图）· 硅基流动 `BAAI/bge-m3` 1024 维（向量）
- **数据** — PostgreSQL 16 + pgvector 0.8（Docker，宿主端口 5433），HNSW 索引
- **前端** — Vue 3.5（`<script setup lang="ts">`）· Vite 7 · TypeScript · Tailwind · Pinia · vue-router
- **质量** — 后端 ruff / mypy / pytest；前端 ESLint / vitest / vue-tsc
- **包管理** — 后端 `uv` · 前端 `npm`

## 目录结构

```
.
├── backend/                     # FastAPI + LangGraph 服务
│   ├── src/app/
│   │   ├── core/                # 配置、日志、错误码、trace、限流、鉴权、依赖注入
│   │   ├── api/
│   │   │   ├── routers/         # health / meta / auth / products / orders / chat / after_sales / admin
│   │   │   └── schemas/         # 请求与响应模型（统一 envelope）
│   │   ├── agent/               # 图与节点
│   │   │   ├── graph.py         # START → guard → understand → 路由 → compose → END
│   │   │   ├── nodes/           # understand / actions / after_sales / compose / guard
│   │   │   ├── tools.py         # 6 个工具：search_products / get_product / compare_products
│   │   │   │                    #          get_order / get_shipment / search_policy
│   │   │   ├── guard.py         # 输入守卫 + 输出脱敏（含流式 hold-back 切点保护）
│   │   │   ├── runner.py        # SSE 执行器：事件推送、落库、中断处理
│   │   │   ├── slots.py         # 槽位抽取与确认判定（纯规则，不交给模型）
│   │   │   ├── llm.py           # LLM 客户端：重试、连接池复用、用量计量
│   │   │   └── prompts/         # 版本化 prompt
│   │   ├── rag/                 # 分块 / 向量化 / 检索 / RRF 融合
│   │   ├── domain/
│   │   │   ├── services/        # 业务服务：catalog / orders / after_sales / handoff / metrics
│   │   │   └── policies/        # 鉴权策略（仅本人 / 游客双因子）
│   │   └── infra/db/            # SQLAlchemy models（15 张表）+ session
│   ├── alembic/                 # 迁移（含退货运费、售后单号序列、部分唯一索引）
│   ├── data/                    # seed 数据（账号/商品/订单）与知识库源文件
│   ├── scripts/                 # seed / ingest_kb / 评测 / 演示排练
│   ├── tests/                   # unit / api / graph
│   ├── pyproject.toml           # 依赖与工具配置
│   └── uv.lock                  # 锁定版本（必须入库）
├── frontend/                    # Vue 3 单页应用
│   ├── src/
│   │   ├── views/               # LoginView / ChatView
│   │   ├── components/          # chat（消息列表、输入框）/ layout（头部、侧栏）/ common
│   │   ├── composables/         # useChatStream（SSE 传输）/ useHealth
│   │   ├── stores/              # Pinia：chat（事件状态机）/ session
│   │   ├── lib/                 # api 封装 / SSE 解帧
│   │   ├── styles/              # Tailwind 与设计令牌
│   │   └── types/               # 接口类型
│   ├── package.json
│   └── package-lock.json        # 锁定版本（必须入库）
├── docs/                        # 实现计划、接口契约、数据模型、评测、UI 规范、演示脚本、学习复盘
├── infra/db/init/               # 容器首启建 vector / pg_trgm 扩展
├── docker-compose.yml           # PostgreSQL 16 + pgvector
├── .env.example                 # 环境变量模板（不含真实密钥）
├── agent.md                     # 工程规范：分层铁律、命名、测试矩阵、DoD
└── LICENSE
```

**依赖方向只能向下**：`api → agent → domain → infra`，`core` 横切。删掉 `agent/` 后，`/products`、`/orders` 这些只读接口仍能正常工作——这是判断分层真假的标准。

## 快速开始

### 环境要求

- **Docker Desktop** 已启动（提供 PostgreSQL + pgvector）
- **uv** ≥ 0.5（后端依赖与虚拟环境）
- **Node.js** ≥ 20 与 **npm** ≥ 10
- 两个模型 API Key：[DeepSeek](https://platform.deepseek.com/)（对话）、[硅基流动](https://cloud.siliconflow.cn/)（向量），都有免费额度

### 1. 启动数据库

```bash
docker compose up -d
docker compose ps          # 等待 ecom-copilot-db 变为 healthy
```

容器名 `ecom-copilot-db`，宿主端口 **5433** 映射容器 5432，首次启动自动执行 `infra/db/init/001_extensions.sql` 创建 `vector` 与 `pg_trgm`。

### 2. 配置环境变量

```bash
cp .env.example .env
```

然后编辑 `.env`，**至少填入这两项**：

```ini
LLM_API_KEY=sk-...            # DeepSeek
EMBEDDING_API_KEY=sk-...      # 硅基流动，灌知识库必需
```

`.env` 已被 `.gitignore` 排除，不会进入版本库。完整变量说明见[下一节](#环境变量说明)。

### 3. 安装后端并初始化数据

```bash
cd backend

uv sync                              # 安装依赖（Python 3.13）
uv run alembic upgrade head          # 建表：15 张表
uv run python scripts/seed.py        # 演示数据：3 账号 / 8 分类 / 40 商品 / 30 订单 / 12 物流 / 3 售后
uv run python scripts/ingest_kb.py   # 知识库：25 篇 → 127 块 → 向量入库（需 EMBEDDING_API_KEY）
```

`seed.py` 与 `ingest_kb.py` 都是幂等的，重复执行不会产生重复数据。`ingest_kb.py --dry-run` 只分块不调模型，可在没有 key 时验证分块逻辑。

### 4. 启动后端

```bash
uv run uvicorn app.main:app --reload --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
# {"code":0,"message":"ok","data":{"status":"ok","db":"ok","vector":"ok","vectorVersion":"0.8.7",...}}
```

接口文档：<http://127.0.0.1:8000/docs>（Swagger，可直接登录后试调用）

### 5. 安装并启动前端

另开一个终端：

```bash
cd frontend
npm install
npm run dev
```

打开 <http://localhost:5173/login>，用下面的演示账号登录后即可对话。右上角应显示「服务正常」。

> **Windows 提示**：Vite 默认只监听 `[::1]`，请用 `localhost` 而非 `127.0.0.1` 访问，否则会 502。
> **esbuild 提示**：`npm install` 可能提示 `esbuild` postinstall 未放行，属正常现象——二进制由可选依赖 `@esbuild/win32-x64` 提供，`dev` / `build` 实测正常。

### 五条命令的实测记录

2026-11-13，本机 Windows 11 + Docker Desktop，逐条执行的结果：

- **`docker compose up -d`** — `ecom-copilot-db` Up (healthy)，宿主 5433 ✅（镜像已存在时约 0.5s）
- **`cp .env.example .env` 并填两把 key** — 19 个配置项齐备 ✅（缺 key 时 `ingest_kb.py` 会明确报出缺哪一项，不会静默失败）
- **`uv sync && alembic upgrade head && seed.py && ingest_kb.py`** — 迁移到 head，数据行数与预期一致，KB 25 篇 127 块 ✅（5.4s / 1.2s / 0.9s / 0.9s）
- **`uvicorn --reload --port 8000`** — `/health` 返回 `db:ok` `vector:ok` ✅（启动约 3s）
- **`npm install && npm run dev`** — `localhost:5173` 返回 200，登录后可对话 ✅（360 包约 8s）

> 冷安装说明：前端把 `node_modules` 移走后重装验证（走 npmmirror）。后端 `.venv` 因文件占用无法移走，改用同一份 `pyproject.toml` + `uv.lock` 在临时目录冷同步验证（5.4s，命中 uv 本地缓存）——**这是替代方案，不是等价验证**，如实记录。

## 环境变量说明

模板见 `.env.example`，全部通过 `pydantic-settings` 读取。**标「必填」的项缺失会导致启动或功能失败。**

### 应用

- `ENV` — 运行环境标识，默认 `local`
- `LOG_LEVEL` — 日志级别，默认 `INFO`
- `LOG_JSON` — 是否输出 JSON 结构化日志，本地调试用 `false`

### 数据库

- `PG_DSN` — **必填**，async DSN，默认 `postgresql+asyncpg://app:app_dev_pwd@127.0.0.1:5433/ecom`
- `DB_ECHO` — 是否打印 SQL，默认 `false`
- `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` / `POSTGRES_PORT` — 供 `docker-compose.yml` 使用；改端口时记得同步改 `PG_DSN`

### 鉴权

- `JWT_SECRET` — **生产必须替换**，模板值是 `dev-only-change-me`。生成方式：`openssl rand -hex 32`

### 模型

- `LLM_BASE_URL` — 对话模型 OpenAI 兼容端点，默认 `https://api.deepseek.com/v1`
- `LLM_API_KEY` — **必填**，对话模型密钥
- `LLM_MODEL` — 默认 `deepseek-chat`
- `EMBEDDING_BASE_URL` — 向量模型端点，默认 `https://api.siliconflow.cn/v1`
- `EMBEDDING_API_KEY` — **灌知识库必填**，向量模型密钥
- `EMBEDDING_MODEL` — 默认 `BAAI/bge-m3`
- `EMBEDDING_DIM` — 必须与模型匹配，bge-m3 为 `1024`
- `EMBEDDING_BATCH_SIZE` / `EMBEDDING_CONCURRENCY` — 批量与并发，默认 16 / 4，免费额度下不要调高

### 检索

- `RAG_TOP_K` — 召回条数，默认 `5`
- `RAG_MAX_DISTANCE` — 余弦距离阈值，默认 `0.45`，越小越严；检索总为空时先放宽到 `0.6`

### 限流与运维

- `RATE_LIMIT_PER_MINUTE` — 每 IP 每分钟放行请求数，默认 `30`；**设为 `0` 表示整体关闭**（跑 `eval.py` 前临时关掉，跑完改回来）
- `ADMIN_TOKEN` — `/api/v1/admin/metrics` 的口令，**留空则该端点返回 404**（默认关闭）
- `LLM_PRICE_INPUT_PER_MTOK` / `LLM_PRICE_OUTPUT_PER_MTOK` — 模型单价（元/百万 token），仅用于成本估算，官方调价时改这里

## 可用脚本

### 后端（在 `backend/` 下执行）

- `uv run uvicorn app.main:app --reload --port 8000` — 开发服务器
- `uv run pytest -q` — 全量测试（unit / api / graph）
- `uv run ruff check . && uv run ruff format --check . && uv run mypy src` — 静态检查三件套
- `uv run alembic revision --autogenerate -m "说明"` — 生成迁移
- `uv run alembic downgrade -1` — 回滚一步（验证可逆性）
- `uv run python scripts/seed.py` — 灌/更新演示数据（幂等）
- `uv run python scripts/seed.py --check` — 只打印各表行数
- `uv run python scripts/ingest_kb.py --dry-run` — 只分块，不调 embedding（无需 key）
- `uv run python scripts/ingest_kb.py` — 灌知识库（需 `EMBEDDING_API_KEY`）
- `uv run python scripts/eval_retrieval.py` — 检索评测：10 条 query 的 hit@3，写入 `docs/eval.md`
- `uv run python scripts/eval_scenarios.py` — 20 条业务场景验收（需先起后端）
- `uv run python scripts/eval.py` — 质量评测：意图混淆矩阵 / 工具匹配 / 延迟分位 / 成本 / 对抗集（需先起后端）
- `uv run python scripts/demo_check.py` — 演示排练：S1–S8 全场景跑一遍并打印证据（需先起后端）

### 前端（在 `frontend/` 下执行）

- `npm run dev` — 开发服务器，<http://localhost:5173>
- `npm run build` — 类型检查 + 生产构建（`vue-tsc --noEmit && vite build`）
- `npm run preview` — 预览构建产物
- `npm run lint` — ESLint（`--max-warnings 0`，零警告）
- `npm run test` — vitest：组件渲染 + composable 状态机
- `npm run typecheck` — 仅类型检查

### 数据库与运维

- `docker compose exec db psql -U app -d ecom` — 进库
- `docker compose stop db` / `docker compose start db` — 可用于验证降级（此时 `/health` 返回 503 + `db:down`，业务接口返回 503 + 错误码 `5002`）
- `curl -H "X-Admin-Token: <ADMIN_TOKEN>" "localhost:8000/api/v1/admin/metrics?hours=24"` — 运维看板

## 关键设计

### 一轮对话发生了什么

```
guard → understand → 条件路由
        ├─ sales_agent  商品：search_products / get_product / compare_products
        ├─ order_flow   订单：鉴权 → get_order → get_shipment（确定性链路，不让模型自由编排）
        ├─ retrieve     政策：混合检索 + 引用编号
        ├─ after_sales  售后：鉴权 → 可受理判定 → 待确认 / 建单 / 取消
        ├─ clarify      缺槽或低置信：追问（连续两次低置信 → 转人工）
        └─ handoff      建工单
     → compose（流式生成 + hold-back 输出校验）→ 落库（含不完整内容）
```

**不用 checkpointer** 是有意为之：会话状态的权威在数据库 `session_states.slots`，图内再存一份就会出现两个真源。代价是每轮重建状态（约 10ms），收益是状态永不漂移。

### 写操作不交给模型措辞

"我要退货，订单 20261101008" 不会直接建单。服务端先核验归属与可受理性，回一张确认卡片，用户点"确认提交"（或回"确认"）才落库，返回工单号 `AS20261113xxxx`；重复提交返回**同一张单**。

确认判定在 `agent/slots.py` 的 `classify_confirmation` 里，是纯规则：≤8 字、否定优先、以"不"开头即拒绝。**终态文案全部走模板**，不经过模型——否则会出现"听起来成功了但其实没建单"。

可受理判定同样是代码而非 prompt：未付款 / 待发货 / 已关闭 / 退款中一律不受理；超过 7 天无理由只受理质量问题。判定表见 `docs/api.md §2.6.1`。

### 安全在架构里，不在提示词里

- **鉴权** — 登录用户只能查本人订单；游客需"订单号 + 手机尾号"；**越权与不存在返回同一错误码 `2003`**，先 `commit` 审计再抛异常
- **输入守卫** — 注入模式、超长、刷屏、会话级限流四类拦截
- **输出脱敏** — 未授权的订单号一律改写成"另一笔订单"；流式输出用 40 字符 hold-back 缓冲，并对齐数字边界与"订单"边界，避免把受保护词切成病句

### 接口契约

统一 envelope `{"code":0,"message":"ok","data":...}`，业务错误用 `4xx` + 业务码（如 `4008` 工具预算超限、`4029` 限流、`4009` 会话忙），**依赖不可用一律 `503` + `5002`**（不用 500，避免被读成"代码有 bug"）。完整错误码见 `docs/api.md`。

SSE 八种事件：`meta` / `tool` / `delta` / `citation` / `slots` / `action` / `done` / `error`。

## 演示账号

- **主测账号 A** — `13800000001` / `Test123456`，14 笔订单
- **他人账号 B** — `13800000002` / `Test123456`，8 笔订单（用于越权测试）
- **第二用户 C** — `13800000003` / `Test123456`，8 笔订单

订单号形如 `20261101001`（A 的首单，已发货并带物流轨迹）。游客查单示例：`GET /api/v1/orders/20261101023?phoneTail=0002`。

## 文档索引

- `docs/IMPLEMENTATION_PLAN.md` — 实现计划：功能分级、选型、架构、P0–P5 验收口径、偏差记录
- `docs/api.md` — 接口契约 v0.6.0：端点、请求响应、错误码、SSE 事件
- `docs/data-model.md` — 15 张表结构与索引说明
- `docs/eval.md` — 检索评测、业务场景验收、质量评测、人工抽查结论（含未达标项解释）
- `docs/ui.md` — 视觉规范：颜色令牌、字号、间距、组件状态、移动端规则
- `docs/demo.md` — 8 分钟演示脚本：时间分配、台词、预期原文、兜底话术
- `docs/PROJECT_REVIEW.md` — 学习向复盘：架构拆解、AI 介入方式、20 条决策取舍、可复用方法
- `agent.md` — 工程规范：分层铁律、Python/TS/Vue 编码约定、测试矩阵、DoD、禁止清单

## 常见问题

**`/health` 返回 503 且 `db: down`** — Docker 未启动或端口不是 5433。`docker compose ps` 确认后 `docker compose up -d`。

**`vector: missing`** — 旧数据卷未执行初始化脚本。`docker compose exec db psql -U app -d ecom -c "CREATE EXTENSION IF NOT EXISTS vector"`。

**`alembic` 报 `UnicodeDecodeError: 'gbk'`** — `alembic.ini` 必须是纯 ASCII（Windows 用系统 locale 读取 ini）。数据库地址配在 `alembic/env.py` 里，不要写进 ini。

**前端 502 / 打不开** — 用 `localhost:5173`，Vite 默认不监听 IPv4 回环。

**`ingest_kb.py` 报维度不符** — `EMBEDDING_MODEL` 与 `EMBEDDING_DIM` 必须匹配（bge-m3 = 1024）。

**检索总是返回空** — `RAG_MAX_DISTANCE` 太严，先放宽到 `0.6` 看召回。

**`uv sync` 很慢** — 配置国内镜像：`UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple`。

**浏览器提示"请求太频繁"** — 触发了 `RATE_LIMIT_PER_MINUTE`（默认 30/分钟/IP），按提示秒数等待，或本地调高。

## 许可证

[MIT](LICENSE) © 2026 DBQ2025

可自由使用、修改、分发、商用，需保留版权声明与许可声明。项目中的商品、订单、知识库内容均为演示用虚构数据。
