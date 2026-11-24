# Presenta 第三轮验收整改清单

> 基线：`README.md`、项目书 PDF、`AGENTS.md`、`todolist1.md`、`todolist2.md`、本轮更新后的代码与测试。
>
> 结论：本轮进一步关闭了版本分支、多指标切分、列范围、非法主题和基础 derived provenance 问题，但整体验收仍不通过。真实模型提示词与 PageDraft Schema 存在冲突，编辑态与导出态仍不一致，数据来源仍有可伪造空间，导出/JOBS/字体/长文档/前端等功能仍有大量缺口。

## 本版新增的硬性验收要求

- [ ] **从当前版本开始必须使用真实 DeepSeek API Key 进行验收，不能再以 mock provider 作为本轮验收通过依据。**
- [ ] API Key 必须由服务端从配置文件或环境变量配置文件读取，统一使用 `DEEPSEEK_API_KEY`。
- [ ] 验收配置必须显式设置 `LLM_PROVIDER=deepseek`。
- [ ] DeepSeek API Key 不得写入前端变量、浏览器代码、Source Map、日志、异常响应、测试快照或 Git 仓库。
- [ ] `.env` 必须保持 Git 忽略；仓库中只能保留不含真实 Key 的 `.env.example`。
- [ ] 服务启动时必须校验真实 API Key 已配置；缺失时拒绝真实模型验收并返回明确配置错误。
- [ ] 所有大纲和逐页生成验收必须确认实际调用 DeepSeek `deepseek-flash`，不能回退到 mock 或静默降级。
- [ ] 验收报告必须记录 provider、model、调用时间、成功/失败状态和 usage ledger，但不得记录 API Key 明文。
- [ ] 真实 API 验收至少要覆盖：大纲生成、普通文本页、图表页、关键数字页、引用页、修复重试和最终降级。
- [ ] 真实 API 返回 401/403/429/5xx 时必须有明确的用户提示、可观测日志和正确计量，不能误标记为生成成功。
- [ ] 配置文档必须说明本地开发、Docker Compose、测试和 CI 中真实 Key 的注入方式。
- [ ] 增加启动配置测试，确保缺少 Key、provider 配错和 Key 泄露到前端构建产物时均会失败。

## 本轮复核结果

### 已通过的检查

- [x] 后端测试增加到 44 项，当前全部通过。
- [x] `ruff check app tests` 通过。
- [x] `mypy app` 通过。
- [x] 前端 `typecheck`、`lint`、生产构建通过。
- [x] Alembic `upgrade -> downgrade -> upgrade` 通过。
- [x] mock 端到端冒烟流程通过。
- [x] 后端基础语义、分享 token、Patch 只读字段和 version parent 链测试通过。

### 本轮确认修复

- [x] 回退后继续编辑不再混入已放弃分支的 patch。
- [x] 新版本 parent 指向当前版本，`load_deck_at()` 按 parent 链回放。
- [x] 已增加回退后继续编辑的分支回归测试。
- [x] 回退到初始空 Deck 会显式返回冲突，不再在内部产生无效活动版本。
- [x] 逗号、顿号、分号、斜杠和换行会切分多个指标。
- [x] `A 组 100，B 组 200` 不再允许 A 组冒用 B 组的 200。
- [x] sourceRef 的 colStart/colEnd 已参与原文区间计算。
- [x] quote 超出列范围会被拒绝。
- [x] 通用 Patch 修改为不存在的 themeId 会被语义校验拒绝。
- [x] 已校验 Deck.id 与数据库 Deck row 一致。
- [x] 图表必须提供 derived provenance。
- [x] Element provenance 和 Deck provenance 开始执行文档/区间校验。
- [x] 图片资产 sourceRef 必须存在，并开始与页面 provenance 做重叠检查。
- [x] 表格非数字文本也开始校验是否出现在来源区间。

## P0 - 当前阻断项

### 真实页面生成提示词与 Schema 冲突

- [ ] **页面提示词要求模型输出 provenance，但 `PageDraft` 禁止该字段。**

  当前事实：

  - `page.md` 第 5 条要求使用原文数据的页面提供 provenance。
  - `PageDraft` 只有 layout、slots、notes，且 `CamelModel` 配置为 `extra="forbid"`。
  - 模型若按提示词输出顶层 provenance，会被 Pydantic 直接拒绝。
  - repair prompt 没有完整 PageDraft Schema，也没有说明 provenance 必须省略。
  - mock provider 不输出 provenance，因此冒烟测试无法暴露此问题。

- [ ] 明确 provenance 由后端自动附加还是由模型输出，二者只能保留一种协议。
- [ ] 若由后端自动附加，删除 `page.md` 中要求模型输出 provenance 的规则。
- [ ] 若由模型输出，扩展 `PageDraft` 并明确 elements/provenance 的 JSON 结构。
- [ ] 提示词中图表必须使用 `derived`、其他来源页通常使用 `original`，不能统一要求 original。
- [ ] repair prompt 必须给出完整期望 Schema、失败 JSON 和实际 previous_json。
- [ ] 当前 repairing 时 `previous_json=""`，需要保存并回传上一版原始输出。
- [ ] page prompt 的多个占位符未在 system prompt 中渲染；页面上下文改由 Python 内联拼接，存在协议漂移。
- [ ] 将页面提示词完整移入 prompt 文件并全部渲染，不在 Python 中拼接硬性规则。
- [ ] 增加 fake DeepSeek 输出“带 provenance”的端到端测试，验证不会错误进入降级页。
- [ ] 增加真实 DeepSeek 图表页、关键数字页和引用页生成验收。

### 编辑态与导出态

- [ ] 导出 HTML/PDF 仍只读取 `slide.slots`，完全忽略 `slide.elements`、`styleOverride` 和 Element layout。
- [ ] 用户在画布修改字号、颜色、对齐或位置后，PDF/GIF/HTML 导出仍会丢失修改。
- [ ] PPTX 仍只生成标题、正文和页脚三个文本框。
- [ ] PPTX 未插入图片、表格、图表、GIF 或元素动效。
- [ ] GIF 仍是每页单张截图重复成多帧，没有逐帧 `seek(t)`。
- [ ] GIF 深色主题仍仅添加说明，没有实际切换浅色背景。
- [ ] 当前 GIF 只提示 256 色，没有明确告知“全部动画被丢弃”。
- [ ] 导出降级仍不满足“逐页、逐能力告知”的要求。
- [ ] 需要建立统一编辑/导出 renderer，不能继续维护两套不一致的 HTML 模板。
- [ ] 增加编辑后 HTML/PDF/PPTX/GIF 的样式和位置快照测试。

### source、originalData 与图片列区间

- [ ] `source` 仍是普通字符串，语义校验只要求页面存在任意 provenance。
- [ ] 实测 `source="完全无关的出处"` 仍能通过图表语义校验。
- [ ] source 插槽必须至少关联明确的 provenance id 或结构化 documentId/sourceRef。
- [ ] 每个图表、表格、引用、关键数字和全图必须绑定到具体 provenance，而不是只验证“本页有 provenance”。
- [ ] derived provenance 的 `originalData={}` 仍可通过；只检查非 null 不足以保留原始数据表。
- [ ] 校验 originalData 必须包含实际列、行、数值和单位。
- [ ] 校验 originalData 的每个数据点与图表/关键数字对应，不能保存空壳或无关对象。
- [ ] 图片 sourceRef 与页面 provenance 的重叠检查只比较行号，不比较列号。
- [ ] 同一行不同字符区间的图片和 provenance 会被判为重叠，需要改成真实字符区间相交。
- [ ] 多图表页面只要求任意一条 derived provenance，可能让多个图表共用一条来源。
- [ ] 建立 Element/媒体路径到 Provenance 的一对一映射或多对多显式引用。

### Schema 向后兼容

- [ ] 当前仍只支持 schemaVersion 1，但本轮改变了图表 provenance 规则。
- [ ] 旧版本中按 previous 逻辑生成的图表使用 `original` provenance，现在会被判定非法。
- [ ] 旧 Deck 可以查看，但不能继续 Patch 或导出，除非人工修复 provenance。
- [ ] 增加 schema 迁移或将旧 original 图表 provenance 安全迁移为 derived + originalData。
- [ ] 增加旧 snapshot 回放、导出和再次编辑测试。
- [ ] 不兼容的语义变更必须提升 schemaVersion 或提供迁移函数，不能静默改变 v1 的可写性。

## P1 - 版本与编辑

- [ ] 回退到初始空 Deck 已被后端拒绝，但版本时间轴仍显示可点击的“回退”按钮。
- [ ] UI 需要禁用空 Deck/不可回退版本的按钮，并解释原因。
- [ ] 版本时间轴没有使用后端新增的 `limit/offset`，默认只加载 100 版。
- [ ] 版本父子链已经存在，但 UI 不展示分支、父子关系或废弃路径。
- [ ] 版本预览和双栏 diff 仍未实现。
- [ ] 回退后点击“重新生成”仍可能命中旧 idempotency key，返回已完成旧 job。
- [ ] 并发 Patch 同时读取同一 current seq 时，可能竞争同一个 `seq` 并触发唯一约束冲突。
- [ ] 需要乐观锁、版本条件更新或事务级 Deck 锁。
- [ ] 大纲仍不能拖拽排序、新增或重新绑定章节。
- [ ] Monaco 与大纲、页面之间仍没有双向定位。
- [ ] 仍没有 12 列栅格拖拽、吸附和重置默认布局。
- [ ] 仍没有图片替换、表格编辑和富文本白名单编辑器。
- [ ] 样式面板仍只有字号、颜色和对齐。
- [ ] 片段和转场输入仍可能在每次按键时提交 Patch。

## P1 - 分享与安全

- [ ] 错误分享密码只写 `audit_logs`，没有写项目书要求的 `share_access_logs.auth_fail`。
- [ ] 分享访问日志测试仍只覆盖成功 view/download，没有验证 auth_fail。
- [ ] action 名为 `share.auth_fail`，但 ShareAccessLog kind 白名单期望 `auth_fail`，需要统一审计模型。
- [ ] `SHARE_PASSWORD_ATTEMPTS` 的限流策略仍会引起“成功解锁也占次数”的行为，需要明确语义。
- [ ] ShareToken 固定 2 小时过期，没有滑动续期或主动刷新策略。
- [ ] 过期 ShareToken 没有 cleanup。
- [ ] 分享下载仍不是独立签名短时效 URL，而是依赖分享 Cookie 的后端代理。
- [ ] 分享 PDF/PPTX/GIF 下载仍在 HTTP 请求中同步渲染。
- [ ] 并发点击下载没有 per-share/format 锁，可能重复执行昂贵导出。
- [ ] `audit_isolated()` 写入失败时被吞掉，仅记录日志，没有指标或告警。
- [ ] Redis 限流错误日志包含原始 IP key，需要统一哈希。
- [ ] `allow_mock_in_prod` 尚未加入 `.env.example` 和部署文档。

## P1 - 任务治理

- [ ] `INGEST_TIMEOUT_S` 仍未应用。
- [ ] `BATCH_CONCURRENCY_PER_USER` 仍未应用。
- [ ] ARQ 仍是固定 1800 秒全局超时。
- [ ] PDF/GIF/PPTX 导出任务仍没有幂等键。
- [ ] 失败生成任务仍可能因已存在 idempotency key 返回旧失败 job。
- [ ] stale reclaim 仍每 15 分钟巡检，项目书要求 60 秒。
- [ ] ARQ enqueue 失败仍会静默改为 API 进程内执行。
- [ ] 任务领取仍非原子操作，重复 enqueue 可能并发执行同一 job。
- [ ] SQLite/local 模式仍不写 heartbeat。
- [ ] 导出任务仍没有阶段边界取消检查。
- [ ] 取消后已完成页面结果仍不会持久化，无法断点续跑。
- [ ] 页面外层重试与 gateway 内部重试仍可能叠加超过修复次数上限。
- [ ] repair prompt 的 previous_json 仍为空。
- [ ] gateway 修复提示仍内联在 Python 中。

## P1 - 长文档与解析

- [ ] 大纲仍只处理前 60 个章节。
- [ ] 章节摘要仍只是前 240 字符截断。
- [ ] 章节进入大纲前仍被截断到 4000 字符。
- [ ] 逐页生成仍只读取章节前 6000 字符。
- [ ] 资产 JSON 仍截断到 4000 字符，资产多时可能产生不完整输入。
- [ ] 大纲 SSE item 仍在完整生成后统一发出，不是真实逐项推进。
- [ ] OMML 转换失败仍只保留占位文本，没有裁剪图片。
- [ ] 上传仍缺少 MIME 白名单。
- [ ] DOCX 仍缺少 zip 展开大小和压缩比校验。
- [ ] 未知图片 MIME 仍可能保存。
- [ ] 重复图片仍只保留首次 sourceRef。
- [ ] `doc_assets.ref_count` 仍未维护。

## P1 - 清理与计量

- [ ] 对象存储删除失败后，仍然继续删除 artifact 数据库记录。
- [ ] 回收 Deck 的 artifact 在存储失败后仍继续删除数据库记录和 Deck。
- [ ] 孤儿资产清理仍未实现。
- [ ] cleanup 失败重试和告警仍未实现。
- [ ] DeepSeek schema 校验失败时仍会写一条成功 usage 和一条失败 usage。
- [ ] 一次上游调用仍可能被重复计入 token 与成本。
- [ ] usage ledger 仍无 upstream call id 或唯一约束。
- [ ] 真实 DeepSeek 成功、修复、失败三种路径的计量仍未验收。

## P1 - 前端、播放与导出入口

- [ ] 播放器 step 仍未传入 iframe，点击“下一步”不会改变幻灯片画面。
- [ ] 转场仍只是标签展示，没有真实播放。
- [ ] 版本时间轴不回显分支关系，也不使用分页参数。
- [ ] 前端仍没有大纲拖拽、Monaco 双向定位、样式完整面板和图片替换。
- [ ] MP4 按钮仍明确提示不可用。
- [ ] 导出面板仍可能展示“服务端导出已实现”，但实际 PPTX/GIF 保真与文档要求差距很大。
- [ ] 导出列表没有逐页显示样式、图片、字体和动效的降级明细。

## P2 - 字体与 CJK

- [ ] 未接入字体文件和字体子集。
- [ ] 未提供 `@font-face`。
- [ ] 导出前未校验 manifest 字体版本。
- [ ] 未执行字形覆盖检查。
- [ ] 中文字号 = 西文字号 × 1.03 仍未应用。
- [ ] `--cjk-scale` 和 `.cjk-compensate` 仍无实际使用位置。
- [ ] `text-autospace` 零宽空格回退仍未实现。
- [ ] 尚未完成中英混排视觉回归。
- [ ] 尚未完成 M1“无字体替换告警”验收。

## P2 - 未完成产品功能

- [ ] MP4 WebCodecs 逐帧导出。
- [ ] 动效 `seek(t)` / `duration()` / `keyframe()` 组件库。
- [ ] MotionBudget 六维参数缩放。
- [ ] FlowParticles、StepReveal、ChartReveal、FlowDiagram、FormulaStep、CodeType。
- [ ] 演讲者视图及计时。
- [ ] 用户模板包上传和七项校验器。
- [ ] 模板版式热加载。
- [ ] 自然语言指令转 JSON Patch。
- [ ] PDF/PPTX/HTML 完整溯源附录。
- [ ] 图表/表格导出静态降级明细。
- [ ] 导出按页增量重渲与缓存强化。

## P2 - 部署、数据库与文档

- [ ] Docker Compose 仍无 MinIO bucket 初始化。
- [ ] API Docker 镜像仍无 pandoc。
- [ ] 缺少完整服务健康检查和启动依赖。
- [ ] 缺少 `deck_versions.snapshot` GIN 索引。
- [ ] 缺少 shares/jobs/sessions 部分索引。
- [ ] 缺少 `doc_assets(document_id, sha256)` 并发约束。
- [ ] README 中项目书文件名、分享 API、主题上传 API 仍与实现不一致。
- [ ] 新增运行时配置项未同步到 `.env.example`。
- [ ] README 的“已实现”描述仍明显领先于真实导出和编辑能力。

## 测试补强

- [ ] 增加 Prompt 输出 provenance 时不得被 PageDraft 拒绝的真实模型协议测试。
- [ ] 增加 PageDraft Schema 与 prompt 输出字段一致性测试。
- [ ] 增加 source 插槽与 provenance 绑定测试。
- [ ] 增加 originalData 空对象、无关对象和错误数值测试。
- [ ] 增加图片 sourceRef 同一行不同字符区间测试。
- [ ] 增加多图表、多 provenance 映射测试。
- [ ] 增加旧 v1 snapshot 在语义规则升级后的回放、编辑和导出测试。
- [ ] 增加初始化空版本在 UI 中不可回退测试。
- [ ] 增加回退后重新生成不会复用旧 job 的测试。
- [ ] 增加并发 Patch 的 seq 冲突测试。
- [ ] 增加分享 auth_fail 写入 share_access_logs 测试。
- [ ] 增加真实 render-svc PDF/GIF/PPTX 测试。
- [ ] 增加导出样式、Element layout、图片和字体快照测试。
- [ ] 增加 cleanup 存储失败测试。
- [ ] 增加 usage ledger 一次调用只计量一次测试。
- [ ] 增加 70 章节、超长章节和大资产列表测试。
- [ ] 增加任务超时、重复 enqueue、reclaim、取消和续跑测试。
- [ ] 增加前端 Playwright 端到端测试。
- [ ] 增加真实 5 份 Word 文档和真实 DeepSeek 回归。

## 建议下一轮修复顺序

1. 修复 page prompt 与 PageDraft Schema 的 provenance 协议冲突。
2. 将 source 插槽绑定到具体 provenance，并校验 originalData 内容。
3. 修复图片 sourceRef 的列级重叠和多来源映射。
4. 建立统一编辑/导出渲染，修复 styleOverride、PPTX 和 GIF。
5. 修复旧 schema 兼容、空版本 UI、idempotency 和并发 Patch。
6. 修复分享 auth_fail 日志、任务超时/幂等/reclaim 和 cleanup 顺序。
7. 修复长文档截断、OMML 图片降级、上传安全和 usage 重复计量。
8. 完成字体/CJK、播放器步进、前端编辑和真实导出验收。
9. 最后实现 MP4、动效库、模板包和 Docker 全链路验收。
