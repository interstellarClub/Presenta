# Presenta 第二轮验收整改清单

> 基线：`README.md`、项目书 PDF、`AGENTS.md`、`todolist1.md`、本轮更新后的代码与测试。
>
> 结论：本轮修复关闭了若干关键安全问题，但整体验收仍不通过。存在一个新的版本链分支回归，以及导出保真、字体、任务治理、长文档、清理和前端功能等未修复项。

## 本轮复核结果

### 已通过的检查

- [x] 后端测试从 24 项增加到 40 项，当前全部通过。
- [x] `ruff check app tests` 通过。
- [x] `mypy app` 通过。
- [x] 前端 `typecheck`、`lint`、生产构建通过。
- [x] Alembic `upgrade -> downgrade -> upgrade` 通过，包含新增 share token 迁移。
- [x] mock 端到端冒烟流程通过。

### 本轮已实质修复

- [x] Patch 阶段开始执行 Deck 语义校验。
- [x] 图表数值从无边界子串匹配改为数字 token 匹配，`1` 不再直接匹配 `2021`，`12` 不再直接匹配 `12.4`。
- [x] 校验 `Provenance.documentId` 必须与关联文档一致。
- [x] 校验 `sourceRef` 行范围存在，quote 必须位于对应行区间。
- [x] 写入和导出时校验图片 `assetId` 是否属于当前文档。
- [x] 禁止直接 Patch `/id`、`/schemaVersion`、`/meta/sourceDocumentId`、slide id 和 layout。
- [x] 禁止通过 Patch 删除整页、清空 slides 或追加页面。
- [x] 错误登录审计改为独立事务，提交后不再被失败请求回滚。
- [x] 分享 token 改为随机 256 bit 凭证，数据库只保存 SHA-256 哈希。
- [x] 分享密码提高到至少 8 位并要求字母和数字。
- [x] 分享解锁增加尝试限流，Redis 限流故障改为 fail-closed。
- [x] MP4 在分享创建阶段显式拒绝，不再允许创建后下载失败。
- [x] 分享文件下载会再次检查 artifact 格式白名单。
- [x] 吊销分享时会吊销关联的 ShareToken。
- [x] 回退改为移动 `current_version_seq`，支持回退到当前最大版本位置。
- [x] 版本列表 API 增加 `limit` 和 `offset`。
- [x] 生产模式启动时拒绝开发 SECRET_KEY、不安全 Cookie 和未显式允许的 mock provider。

## P0 - 当前阻断项

### 版本链回退分支

- [ ] **修复回退后继续编辑会重新带入已放弃分支改动的问题。**

  当前回退只把 `current_version_seq` 指向旧版本，但后续新版本仍使用全局最大 `seq + 1`，parent 也指向最大 seq。实测：

  1. 初始生成版本为 v2。
  2. 在 v2 基础上添加元素 `old`，产生 v3。
  3. 回退到 v2，确认返回的 Deck 中没有 `old`。
  4. 在 v2 基础上添加元素 `new`，生成 v4。
  5. 加载 v4 时元素变为 `["old", "new"]`，已放弃分支被重新应用。

- [ ] 新版本必须基于当前版本形成独立父子链，不能在回放时混入旧分支 patch。
- [ ] `load_deck_at()` 需要按 parent 链回放，或回退后截断/标记废弃的后继版本。
- [ ] 明确“回退后继续编辑”是创建新分支还是覆盖旧分支，并在 UI 中显示分支关系。
- [ ] 修复后增加“回退 -> 编辑 -> 再打开 -> 再回退”的端到端测试。
- [ ] 修复回退到初始空 Deck（v1）返回 422，但版本时间轴仍允许点击回退的问题。
- [ ] 决定初始空 Deck 是否允许作为活动版本；若不允许，时间轴应禁用该回退按钮或隐藏该版本。
- [ ] 修复回退到已有生成版本后点击“重新生成”时，旧 idempotency key 返回已完成旧 job 的问题。

### 数值与来源绑定

- [ ] **修复同一句由逗号或冒号分隔的多个数据仍可互相冒用的问题。**

  当前 clause 只按分号、句号和换行切分，不按中文逗号、英文逗号或冒号切分。实测：

  - `A 组收入 100 万元，B 组收入 200 万元。`
  - 查询“A 组”时，`100` 和 `200` 都返回匹配成功。
  - 查询“甲指标”时，`10/20/30` 三个值都返回匹配成功。

- [ ] 按中文逗号、英文逗号、顿号、冒号、括号和分号建立完整 clause 边界。
- [ ] 标签与数值必须在同一局部绑定关系中匹配，不能只要同属一个 clause 就接受。
- [ ] 支持同一句包含多个指标时的最近邻或显式表格映射。
- [ ] 增加年份、百分比、负数、括号负数、千分位、区间、单位和小数位测试。
- [ ] 增加案例：`2021 年`、`12.4 亿元`、`8.5%`、`1,234.5 万元`、`-3.1%`。

### 字符级来源定位

- [ ] **校验 `SourceRef.colStart` 和 `colEnd`，当前完全忽略列范围。**

  实测 `colStart=0, colEnd=2` 时，整行 `prefix 2021 收入 12.4 亿元 suffix` 仍被当为有效来源区间，quote 校验也能通过。

- [ ] quote 必须位于 `lineStart/colStart` 到 `lineEnd/colEnd` 的实际字符区间。
- [ ] 明确 `colEnd` 是闭区间还是开区间，并统一 DOCX、Markdown、表格和公式来源定位。
- [ ] 支持跨行 quote，并确保每行首尾位置都被正确校验。
- [ ] 同一页存在多条 provenance 时，不能只使用第一条 provenance 的 region 校验全部图表和表格。
- [ ] 多图表、多来源页面需要建立从 Element/媒体路径到对应 Provenance 的映射。

### 编辑态与导出态

- [ ] 导出 HTML/PDF 仍只读取 `slide.slots`，没有读取 `slide.elements`、`styleOverride` 或 Element layout。
- [ ] 统一编辑画布和导出渲染器，保证字号、颜色、字重、行高、对齐、内距、圆角、阴影、透明度和位置一致。
- [ ] PPTX 仍只生成标题、正文和页脚三个文本框，没有插入图片、图表、表格或 GIF。
- [ ] GIF 仍为每页截一张静态图后重复，没有逐帧 `seek(t)`。
- [ ] GIF 深色主题仍只添加说明，没有实际切换浅底。
- [ ] 导出无法保真的内容必须逐页透出，不能用“256 色”说明代替“动效被丢弃”。
- [ ] 增加编辑态与导出态快照对比测试。

### Theme 与 Schema 完整性

- [ ] 通用 Patch 仍可修改 `/themeId` 为不存在的主题；Pydantic 和语义校验都没有验证主题存在。
- [ ] 非法主题会导致画布回退样式、WCAG 为 null，并在后续导出时报错。
- [ ] Patch `/themeId` 时调用 `load_manifest()`，或将该路径设为只读并要求使用主题切换接口。
- [ ] 校验 Deck 的 `schemaVersion` 与版本迁移器一致。
- [ ] 校验 Deck `id` 与数据库 Deck row id 一致，避免内部调用写错身份。
- [ ] 对 `deck.provenance` 和 `slide.elements[].provenance` 执行与 slide provenance 相同的校验。

## P1 - 数据真实性

- [ ] `source` 插槽仍是普通字符串，没有结构化保存 documentId/sourceRef。
- [ ] 页面只要存在任意一条 provenance，任意 source 文本仍可能通过，需建立 source 与 provenance 的一对一或显式映射。
- [ ] 图表数据应由 `derived` provenance 承载，并必须填写 `originalData`。
- [ ] 当前自动生成的图表 provenance 仍标记为 `original`，不符合“原文数据转图表 = derived”。
- [ ] 关键数字页也应区分 original 和 derived。
- [ ] 图片 provenance 必须校验图片资产自身的 sourceRef，而不仅是 assetId 存在。
- [ ] 表格文本列也必须校验来源，目前只校验表格中的数字 token。
- [ ] external provenance 默认关闭；启用时必须有用户确认、URL、许可证、站点和审计记录。
- [ ] Deck 级 provenance 清单需要与各页 provenance 去重、合并并保持引用关系。
- [ ] 数值修复重试后仍需保证原始数据和 provenance 没有漂移。

## P1 - 分享与安全

- [ ] 错误分享密码现在写入 `audit_logs`，但没有写入项目书要求的 `share_access_logs.auth_fail`。
- [ ] 增加 `share_access_logs.auth_fail` 或同步写入两类日志。
- [ ] 增加错误分享密码日志持久化测试。
- [ ] 增加分享解锁限流测试，确认第 9 次失败返回 429。
- [ ] 明确成功解锁是否计入 8 次限流；当前所有解锁尝试都会计数。
- [ ] ShareToken 过期后没有清理策略；增加清理任务或按 share 级联控制。
- [ ] 浏览器的分享 Cookie 没有 active token 刷新机制，2 小时固定过期。
- [ ] 下载链接仍不是文档要求的独立签名、短时效 URL，而是经过后端 Cookie 校验的代理 URL。
- [ ] 分享下载 PDF/PPTX/GIF 时仍在 HTTP 请求内同步渲染，可能造成慢请求和并发放大。
- [ ] 为分享下载增加按 share+format 的互斥或缓存锁，避免并发重复渲染。
- [ ] `audit_isolated()` 写失败时被吞掉；应增加指标告警，不能只写日志。
- [ ] 限流错误日志中的 Redis key 含原始 IP；统一使用哈希 IP。

## P1 - 任务治理

- [ ] `INGEST_TIMEOUT_S` 仍未用于 ingest 任务。
- [ ] `BATCH_CONCURRENCY_PER_USER` 仍未用于模型调用并发控制。
- [ ] ARQ 仍只有全局 1800 秒 timeout，没有按任务类型的 120/300/900 秒。
- [ ] PDF/GIF/PPTX 导出任务仍没有幂等键。
- [ ] stale reclaim 仍每 15 分钟执行，项目书要求 60 秒。
- [ ] 失败生成任务仍可能因已存在 idempotency key 直接返回旧失败 job。
- [ ] ARQ enqueue 失败仍会静默改为 API 进程内执行任务。
- [ ] 任务领取不是原子操作，重复 enqueue 仍可能并发执行同一个 job。
- [ ] SQLite/local 模式仍不启动 heartbeat。
- [ ] 导出任务没有阶段边界取消检查。
- [ ] 断点续跑仍未实现，取消后已完成页面结果不会复用。
- [ ] 页面生成外层 2 次与 gateway 内部最多 3 次叠加，仍可能超过“修复 ≤2 次”。
- [ ] repair prompt 的 `previous_json` 仍固定传空。
- [ ] gateway 的修复提示仍内联在 Python 中，没有进入 prompt 文件。

## P1 - 长文档与解析

- [ ] 大纲仍只读取前 60 个章节，后续章节会被静默丢弃。
- [ ] 章节摘要仍是前 240 字符截断，不是真正的分块摘要。
- [ ] 单章进入大纲前仍截断到 4000 字符。
- [ ] 逐页生成仍只读取单章前 6000 字符。
- [ ] 页面可用资产 JSON 仍截断到 4000 字符，资产较多时可能生成非法引用。
- [ ] 大纲 SSE 仍在模型完整生成后统一发出 item，不是真实逐项推进。
- [ ] OMML 失败仍只写占位文本，没有按项目书保留裁剪图片。
- [ ] 上传仍缺少 MIME 白名单校验。
- [ ] DOCX 仍缺少 zip 展开大小和压缩比检查。
- [ ] 未知图片 MIME 仍可能被保存为普通资产。
- [ ] 重复图片仍只保留第一次出现的 sourceRef。
- [ ] `doc_assets.ref_count` 仍未维护。

## P1 - 清理与计量

- [ ] 对象存储删除失败后，cleanup 仍会删除数据库 artifact 记录。
- [ ] 被回收 Deck 的 artifact 同样在存储失败后继续删除数据库记录和 Deck。
- [ ] 孤儿资产清理仍未实现。
- [ ] 清理失败仍没有重试队列和告警。
- [ ] cleanup 仍没有存储失败路径测试。
- [ ] DeepSeek 调用 schema 失败时仍先写成功 usage，再写相同 usage 的失败记录，导致重复计量。
- [ ] usage ledger 仍没有上游调用 ID，无法识别重试和重复写入。
- [ ] 尚未完成真实 DeepSeek 的成功、修复成功、最终失败三种计量验收。

## P1 - 编辑、版本与播放

- [ ] 大纲仍不能拖拽排序、新增或重新绑定章节。
- [ ] Monaco 与大纲、Slide 仍没有双向定位。
- [ ] 仍没有 12 列栅格拖拽、吸附和重置默认布局。
- [ ] 仍没有图片替换、表格编辑和富文本白名单编辑器。
- [ ] 样式面板仍只有字号、颜色和对齐，缺少字重、行高、内距、圆角、阴影、透明度和背景。
- [ ] 版本时间轴仍没有版本预览、双栏 diff 和分支关系展示。
- [ ] 版本时间轴没有使用新的 `limit/offset` 分页，超过默认 100 版仍不可见。
- [ ] 播放器 `step` 仍未传入 iframe，按“下一步”不会改变幻灯片画面。
- [ ] 转场仍只是标签展示，没有真实播放。
- [ ] fragment 与 steps 元数据仍未建立统一映射。
- [ ] 片段和转场输入每次按键仍立即提交 Patch，可能产生大量 autosave。

## P2 - 尚未完成的功能

- [ ] MP4 WebCodecs 逐帧导出、参数面板、音轨和字幕。
- [ ] 动效组件库与纯函数式 `seek(t)` / `duration()` / `keyframe()`。
- [ ] MotionBudget 和 motionLevel 对六类动效维度的真实缩放。
- [ ] FlowParticles、StepReveal、ChartReveal、FlowDiagram、FormulaStep、CodeType。
- [ ] 演讲者视图的当前页、下一页、备注和计时。
- [ ] 用户模板包上传与七项校验器。
- [ ] 14 种模板版式的模板热加载和能力校验。
- [ ] 自然语言指令转 JSON Patch。
- [ ] PDF、PPTX、HTML 的完整溯源附录和原文定位链接。
- [ ] 图表、表格在导出时的静态降级说明和逐元素备注。
- [ ] 视频/GIF/PPT 的按页增量重渲和 schema_hash 缓存强化。

## P2 - 字体和 CJK

- [ ] 接入统一字体文件、字体子集和版本号。
- [ ] 增加 `@font-face` 和内联字体。
- [ ] 导出前执行 manifest 字体版本检查。
- [ ] 增加缺字形检查和导出阻断。
- [ ] 实际应用中文字号 = 西文字号 × 1.03。
- [ ] 当前 `--cjk-scale` 和 `.cjk-compensate` 仍未被任何版式使用。
- [ ] 实现 `text-autospace` 的零宽空格回退。
- [ ] 完成避头尾和中文禁止 `break-all` 的视觉回归测试。
- [ ] 完成 M1 第 7 条“无字体替换告警”。

## P2 - 部署与数据库

- [ ] Docker Compose 仍没有 MinIO bucket 初始化。
- [ ] API Docker 镜像仍未安装 pandoc。
- [ ] 仍未配置 PostgreSQL、Redis、MinIO、render-svc 完整启动健康检查。
- [ ] 仍缺少 `deck_versions.snapshot` 的 GIN 索引。
- [ ] 仍缺少 shares、jobs、sessions 等文档要求的部分索引。
- [ ] 仍缺少 `doc_assets(document_id, sha256)` 的并发一致性约束。
- [ ] 新增 `allow_mock_in_prod` 未同步到 `.env.example` 和 README。
- [ ] README 中项目书文件名、分享 API 路径、主题上传 API 仍与实际实现不一致。

## 测试补强

- [ ] 增加“回退 -> 编辑 -> 重新读取”的分支回归测试。
- [ ] 增加回退到初始 v1 的允许/拒绝策略测试和 UI 状态测试。
- [ ] 增加回退后重新生成仍使用旧 idempotency key 的测试。
- [ ] 增加逗号、顿号、冒号和同句多指标绑定测试。
- [ ] 增加 sourceRef 列边界和多 provenance 映射测试。
- [ ] 增加非法 themeId Patch 测试。
- [ ] 增加原始值、derived 图表和 originalData 缺失测试。
- [ ] 增加分享 auth_fail 写入 `share_access_logs` 的测试。
- [ ] 增加真实 render-svc PDF/GIF/PPTX 测试，替换冒烟脚本中的假 PDF/GIF。
- [ ] 增加导出样式、位置、图片和字体一致性快照测试。
- [ ] 增加清理存储失败路径测试。
- [ ] 增加 usage ledger 一次调用只记录一次计量的测试。
- [ ] 增加 70 章节和超长单章不被静默遗漏的测试。
- [ ] 增加任务超时、重复 enqueue、幂等和取消测试。
- [ ] 增加前端 Playwright 测试，覆盖大纲拖拽、双向定位、Patch 刷新、版本分支和播放器步进。
- [ ] 增加真实 5 份 Word 文档回归和真实 DeepSeek 验收。

## 建议下一轮修复顺序

1. 先修复回退分支混入旧 patch 的 P0 回归。
2. 修复逗号/冒号多指标绑定、sourceRef 列范围和 derived provenance。
3. 修复非法 themeId、多 provenance 映射及 Element provenance。
4. 建立统一编辑/导出渲染，补齐字体和 CJK。
5. 修复分享失败访问日志、任务超时/幂等/reclaim 和清理顺序。
6. 修复长文档截断、OMML 图片降级、上传安全及 usage 重复计量。
7. 完成编辑、版本 diff、播放器步进和前端自动化。
8. 最后实现 MP4、动效组件库、模板包和真实 Docker/render-svc 验收。
