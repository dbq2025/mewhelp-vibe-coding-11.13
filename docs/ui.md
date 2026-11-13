# UI 规范（v1.0 · P5）

> 这份文档是「改界面时先看这里」的单一来源。约定：**组件里不出现色值，只出现语义令牌**；
> 要换主题/换品牌色，只改 `frontend/src/styles/main.css` 的 `:root` 变量。

---

## 1. 颜色令牌

| 令牌 | Tailwind 类 | 值 | 用途 |
|---|---|---|---|
| `--c-canvas` | `bg-canvas` | `#f6f7f9` | 页面底色、被嵌套的浅色块 |
| `--c-surface` | `bg-surface` | `#ffffff` | 卡片、侧栏、输入区底 |
| `--c-line` | `border-line` / `bg-line` | `#e4e7ec` | 分隔线、边框、骨架屏占位 |
| `--c-ink` | `text-ink` | `#101828` | 主文字 |
| `--c-muted` | `text-muted` | `#667085` | 次要文字、元信息（时间、意图标签） |
| `--c-brand` | `bg-brand` / `text-brand` | `#1f6feb` | 主操作、选中态、引用编号 |
| `--c-brand-ink` | `text-brand-ink` | `#ffffff` | 主色块上的文字 |
| `--c-brand-soft` | `bg-brand-soft` | `#e8f0fe` | 选中底色、待确认卡片底 |
| `--c-ok` | `text-ok` | `#12a150` | 成功、工具调用成功、服务正常 |
| `--c-warn` | `text-warn` | `#c2740b` | 未完成、不可受理、降级 |
| `--c-danger` | `text-danger` | `#d92d20` | 错误、拦截、停止 |

**语义映射（不许混用）**

| 场景 | 用色 |
|---|---|
| 售后「待确认」 | `brand`（可操作，不是成功也不是错误） |
| 售后「已建单」 | `ok` |
| 售后「不可受理」 | `warn`（是业务判定，不是系统故障） |
| 限流 429 / 网络失败 / 注入拦截 | `danger` |
| 流式中断、历史卡片只读 | `warn` + 灰色说明 |

> 状态色不表达「涨跌」，本项目不涉及行情，因此不遵循红涨绿跌。

---

## 2. 字号与行高

| 用途 | 类 | 说明 |
|---|---|---|
| 页面标题 | `text-lg font-semibold` | 只出现在欢迎页 |
| 区块标题 | `text-sm font-semibold` | 顶栏、侧栏品牌名 |
| 正文 | `text-sm leading-relaxed` | 消息正文，桌面 14px |
| 输入框 | `text-base sm:text-sm` | **移动端必须 16px**，否则 iOS Safari 聚焦时自动放大页面 |
| 元信息 | `text-xs` / `text-[11px]` | 意图标签、耗时、引用标题、工具轨迹 |
| 等宽 | `font-mono` | 订单号、工单号（避免 O/0 混淆） |

行高统一 `leading-relaxed`；正文不使用 `text-justify`（中文两端对齐在窄屏会拉出字间距）。

---

## 3. 间距与布局

- 内容列宽上限 `max-w-chat` = `48rem`（768px），居中；超出后不再拉宽，保持可读行长。
- 页面横向内边距：移动端 `px-3`，`sm` 起 `px-5`。
- 消息块间距 `space-y-6`；卡片内部 `px-3 py-2.5`；标签与正文之间 `mb-1`。
- 圆角：卡片 `rounded-xl`，按钮/输入 `rounded-lg`，标签 `rounded`/`rounded-full`（建议 chip）。
- 边框一律 `1px solid var(--c-line)`；不用阴影分层（除移动端抽屉 `shadow-xl`）。
- 三段式纵向结构：`header`（h-14，固定）→ 消息区（`flex-1 min-h-0 overflow-y-auto`）→ 输入区（固定）。
  **`min-h-0` 不能省**，否则 flex 子项不会收缩，滚动条不出现。

---

## 4. 移动端（≤767px）

| 规则 | 实现 |
|---|---|
| 侧栏改为抽屉 | `fixed inset-y-0 left-0 z-40 w-72` + `-translate-x-full`，`md:static md:translate-x-0` |
| 打开抽屉时锁背景滚动 | `watch(sidebarOpen)` 写 `document.body.style.overflow` |
| 抽屉入口 | 顶栏左侧汉堡按钮（`md:hidden`），`aria-label="打开会话列表"` |
| 高度跟随可视视口 | `#app { height: 100dvh }`（`@supports` 包裹，旧浏览器回落 `100%`），软键盘弹出时输入框仍在视口内 |
| 底部安全区 | 输入区 `.pb-safe` = `max(0.75rem, env(safe-area-inset-bottom))`；`index.html` 需 `viewport-fit=cover` |
| 触屏命中区 | `@media (pointer: coarse) button { min-height: 2.5rem }` |
| 删除会话按钮 | 触屏无 hover：移动端常显，桌面端 `md:group-hover:block` |
| 横向溢出 | 正文 `break-words`，长单号不撑破容器；验收标准 `scrollWidth === clientWidth` |

**375px 验收**：无横向滚动、侧栏默认隐藏、输入框完整可见、卡片按钮可点（实测数据见 §7）。

---

## 5. 组件状态清单

| 组件 | 状态 | 视觉 |
|---|---|---|
| 会话列表 | 加载中 | 6 条 `h-3.5` 灰色骨架条，宽度 2/3 与全宽交替 |
| 会话列表 | 空 | 两行灰字「还没有会话记录 / 发第一条消息就会自动保存」 |
| 消息区 | 历史加载中 | 2 组「标签条 + 正文条」骨架；**URL 有会话 id 时不得先闪欢迎页** |
| 消息区 | 空会话 | EC 徽标 + 「有什么可以帮你？」+ 3 个建议 chip |
| 消息区 | 流式生成中 | 正文末尾打字光标 `.caret`（伪元素，不进复制文本）；工具执行时另显示脉动圆点 + 动作名 |
| 消息区 | 中断/未完成 | 标题行 `warn` 徽标「未完成」+「重试本条」按钮 |
| 消息区 | 已拦截 | 标题行 `danger` 徽标「已拦截」 |
| 售后卡片 | 待确认 | `brand` 边框 + 「确认提交 / 先不申请」两按钮 |
| 售后卡片 | 历史（非最后一轮） | 同色系但按钮变灰字说明「历史记录，如需办理请重新发起」 |
| 售后卡片 | 建单成功 | `ok` 边框 + ✓ + 等宽工单号 + 状态 |
| 售后卡片 | 不可受理 | `warn` 边框 + 原因 |
| 引用卡片 | 收起 | `[n]` 主色徽标 + 标题 + 「展开」 |
| 引用卡片 | 展开 | 原文片段，`border-t` 分隔，最长 `max-w-md` |
| 错误条 | 有错误 | `danger/5` 底色 + 消息 + 「重试本条」（仅未完成时）+「忽略」 |
| 输入框 | 可发送 / 空 | 主色实心 / 灰底禁用 |
| 输入框 | 生成中 | 发送键换成「停止」 |

---

## 6. 无障碍与体验细节

- 所有图标按钮必须有 `aria-label`；健康状态用 `role="status"`，错误条用 `role="alert"`。
- 骨架屏容器 `aria-busy="true"`，占位块 `aria-hidden="true"`（读屏不念空块）。
- `prefers-reduced-motion: reduce` 下关闭闪烁与过渡动画，光标保持常亮。
- Enter 发送 / Shift+Enter 换行；输入法组合中（`isComposing`）不触发发送。
- 焦点可见：输入框 `focus-within:border-brand`；不主动 `outline: none` 到不可见的程度（textarea 用容器边框承担焦点提示）。

---

## 7. 实测验收记录（2026-11-13，Playwright + 本机 Chrome 无头）

| 检查 | 方法 | 结果 |
|---|---|---|
| 375×812 无横向溢出 | `documentElement.scrollWidth` vs `clientWidth` | 375 / 375，越界元素 0 个 |
| 侧栏默认隐藏 | `aside.getBoundingClientRect().right <= 1` | true |
| 抽屉可开合 | 点汉堡 → 截图 → 点遮罩 → 复测 rect | 打开 left=0、宽 288；关闭 right≤1 |
| 输入框在视口内 | `textarea.boundingBox()` | y=740.5，高 26，底 766.5 < 812 |
| 软键盘（视口压到 375×420） | `setViewportSize` 后复测 | 输入框 y=348.5，底 374.5 < 420，未被顶出 |
| 触屏按钮命中区 | `boundingBox` of 「确认提交」 | 高 40px（≥40 达标） |
| 打字光标 | 流式截图 | 正文末尾可见方块光标 |
| 骨架屏 | 接口延迟 1.8s / 6s | 侧栏 6 条、消息区 5 块占位，无欢迎页闪现 |
| 引用卡展开 | 点「运费规则」 | 展开出原文片段，`[1]` 徽标与正文编号一致 |
| 错误条 + 重试 | 把 `/chat/stream` 打回 429 | 提示「请求太频繁了，12 秒后再试一次」+「重试本条」；点「忽略」后 `role=alert` 数量归 0 |

> 截图见 `.tmp/vis/`（本地临时目录，不入库）。

---

## 8. 改动界面时的自检

1. 新增颜色？先加令牌，再在组件里用语义类 —— 禁止 `text-[#d92d20]`。
2. 新增状态？在上表补一行，并确认移动端 375px 下不溢出。
3. 新增按钮？`pointer: coarse` 下高度 ≥40px，图标按钮带 `aria-label`。
4. 新增异步加载？必须有骨架屏，且「有 id 但未到数据」不能渲染空状态。
5. 改完跑 `npm run lint && npm run test && npm run build`。
