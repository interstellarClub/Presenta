# AI 演示文稿生产平台

> 文档进，演示文稿出。支持就地编辑、连续可调动效、全格式导出，溯源真实性由架构保证。
> 技术栈：Python + FastAPI · React + TypeScript · PostgreSQL · Redis · DeepSeek `deepseek-flash`
> 详细的产品定义、架构、数据模型、排期与风险见 **`AI演示文稿生产平台_项目书.pdf`**；AI 编码约束见 **`AGENTS.md`**。

---

## 目录

- [一、它能做什么](#一它能做什么)
- [二、系统架构一览](#二系统架构一览)
- [三、目录结构](#三目录结构)
- [四、本地开发（Docker Compose）](#四本地开发docker-compose)
- [五、本地开发（不用 Docker）](#五本地开发不用-docker)
- [六、环境变量](#六环境变量)
- [七、常用命令](#七常用命令)
- [八、API 概览](#八api-概览)
- [九、M1 验收标准](#九m1-验收标准)
- [十、开发须知（必读）](#十开发须知必读)

---

## 一、它能做什么

| 能力 | 说明 |
|---|---|
| 文档解析 | Markdown / Word(.docx) / 内置 Markdown 编辑器；Word 统一归一化为 Markdown，保留字符级来源定位 |
| 大纲生成 | 章节树 → 分块摘要 → 大纲（SSE 流式），**用户确认后**才逐页生成 |
| 逐页生成 | 每页单独调用模型，只输出「版式 ID + 插槽内容」，Pydantic 强校验，失败修复 ≤2 次，仍失败降级为纯文本页 |
| 就地编辑 | 点击元素 → 右侧面板修改 → 提交 JSON Patch → 局部重渲染；支持拖拽（12 列栅格）、样式微调、撤销重做 |
| 动效 | `motionLevel 0–1` 强度滑块 + fragment 点击步进；所有组件实现 `seek(t)` |
| 导出 | PDF、PPTX（服务端）；MP4（客户端 WebCodecs）；GIF（服务端）；单文件独立 HTML |
| 主题 | 6 套内置 + 用户模板包（按规范上传，只能填插槽改 Token） |
| 分享 | 密码 + 有效期，访客可下载全部格式 |
| 版本历史 | 全量 JSON Patch 链，每 20 版全量锚点，里程碑可回退、可 diff |

**当前实现状态**：M1–M7 的主要代码路径已铺齐，包括结构化生成、编辑、动效、全格式导出、分享、模板包与观测。

> **仓库实现状态（与本 README 的排期不完全同步，以此表为准）**
>
> 已实现：
> - 账号与准入：邮箱密码 + 邀请码注册、会话 Cookie、邀请码 CLI（生成 / 吊销 / 查询用量）
> - 文档：`.docx` / `.md` 上传、归一化 Markdown、字符级章节锚点、资产抽取（图片 / 表格；OMML 经 pandoc，失败降级并标注）
> - 大纲：SSE 分阶段推送（摘要 → 规划 → 逐项），确认后才创建 Deck
> - 逐页生成：`mock` / `deepseek` 双 provider，Pydantic 校验 + 修复 ≤2 + 失败降级纯文本页（`degraded`），任务状态含 `partial`
> - 编辑：14 种版式渲染于 iframe 沙箱，点击选中、12 列拖拽、图片替换、受控富文本、JSON Patch 与乐观刷新
> - 自然语言编辑：模型生成 JSON Patch 预览，用户确认后应用
> - 动效：motionLevel、fragment 步进、6 类受控组件与统一 seek(t)
> - 版本：Patch 链 + 每 20 版锚点 + 里程碑；列表 / 按 seq 回放 / 回滚 / diff
> - 主题：6 套内置 Token + WCAG；支持上传 Token/版式模板包并执行静态安全检查
> - 导出：独立 HTML（资源内联）、PDF / GIF / PPTX（服务端 `render-svc`；未启动 render-svc 时明确报错，不静默降级）
> - MP4：客户端 WebCodecs 逐帧编码 + MP4 封装；分享页支持由访客本地生成
> - 分享：密码 + 有效期 + 下载格式白名单 + 访问日志 + 吊销；访客只读播放
> - 清理：过期导出物 / 回收站 Deck / 过期分享 / 30 日访问日志（`app.cli.cleanup` 或 arq cron）
> - 观测：`usage_ledger` 逐次计量、`audit_logs` 关键动作（永不删除）
>
> 剩余生产化事项：
> - 字体子集分发与字形覆盖校验（当前导出使用系统字体；生产需接入统一字体包）

---

## 二、系统架构一览

```
浏览器 (React + Vite)
 ├ 文稿区 Monaco ←→ 大纲树 ←→ 画布（逐页 iframe 沙箱） ←→ 检查器
 └ 导出：MP4 在客户端（WebCodecs + ffmpeg.wasm）

FastAPI（无状态，可水平扩容）
 ├ 解析：markdown-it-py / python-docx / pandoc(OMML→LaTeX)
 ├ 生成：llm/gateway → DeepSeek（重试 · 限流 · 计量 · JSON Mode）
 ├ 版本：JSON Patch + 锚点
 └ 任务：Redis 队列 + ARQ worker（心跳/ reclaim/ 幂等）

render-svc（唯一 Chromium 容器）
 └ PDF · PPTX · GIF

PostgreSQL + 对象存储（MinIO / OBS）
 └ 7 日生命周期：导出物、回收站文稿、过期分享
```

**一条铁律**：编辑器、PDF、GIF 必须使用**同一份字体子集**，版本号写在 `themes.manifest` 里；不一致时导出直接报错，不静默出图。

---

## 三、目录结构

```
backend/
  app/
    main.py
    core/        config.py security.py deps.py errors.py ratelimit.py
    db/          engine.py models.py session.py migrations/
    api/
      routers/   auth.py documents.py decks.py outline.py pages.py
                 patch.py themes.py shares.py exports.py jobs.py
      schemas/   pydantic v2 模型（含 14 种版式插槽定义）
    services/
      ingest/    markdown.py docx.py omml.py normalize.py assets.py anchor.py
      deck/      schema.py versioning.py patch_apply.py render_payload.py
      outline/   generator.py prompts/outline.md
      pages/     generator.py layout_picker.py validator.py repair.py prompts/page.md
      intent/    nl_to_patch.py            # M6
      theme/     manifest.py validator.py package.py
      share/     token.py guard.py
      export/    pdf.py pptx_inject.py gif.py
      llm/       gateway.py retry.py metering.py json_guard.py
    workers/     arq_settings.py heartbeat.py
                 tasks/ ingest.py batch_generate.py pdf_export.py ppt_export.py cleanup.py
    templates/   layouts/  themes/  motion/
    cli/         invite.py                # 邀请码：生成/吊销/查用量
web/
  src/
    editor/      MonacoHost.tsx anchorMap.ts
    outline/     TreeEditor.tsx
    canvas/      SlideFrame.tsx bridge.ts selection.ts dragGrid.ts
    inspector/   ContentPanel.tsx StylePanel.tsx MotionPanel.tsx MotionSlider.tsx
    export/      webcodecs/ gif/ pptx/ html/standalone.ts ffmpeg-loader.ts
    player/      RevealHost.tsx presenter.tsx
    share/       GuestViewer.tsx PasswordGate.tsx DownloadCenter.tsx
    themes/      token.ts fontStack.ts
infra/
  docker-compose.yml  Dockerfile.api  Dockerfile.render  nginx.conf
```

---

## 四、本地开发（Docker Compose）

```bash
# 1. 克隆后复制环境变量
cp .env.example .env      # 填入 DEEPSEEK_API_KEY（平台 Key，不要提交）

# 2. 一键启动：api / web / postgres / redis / minio / render-svc
docker compose -f infra/docker-compose.yml up -d --build

# 3. 初始化数据库
docker compose exec api alembic upgrade head

# 4. 创建第一个邀请码（注册必需）
docker compose exec api python -m app.cli.invite create --label "first-user" --uses 1

# 5. 打开
open http://localhost:5173
```

服务端口：web `5173` · api `8000` · postgres `5432` · redis `6379` · minio `9000`。

---

## 五、本地开发（不用 Docker）

### 最简模式（SQLite + 本地队列 + mock 模型，零外部依赖）

```bash
cp .env.example .env                  # LLM_PROVIDER=mock / QUEUE_BACKEND=local / STORAGE_BACKEND=local
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head                  # 或直接启动，dev 模式会自动建表
python -m app.cli.invite create --label dev --uses 5
uvicorn app.main:app --reload --port 8000

# 另一个终端
cd web && npm install && npm run dev  # http://localhost:5173
```

- `mock` 提供确定性大纲 / 页面（不联网），并在 `usage_ledger` 中标记 provider=mock。
- **接真实模型**：编辑 `.env`，设 `LLM_PROVIDER=deepseek` 并填入 `DEEPSEEK_API_KEY`（平台 Key，仅服务端可读，不要提交到仓库）。启动时若 Key 缺失、为占位值或过短，lifespan 会直接失败退出，不会静默降级到 mock。
- 验收流程：`pytest -q`（默认跳过 `@pytest.mark.deepseek` 标记的真实调用测试）；配好真实 Key 后跑 `pytest -m deepseek -q` 验证真实计量与降级；`PYTHONPATH=. python scripts/smoke_deepseek.py` 做端到端冒烟。
- PDF / GIF / PPTX 需要 `render-svc`：`cd render_svc && pip install -r requirements.txt && playwright install chromium && uvicorn app:app --port 8100`。未启动时导出接口会返回明确错误。
- 端到端冒烟脚本：`cd backend && PYTHONPATH=. python scripts/smoke_pipeline.py`（注册 → 解析 → 大纲 → 生成 → 四种导出 → 分享）。

### 完整模式（本机 PostgreSQL / Redis / MinIO / pandoc）

需要本机准备：**Python 3.12+、Node 20+、PostgreSQL 16、Redis 7、pandoc**。
渲染服务（PDF/GIF/PPTX）需要 Chromium + FFmpeg，建议即使前端后端本地跑，`render-svc` 也用容器启动。

```bash
# 后端
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Worker（另一个终端）
arq app.workers.arq_settings.WorkerSettings

# 前端
cd web
npm install
npm run dev
```

---

## 六、环境变量

复制 `.env.example`，关键项：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql+asyncpg://app:app@localhost:5432/app` |
| `REDIS_URL` | Redis | `redis://localhost:6379/0` |
| `S3_ENDPOINT` / `S3_BUCKET` / `S3_KEY` / `S3_SECRET` | 对象存储 | MinIO 本地默认值 |
| `DEEPSEEK_API_KEY` | **平台统一持有的 Key，仅服务端可读** | 必填 |
| `DEEPSEEK_BASE_URL` | 官方地址 | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 模型别名 | `deepseek-flash` |
| `DEEPSEEK_THINKING` | V4 系列默认开启思考 | `true` |
| `PANDOC_PATH` | OMML→LaTeX 用 | `pandoc` |
| `RENDER_SVC_URL` | 渲染服务地址 | `http://render-svc:8100` |
| `SESSION_TTL_HOURS` | 会话有效期 | `168` |
| `SHARE_DEFAULT_TTL_HOURS` | 分享链接默认有效期 | `72` |
| `PURGE_RETENTION_DAYS` | 回收站 / 导出物留存 | `7` |
| `INGEST_TIMEOUT_S` | 解析任务超时 | `120` |
| `BATCH_CONCURRENCY_PER_USER` | 单用户模型调用并发上限（**是护栏，不是配额**） | `3` |
| `MAX_UPLOAD_MB` | 上传上限 | `50` |

> ⚠️ 前端**永远拿不到** `DEEPSEEK_API_KEY`。所有模型调用走后端 `/api/...`。

---

## 七、常用命令

```bash
# 邀请码
python -m app.cli.invite create --label "xxx" --uses 5 --ttl-days 30
python -m app.cli.invite list
python -m app.cli.invite revoke <code>

# 数据库
alembic revision --autogenerate -m "xxx"
alembic upgrade head

# 测试与检查
pytest -q
ruff check app
mypy app
cd web && npm run lint && npm run typecheck
```

---

## 八、API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/register` | 邮箱 + 密码 + 邀请码 |
| POST | `/api/auth/login` · `/logout` | 会话 |
| POST | `/api/documents` | 上传 .docx / .md，返回 `document_id`，异步解析 |
| GET | `/api/documents/{id}` | 状态、章节树、资产表 |
| POST | `/api/documents/{id}/outline` | SSE 流式生成大纲 |
| POST | `/api/decks` `GET /api/decks/{id}` | 创建 / 读取 deck（含 slides） |
| POST | `/api/decks/{id}/generate` | 确认大纲后逐页生成（job） |
| PATCH | `/api/decks/{id}` | 提交 JSON Patch（编辑回写） |
| GET | `/api/decks/{id}/versions` · `POST .../rollback/{version_id}` | 版本历史 / 回退 |
| POST | `/api/decks/{id}/shares` | 创建分享（密码 + 有效期） |
| GET | `/s/{slug}` | 访客入口（密码门 → 只读播放） |
| POST | `/api/exports` · GET `/api/jobs/{id}`(SSE) | 发起导出 / 进度 |
| GET | `/api/themes` · POST `/api/themes` | 主题列表 / 上传模板包 |

---

## 九、M1 验收标准

一条命令跑通，拿一份真实 Word 文档：

1. 注册（邀请码）→ 登录
2. 上传 `.docx` → 状态变为 `ready`，`normalized_md` 可在编辑器中看到，图片进入资产表且有 `sourceRef`
3. 大纲 SSE 流式出现，可拖拽编辑，**确认后**逐页生成
4. 40 页左右 deck 全部生成；故意失败页降级为纯文本页并标 `degraded`
5. 画布可点选元素、提交 Patch、刷新后改动仍在
6. `deck_versions` 中能看到 autosave / milestone / anchor 三类版本
7. 中英混排：无标点悬挂、中英文间有间距、无字体替换告警

M1 **不含**：动效播放、任何导出、分享、模板包、自然语言编辑。

---

## 十、开发须知（必读）

1. **Schema 是唯一真相**：HTML 永远由 Schema 渲染，禁止写「HTML → Schema」的反向解析。
2. **禁止 AI 生图**：图片插槽只接受 `asset_id`。不得引入任何文生图依赖。
3. **禁止开放用户 JS**：动效只从内置受控组件库选；新组件必须实现 `render / seek(t) / duration`。
4. **降级必须告知**：任何格式降级都要在 UI 上说明，禁止静默降级。
5. **数值必须核对原文**：图表数据写入前与 `sourceRef` 原文逐字符串比对。
6. **API Key 只在服务端**：前端、日志、错误信息里都不得出现。
7. **提交前**：`ruff` + `mypy` + `pytest` + 前端 `typecheck` 全绿；涉及版式 Schema 的改动必须补 fixture 测试。

更多「不许做什么」见 **`AGENTS.md`**。
