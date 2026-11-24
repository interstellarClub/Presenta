# Presenta 第四轮验收整改清单

> 基线：`README.md`、项目书 PDF、`AGENTS.md`、`todolist1.md` 至 `todolist3.md`、本轮更新后的代码与测试。
>
> 结论：本轮修复了页面提示词协议、source/originalData 校验、图片字符区间和图表来源独占等问题，但整体验收仍不通过。最直接的阻断是当前工作区没有 `.env`，真实 `DEEPSEEK_API_KEY` 未配置，provider 仍是 mock，因此无法完成本版要求的真实 API 验收；编辑/导出一致性、版本 UI、JOBS、字体、长文档和前端功能也仍未完成。

## 一、真实 API Key 硬性要求

### 当前配置状态

- [ ] **当前版本仍未满足“必须使用真实 API Key 验收”的要求。**
- [ ] 仓库根目录 `.env` 不存在。
- [ ] `backend/.env` 不存在。
- [ ] 当前进程环境中的 `DEEPSEEK_API_KEY` 为空。
- [ ] 当前解析出的 `LLM_PROVIDER` 为 `mock`。
- [ ] 当前 `deepseek_api_key_configured` 为 `false`。
- [ ] 本轮无法实际调用 DeepSeek，因此真实大纲、逐页生成、修复和降级均未验收。

### 必须完成的配置与代码修改

- [ ] 创建本地 `.env` 配置文件并填入真实 `DEEPSEEK_API_KEY`。
- [ ] 设置 `LLM_PROVIDER=deepseek`。
- [ ] 保持 `DEEPSEEK_MODEL=deepseek-flash`，除非项目书另行更新模型别名。
- [ ] `.env` 必须继续被 `.gitignore` 忽略，仓库中不能提交真实 Key。
- [ ] `.env.example` 应改为真实验收模式，至少写明 `LLM_PROVIDER=deepseek` 和 Key 必填要求。
- [ ] `Settings.llm_provider` 不应继续默认 `mock`；本版验收环境应默认或强制使用 `deepseek`。
- [ ] 当 `LLM_PROVIDER=deepseek` 且 Key 为空时，应用应在启动阶段直接失败。
- [ ] 当前设置 `LLM_PROVIDER=deepseek`、Key 为空时仍能成功构建 Settings，需要增加启动配置校验。
- [ ] Docker Compose 不应继续使用 `LLM_PROVIDER: ${LLM_PROVIDER:-mock}` 作为默认值。
- [ ] Docker Compose 中 `DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY:-}` 为空时应在启动阶段失败。
- [ ] README 不应继续把 mock 模式描述为默认验收模式。
- [ ] 增加独立真实 API smoke 目标，不能与 mock 冒烟共用同一通过结论。
- [ ] `tests/conftest.py` 可以继续使用 mock 做单元测试，但必须有单独的真实 DeepSeek 集成测试套件。
- [ ] `scripts/smoke_pipeline.py` 仍强制 `LLM_PROVIDER=mock`，不能作为本版最终验收脚本。

### API Key 安全

- [x] `.env` 已被 `.gitignore` 忽略。
- [x] 当前前端构建产物未发现 `DEEPSEEK_API_KEY` 或明显 API Key 样本。
- [x] 当前代码只在服务端 gateway 中读取 Key。
- [ ] 将 `deepseek_api_key` 改为 `SecretStr`，避免配置对象被 `repr`/日志序列化时泄露明文。
- [ ] 日志、异常详情、usage ledger、审计日志和测试快照不得含 Key。
- [ ] 启动日志只能记录 provider、model 和 Key 是否配置，不得记录 Key 内容。
- [ ] 前端环境变量中禁止出现任何 `VITE_*DEEPSEEK*`。
- [ ] CI 使用 secret 注入 Key，并增加泄露扫描。

### 真实 API 必需验收场景

- [ ] 真实 API 大纲生成成功。
- [ ] 真实 API 普通文本页生成成功。
- [ ] 真实 API 图表页生成成功，并自动附加 derived provenance/originalData。
- [ ] 真实 API 关键数字页生成成功。
- [ ] 真实 API 引用页生成成功。
- [ ] 真实 API 图片页生成成功，assetId 与 sourceRef 校验通过。
- [ ] 真实 API 首次输出非法后，第二次修复成功。
- [ ] 连续两次修复失败后，页面降级并标记 `degraded`。
- [ ] 401/403/429/5xx 有正确错误响应、日志和 usage 记录。
- [ ] 真实调用确认 `usage_ledger.provider=deepseek`、model 正确、thinking 配置正确。
- [ ] 当前“一次调用写入成功 usage 后再写失败 usage”的重复计量必须在真实 API 验收前修复。

## 二、本轮已通过的检查

- [x] 后端测试增加到 54 项，当前全部通过。
- [x] `ruff check app tests` 通过。
- [x] `mypy app` 通过。
- [x] 前端 `typecheck`、`lint`、生产构建通过。
- [x] Alembic `upgrade -> downgrade -> upgrade` 通过。
- [x] mock 冒烟流程通过，但它不是真实模型或真实渲染验收。
- [x] 版本 parent 链和回退后编辑测试通过。
- [x] 分享 token、Patch 只读字段、错误登录审计测试通过。

## 三、本轮确认修复

- [x] PageDraft 已接受可选 provenance，不再与合法 JSON 结构直接冲突。
- [x] `page.md` 明确要求模型不要再输出 provenance，改由后端自动附加。
- [x] `page_user.md` 将页面上下文和输出约定迁移到提示词文件。
- [x] repair prompt 已写明期望 JSON 和禁止额外字段。
- [x] gateway schema repair 已迁移到 `services/llm/prompts/schema_repair.md`。
- [x] 页面生成总尝试次数调整为 1 次初始 + 2 次修复。
- [x] 页面调用 gateway 时使用 `repair_budget=0`，避免外层与内层修复次数叠加。
- [x] 语义失败后会将上一版 PageDraft JSON 回传给 repair prompt。
- [x] source 插槽开始与 provenance 行号、quote 和 originalData 做匹配。
- [x] derived originalData 不能再是空对象。
- [x] 图表 originalData 必须包含图表数据点，且不能包含图表之外的数值。
- [x] 关键数字页 originalData 必须包含非空 numbers，并覆盖全部关键数字。
- [x] 图片 sourceRef 与 provenance 改为真实字符区间重叠检查。
- [x] 多个图表不得共用同一条 provenance。
- [x] 表格非数字文本、sourceRef 列范围和逗号多指标绑定已有测试。

## 四、P0 - 当前阻断项

### 真实 API 无法验收

- [ ] 无真实 Key，无法验证真实模型是否遵守当前提示词。
- [ ] 无真实 Key，无法验证 `deepseek-flash` 的 JSON 稳定性。
- [ ] 无真实 Key，无法验证图表页 derived provenance 自动附加。
- [ ] 无真实 Key，无法验证修复预算和降级路径。
- [ ] 当前真实模型测试只是 monkeypatch `_post_deepseek`，不能证明 API 可用。
- [ ] `test_deepseek_page_payload_with_provenance_is_accepted` 使用 fake transport 和 `test-key`，属于协议测试，不是真实 API 验收。
- [ ] 需要用户提供真实 Key 后重新执行本轮验收。

### 编辑态与导出态仍不一致

- [ ] 导出 HTML/PDF 仍只读取 `slide.slots`，没有读取 `slide.elements`、`styleOverride` 或 Element layout。
- [ ] 用户画布中的字号、颜色、对齐和位置修改仍不会进入导出。
- [ ] PPTX 仍只生成标题、正文和页脚三个文本框。
- [ ] PPTX 仍未插入图片、图表、表格、GIF 或元素动效。
- [ ] GIF 仍为每页单张截图重复，不是逐帧 `seek(t)`。
- [ ] GIF 深色主题仍未实际切换浅底。
- [ ] GIF 仍只说明 256 色，没有逐页说明全部动画被丢弃。
- [ ] 需要统一编辑/导出渲染器，避免两套 HTML 模板继续漂移。

### Schema 向后兼容

- [ ] schemaVersion 仍仅为 1，但本轮继续改变 v1 的 provenance 和 originalData 规则。
- [ ] 旧图表页若仍使用 original provenance，当前会无法 Patch 或导出。
- [ ] 需要安全迁移旧 original 图表为 derived + originalData，或提升 schemaVersion。
- [ ] 增加旧 snapshot 的回放、编辑、导出和再回放测试。

## 五、P1 - 数据与来源

- [ ] `source` 仍是普通字符串，不是结构化 documentId/sourceRef 引用。
- [ ] source 校验通过行号数字匹配，短来源值如 `"1"` 可能借助对应行号通过。
- [ ] source、图表和 provenance 仍没有持久化的一对一 ID 映射。
- [ ] 表格页尚未限制多个表格共用同一条 provenance。
- [ ] 多来源页面仍按“任意来源能匹配”处理，媒体与来源的绑定粒度不够。
- [ ] `originalData.numbers` 只校验 value，没有严格校验 label 和单位。
- [ ] 图片 assetId、asset sourceRef 与页面 provenance 三者仍没有显式关联 ID。
- [ ] external provenance 默认关闭、用户确认和审计流程仍未完成。
- [ ] 各 Element 的 provenance 仍未被完整填充和渲染。

## 六、P1 - 版本、并发与编辑

- [ ] 初始空 Deck 不能回退，但版本时间轴仍显示可点击“回退”按钮。
- [ ] 版本时间轴仍不使用后端 `limit/offset`。
- [ ] 版本时间轴仍不展示 parent、分支和废弃路径。
- [ ] 版本预览和双栏 diff 仍未实现。
- [ ] 回退后点击“重新生成”仍可能命中旧 idempotency key。
- [ ] 并发 Patch 会读取相同 current seq，可能生成相同新 seq 并触发唯一约束错误。
- [ ] 需要版本乐观锁、条件更新或 Deck 行锁。
- [ ] 大纲仍不能拖拽、新增或重新绑定章节。
- [ ] Monaco 与大纲、页面之间仍没有双向定位。
- [ ] 仍没有 12 列栅格拖拽、吸附和重置默认。
- [ ] 仍没有图片替换、表格编辑和富文本白名单。
- [ ] 样式面板仍只有字号、颜色和对齐。
- [ ] 片段和转场输入仍可能每次按键提交 Patch。

## 七、P1 - 分享与安全

- [ ] 分享密码错误仍只写审计日志，没有写 `share_access_logs.auth_fail`。
- [ ] action 名 `share.auth_fail` 与 ShareAccessLog kind `auth_fail` 未统一。
- [ ] 缺少分享限流、失败日志和锁定后的端到端测试。
- [ ] ShareToken 固定 2 小时过期，没有续期策略。
- [ ] 过期 ShareToken 没有 cleanup。
- [ ] 分享下载仍不是独立签名短时效 URL。
- [ ] 分享 PDF/PPTX/GIF 下载仍在请求内同步渲染。
- [ ] 分享下载没有 per-share/format 并发锁。
- [ ] `audit_isolated()` 写失败只记录日志，没有监控告警。
- [ ] Redis 限流错误日志包含原始 IP key。

## 八、P1 - 任务治理

- [ ] `INGEST_TIMEOUT_S` 仍未应用。
- [ ] `BATCH_CONCURRENCY_PER_USER` 仍未应用。
- [ ] ARQ 仍固定全局 1800 秒超时。
- [ ] PDF/GIF/PPTX 导出仍没有幂等键。
- [ ] 失败生成任务仍可能返回旧失败 job。
- [ ] stale reclaim 仍每 15 分钟执行一次。
- [ ] ARQ enqueue 失败仍可静默转为 API 进程内任务。
- [ ] 任务领取仍不是原子操作。
- [ ] SQLite/local 仍不写 heartbeat。
- [ ] 导出任务仍没有取消检查。
- [ ] 页面中断后的已完成结果仍不持久化。
- [ ] 页面首次 JSON 校验失败时仍无法取得原始输出，repair 的 previous_json 可能为空。
- [ ] usage ledger 仍对一次 DeepSeek 调用重复写成功和失败记录。

## 九、P1 - 长文档与解析

- [ ] 大纲仍只处理前 60 个章节。
- [ ] 章节摘要仍只是前 240 字符截断。
- [ ] 章节进入大纲前仍截断到 4000 字符。
- [ ] 逐页生成仍只读取单章前 6000 字符。
- [ ] 资产 JSON 仍截断到 8000 字符。
- [ ] 大纲 SSE item 仍在一次完整生成后统一发出。
- [ ] OMML 失败仍只写占位文本，没有裁剪图片。
- [ ] 上传仍缺少 MIME 白名单。
- [ ] DOCX 仍缺少 zip 展开大小和压缩比防护。
- [ ] 未知图片 MIME 仍可能保存。
- [ ] 重复图片仍只保存首次 sourceRef。
- [ ] `doc_assets.ref_count` 仍未维护。

## 十、P1 - 清理与计量

- [ ] artifact 对象删除失败后仍继续删除数据库记录。
- [ ] 回收 Deck 的 artifact 删除失败后仍继续删除 DB 和 Deck。
- [ ] 孤儿资产清理仍未实现。
- [ ] cleanup 失败重试和告警仍未实现。
- [ ] usage ledger 一次调用仍可能被计为两次。
- [ ] usage ledger 仍无 upstream call id 或唯一约束。
- [ ] 通过真实 API 验证 usage 计量尚未完成。

## 十一、P1 - 前端与播放

- [ ] 播放器 step 仍未传入 iframe。
- [ ] “下一步”不会改变幻灯片内容。
- [ ] 转场仍只是标签展示。
- [ ] 版本历史没有分支展示和分页 UI。
- [ ] 大纲拖拽和双向定位仍未实现。
- [ ] 图片替换和完整样式面板仍未实现。
- [ ] MP4 仍明确不可用。
- [ ] 导出面板没有逐页降级明细。

## 十二、P2 - 字体与 CJK

- [ ] 未接入字体文件和子集。
- [ ] 未提供 `@font-face`。
- [ ] 导出前未校验字体 manifest 版本。
- [ ] 未执行字形覆盖检查。
- [ ] 中文字号 = 西文字号 × 1.03 仍未应用。
- [ ] `--cjk-scale` 和 `.cjk-compensate` 仍未被版式使用。
- [ ] `text-autospace` 零宽空格回退仍未实现。
- [ ] 中英混排视觉回归未完成。

## 十三、P2 - 未完成产品功能

- [ ] MP4 WebCodecs 逐帧编码。
- [ ] 动效 `seek(t)` / `duration()` / `keyframe()` 组件库。
- [ ] MotionBudget 六维参数缩放。
- [ ] FlowParticles、StepReveal、ChartReveal、FlowDiagram、FormulaStep、CodeType。
- [ ] 演讲者视图和计时。
- [ ] 用户模板包上传和七项校验器。
- [ ] 模板版式热加载。
- [ ] 自然语言指令转 JSON Patch。
- [ ] PDF/PPTX/HTML 完整溯源附录。
- [ ] 图表/表格导出静态降级明细。
- [ ] 导出按页增量重渲和缓存强化。

## 十四、P2 - 部署、数据库与文档

- [ ] Docker Compose 缺少 MinIO bucket 初始化。
- [ ] API Docker 镜像缺少 pandoc。
- [ ] 缺少完整服务健康检查和启动依赖。
- [ ] 缺少 `deck_versions.snapshot` GIN 索引。
- [ ] 缺少 shares/jobs/sessions 部分索引。
- [ ] 缺少 `doc_assets(document_id, sha256)` 并发约束。
- [ ] README 中项目书文件名、分享 API、主题上传 API 仍不一致。
- [ ] README 和 `.env.example` 仍以 mock 为默认模式。
- [ ] 新增配置项未全部同步到部署文档。

## 十五、测试补强

- [ ] 使用真实配置文件和真实 Key 跑通完整验收流程。
- [ ] 单独建立真实 DeepSeek 集成测试，不在普通单元测试中混用。
- [ ] 检查 Key 不进入前端构建、日志、错误响应和 Git。
- [ ] 增加 `SecretStr` 误打印测试。
- [ ] 增加缺少 Key 时启动失败测试。
- [ ] 增加真实 API 401/403/429/5xx 测试。
- [ ] 增加真实 API 首次非法、修复成功和最终降级测试。
- [ ] 增加 PageDraft 与 prompt 输出协议一致性测试。
- [ ] 增加 source 短数字绕过测试。
- [ ] 增加多表格来源映射测试。
- [ ] 增加旧 schema 回放/迁移测试。
- [ ] 增加空版本 UI 不可回退测试。
- [ ] 增加回退后重新生成测试。
- [ ] 增加并发 Patch seq 冲突测试。
- [ ] 增加分享 auth_fail 写入 share_access_logs 测试。
- [ ] 增加真实 render-svc PDF/GIF/PPTX 测试。
- [ ] 增加编辑态与导出态样式快照测试。
- [ ] 增加 cleanup 存储失败测试。
- [ ] 增加 usage ledger 单次调用单次计量测试。
- [ ] 增加长文档和大资产列表测试。
- [ ] 增加任务超时、重复 enqueue、reclaim、取消和续跑测试。
- [ ] 增加前端 Playwright 端到端测试。
- [ ] 增加真实 5 份 Word 文档和真实 DeepSeek 回归。

## 建议下一轮修复顺序

1. 创建本地 `.env`，配置真实 `DEEPSEEK_API_KEY` 和 `LLM_PROVIDER=deepseek`。
2. 增加 Key 必填校验、`SecretStr` 和真实 API 集成测试。
3. 修复 usage ledger 重复计量，再执行真实模型验收。
4. 建立统一编辑/导出渲染，修复 styleOverride、PPTX 和 GIF。
5. 修复旧 schema 兼容、空版本 UI、idempotency 和并发 Patch。
6. 修复分享 auth_fail、任务超时/幂等/reclaim 和 cleanup 顺序。
7. 修复长文档截断、OMML 图片降级和上传安全。
8. 完成字体/CJK、播放器步进、前端编辑和真实导出验收。
9. 最后实现 MP4、动效库、模板包和 Docker 全链路验收。
