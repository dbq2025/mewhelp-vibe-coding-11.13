# ecom-copilot · 电商智能客服

一个能完成**商品咨询、订单查询、售后受理**的电商客服 Agent，回答中的每个事实都能溯源到数据库或知识库。
本项目用于跑通生产级 AI 应用的六条链路：意图识别、工具调用、检索增强、多轮记忆、流式体验、可观测与评测。

> 当前阶段：**P0 基座与契约已完成**（骨架 / 数据模型 / 迁移 / 健康检查 / 前端壳）。
> 范围与验收见 `docs/IMPLEMENTATION_PLAN.md`，工程规范见 `agent.md`，接口契约见 `docs/api.md`。

---

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.13 · FastAPI · SQLAlchemy 2.0 async · Alembic |
| 数据库 | PostgreSQL 16 + pgvector（Docker） |
| Agent | LangGraph（P2 起）· DeepSeek `deepseek-chat` · bge-m3（1024 维） |
| 前端 | Vue 3.5 · Vite · TypeScript · Tailwind · Pinia · vue-router |
| 包管理 | 后端 `uv` · 前端 `npm` |

---

## 快速开始

前置：Docker Desktop 已启动、`uv` 与 Node 20+ 可用。

```bash
# 1. 起数据库（pgvector/pg16，宿主端口 5433）
docker compose up -d

# 2. 后端依赖 + 建表
cd backend && uv sync && uv run alembic upgrade head

# 3. 起后端（http://127.0.0.1:8000）
uv run uvicorn app.main:app --reload --port 8000

# 4. 起前端（http://localhost:5173）
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
    agent/    图、节点、状态、prompt（P2 起）
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
| P1 | 数据、检索与只读 API | 待开始 |
| P2 | 对话主链路（SSE + 多轮） | 待开始 |
| P3 | 业务闭环（工具 / 订单 / 售后） | 待开始 |
| P4 | 质量、安全与可观测 | 待开始 |
| P5 | 体验与交付 | 待开始 |

---

## 常见问题

| 现象 | 处理 |
|---|---|
| `/health` 返回 503 且 `db: down` | Docker 未启动或端口不是 5433：`docker compose ps` 后 `docker compose up -d` |
| `vector: missing` | 库是旧卷且未跑 init 脚本：`docker compose exec db psql -U app -d ecom -c "CREATE EXTENSION vector"` |
| `alembic` 报 `UnicodeDecodeError: 'gbk'` | `alembic.ini` 必须保持纯 ASCII（Windows 用系统 locale 读 ini） |
| 前端 502 / 打不开 | 用 `localhost:5173`；Vite 默认不监听 IPv4 回环 |
| `uv sync` 很慢 | 配置国内 PyPI 镜像（`UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple`） |
