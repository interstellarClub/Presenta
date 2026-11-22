# AGENTS.md — AI 编码代理约束

> 本文件面向在本仓库中写代码的 AI 代理（以及人）。**先读 `README.md` 与 `项目书 PDF` 再动手。**
> 规则分三级：**🚫 红线**（违反即回滚提交）· **⚠️ 必须**（违反需说明原因）· **💡 建议**（可权衡）。
> 遇到本文件未覆盖的需求歧义：**停下来问，不要猜。**

---

## 0. 项目一句话

文档（Markdown / Word）→ AI 大纲 → 逐页生成结构化演示文稿 → 元素级就地编辑 → 导出 PDF / PPTX / MP4 / GIF / 单文件 HTML。
模型：DeepSeek `deepseek-flash`（平台 Key，仅服务端）。阶段：**M1**。

---

## 1. 🚫 红线（绝不可做）

1. **不得引入 AI 生图**：不装文生图 SDK、不调外部生图 API、不给学生成图片的字段。图片只允许来自 `doc_assets`（`asset_id`）。
2. **不得开放用户自定义 JS**：不执行用户上传的脚本；`eval` / `new Function` / `dangerouslySetInnerHTML`（未过滤）一律禁止。动效只用 `templates/motion/` 下的内置组件。
3. **不得把 Schema 反向解析出来**：编辑 = 对 Schema 打 JSON Patch。禁止「读取 DOM → 反推结构 → 覆盖后端数据」这条路径。
4. **不得把 `DEEPSEEK_API_KEY` 送到前端**：不写进 `VITE_*` 变量、不进日志、不进错误响应。
5. **不得静默降级**：导出时任何无法保真的部分必须在响应与 UI 上标注（如 `degraded: true`、GIF 化页面清单）。
6. **不得编造数据**：图表数值必须来自原文且通过逐字符串校验；校验不过 → 拒绝入库并触发修复，不得「差不多就放行」。
7. **不得绕过 Pydantic 校验直接写库**：包括 migration 脚本里手工塞「看起来合理」的示例内容。
8. **不得在渲染容器中联网**：渲染用户内容时 Chromium 必须 `--no-remote`-级断网（阻断所有非 `data:` /本地请求），防止外链追踪与 SSRF。
9. **不得自动提交数据库不可逆操作**：`drop` / `truncate` / 批量物理删除必须人工确认；7 日清理只走 `cleanup` 任务。

---

## 2. ⚠️ 必须遵守

### 2.1 数据与 Schema
- 新增内容字段 → 先改 `api/schemas/`（Pydantic）与 `db/models.py`，再写 alembic 迁移，**禁止只改一处**。
- Schema 变更必须向后兼容：旧版本 snapshot 要能回放（`versioning.py`），不兼容变更需写迁移函数 + 测试。
- `Slide.layout` 只读：不得提供任何修改 layout 的 API。
- 所有 `image` 插槽类型只允许 `asset_id`；所有 `source` 必填插槽不允许空字符串。
- 版本写入：**每次确认级操作**生成 version；`seq % 20 == 0` 或 milestone 时额外写全量 snapshot。

### 2.2 模型调用
- 所有 DeepSeek 调用走 `services/llm/gateway.py`；业务代码里 **不 import 任何 LLM SDK**。
- 结构化输出：`response_format={"type":"json_object"}` + Pydantic 校验 + 失败把校验错误回喂重试，**最多 2 次**；仍失败 → 降级纯文本页 + `degraded` 标记，不得让整批任务失败。
- 每次调用都要写 `usage_ledger`（token、是否思考、耗时、成败）。
- 大纲/逐页用思考模式；意图识别、文案微调用 `extra_body={"thinking":{"type":"disabled"}}`。
- 提示词放在 `services/*/prompts/*.md`，**不内联在 .py 里**；修改提示词要记录变更原因。

### 2.3 任务与异步
- 新任务类型必须在 `jobs.kind` 登记、指定超时与**幂等键**，并实现心跳（15s 一次）。
- 长任务按页/按元素推进 `progress`；含动效页数 >20 必须逐页更新。
- 任务可取消：在页边界检查取消标志，保证中断点一致。
- worker 崩溃 reclaim 由巡检负责，**不要在任务内部自己 `try/except` 后标记 succeeded**。

### 2.4 前端
- 画布每页一个 iframe；样式不得泄漏出 iframe，不得用全局 CSS 覆盖主题 Token。
- 微调写入 `styleOverride`，**不得修改主题 Token 本身**。
- 编辑提交用 JSON Patch，不做整 Slide 覆盖（避免并发覆盖他人改动）。
- 中英混排用 `themes/fontStack.ts` 与项目书第 05 章规则：中文基准字号 = 西文 ×1.03；`text-autospace`；`line-break: strict`；**中文严禁 `word-break: break-all`**。
- 字体文件只从约定对象存储路径加载，引用 `themes.manifest` 中的字体版本号；版本不匹配 → 报错，不 fallback 静默渲染。

### 2.5 动效组件
- 新组件必须实现 `render / seek(t) / duration()`，`seek` 为**纯函数**（同一 t 同一画面，禁止依赖 `Date.now()`）；PDF 关键帧可选实现 `keyframe()`。
- 动效参数必须乘 `MotionBudget`；硬编码时长/位移视为 bug。
- 组件不得发起网络请求、不得访问 `localStorage`、不得读取用户文档原文之外的任何数据。

### 2.6 导出
- PDF 只走服务端 `render-svc`，**禁止用浏览器 `window.print()`**。
- PPTX：转场只用白名单（fade / push / wipe / 覆盖 / zoom）；不要用 python-pptx 手搓 `p:timing` 元素动画树，元素动效一律 GIF 插入（参见项目书 R1）。
- GIF：PNG 序列 → FFmpeg 双遍调色板（`palettegen=stats_mode=diff` + `dither=sierra2_4a`）；深色主题自动换浅底。
- MP4：逐帧 `seek(t)` 截图喂 WebCodecs，**禁止 `MediaRecorder` / `captureStream` 录屏**。
- 视频导出后跑空帧自检（64×36 逐帧标准差，连续 0.3s 近纯色报警）。
- 导出产物写 `export_artifacts`，带 `schema_hash`；同版本重导优先命中缓存。

### 2.7 安全
- 密码：argon2id；邀请码：HMAC-SHA256 加盐；分享 token：随机 256bit，只存哈希。
- 上传：后缀白名单 + MIME 校验 + 大小上限 + 解压炸弹防护（zip/tar 展开比）。
- SQL 一律参数化；对象存储 key 不许用用户原文命名（用 uuid + 白名单后缀）。
- 模板包：静态扫描（禁止 `eval`、网络 API、`child_process`、动态 import）+ 渲染断网沙箱。
- 日志不记录：密码、token、API Key、邀请码明文、文档全文。

### 2.8 留存
- 分享过期：由 `expires_at` 判定，不另起定时器；访问日志 30 日。
- 回收站与导出物：7 日后由 `cleanup` 任务物理删除（先对象存储、后数据库记录）。
- 审计日志与用量账本：**永不删除**。

---

## 3. 💡 建议

- 一个功能一个 PR；PR 描述里写明对应项目书章节（如「见项目书 09 动效系统」）。
- 版式组件与模板：一个版式一个文件，模板 JSX 里不写业务逻辑。
- 提示词改动附 3 份样例文档的生成结果对比（截图或 JSON diff）。
- 错误提示对用户说人话，技术细节写进 `error` 字段与日志。
- 命名：后端 snake_case，前端 camelCase，Schema 字段 camelCase（与 JSON 一致）。

---

## 4. 禁止的「聪明」行为

| 诱惑 | 为什么不行 |
|---|---|
| 「先把 HTML 生成出来，以后再抽结构」 | Schema 就再也抽不出来了，编辑/版本/导出全部失效 |
| 「动效直接用 CSS 动画，seek 以后再补」 | 没有 seek 就没有确定性导出，视频/GIF/ PDF 全部重做 |
| 「PPT 动画我手工拼 XML 就行」 | PowerPoint 静默丢动画甚至报文件损坏（项目书 R1） |
| 「用户上传的 JS 加个 sandbox 应该没事」 | 导出渲染、SSR、字体加载三处都会逃逸；红线 |
| 「配额以后再加，先让用户随便用」 | 平台出 Key + 无配额 = 一晚被刷穿（项目书 R6） |
| 「字体差不多，用系统字体就行」 | 「浏览器 3 行、PDF 4 行」是本项目最高频事故（项目书 R3） |
| 「这个降级用户不会注意到的」 | 会，而且会带着成品去客户现场才发现 |

---

## 5. 不确定时怎么办

1. 查 `项目书 PDF` 对应章节（第 04 章列了全部决策及其代价）。
2. 查本文件第 1、2 节。
3. 仍不清楚 → **在 PR/任务里提问**，列出你看到的两三种做法及各自代价，**不要自行选一个先写上**。

---

## 6. 提交前检查清单

- [ ] `ruff check app && mypy app && pytest -q`
- [ ] `cd web && npm run typecheck && npm run lint`
- [ ] Schema 改动：迁移可升可降，旧版本 snapshot 回放测试通过
- [ ] 新模型调用：写了 `usage_ledger`，走 gateway
- [ ] 新任务：有幂等键、心跳、超时、取消点
- [ ] 新动效组件：实现了 `seek(t)` 且不使用真实时钟
- [ ] 导出改动：降级信息已透出到 UI
- [ ] 无 🚫 红线项、日志无敏感信息
