# Presenta 第五轮验收整改清单

> 基线：`README.md`、项目书 PDF、`AGENTS.md`、`todolist1.md` 至 `todolist4.md`、本轮更新后的代码与测试。
>
> 结论：本轮大幅补齐了 Key 安全、JOBS、清理、分享、计量、迁移和 CI，但整体验收仍不通过。真实 DeepSeek Key 仍未配置，真实 API 未运行；ARQ worker 当前无法启动；cleanup 存在删除原始文档的数据丢失风险；`mypy` 和仓库级 `ruff` 未通过；编辑/导出保真、字体、长文档和前端功能仍未完成。

## 一、本轮实际检查结果

### 通过的检查

- [x] `pytest -q`：54 项普通测试通过，2 项真实 DeepSeek 测试被排除。
- [x] 前端 `typecheck`、`lint`、生产构建通过。
- [x] `ruff check app` 通过。
- [x] 空数据库 Alembic `upgrade -> downgrade -> upgrade` 通过。
- [x] mock 冒烟流程通过。
- [x] `check_no_secrets.py` 当前扫描结果为未发现明显 Key。
- [x] `.env` 已加入 `.gitignore`。
- [x] 当前前端构建产物中未发现 `DEEPSEEK_API_KEY` 或明显的 hardcoded Key。

### 未通过的检查

- [ ] **真实 Key 未配置，真实 DeepSeek 验收未执行。**
- [ ] 仓库根目录 `.env` 不存在。
- [ ] `backend/.env` 不存在。
- [ ] 当前进程环境中的 `DEEPSEEK_API_KEY` 为空。
- [ ] `scripts/smoke_deepseek.py` 在当前环境下退出码为 2。
- [ ] `pytest -m deepseek -q` 结果为 2 skipped，没有真实调用。
- [ ] `ruff check app tests` 失败，`tests/test_deepseek_integration.py` 导入顺序不符合规则。
- [ ] `mypy app` 失败，当前有 16 个错误。
- [ ] ARQ WorkerSettings 导入即抛 `TypeError`，worker 无法启动。
- [ ] 有历史重复 `doc_assets` 时，新迁移会因唯一约束失败。
- [ ] cleanup 实测会删除仍被 `Document.original_key` 引用的原始文档对象。

## 二、真实 API Key 硬性要求

### 配置现状

- [ ] **本版验收硬性要求“从配置文件读取真实 DeepSeek Key”仍未完成。**
- [ ] 必须创建本地 `.env`，不能在仓库内保存真实 Key。
- [ ] `.env` 中必须设置 `LLM_PROVIDER=deepseek`。
- [ ] `.env` 中必须设置真实 `DEEPSEEK_API_KEY`。
- [ ] `DEEPSEEK_BASE_URL` 和 `DEEPSEEK_MODEL` 必须与项目书一致。
- [ ] 应用应从根目录 `.env` 或 `backend/.env` 读取上述配置。
- [ ] 当前应用配置读取路径已经支持这两个文件，但实际文件均不存在。

### 配置代码问题

- [x] `deepseek_api_key` 已改为 `SecretStr`。
- [x] `llm_provider` 默认值已改为 `deepseek`。
- [x] 缺少 Key 时，API lifespan 会拒绝启动。
- [x] 日志只输出 Key 是否配置，不输出 Key 内容。
- [x] Docker Compose 已要求提供 `DEEPSEEK_API_KEY`。
- [x] Docker 默认 provider 已改为 `deepseek`。
- [ ] `.env.example` 当前值 `请填入真实 Key（不要提交到仓库）` 会被识别为“Key 已配置”。
- [ ] 实测把该占位字符串作为 Key 后，`deepseek_api_key_configured` 返回 `true`。
- [ ] 增加占位值、空白值和明显非法格式校验，不能仅判断非空。
- [ ] 建议校验 DeepSeek Key 前缀/长度，并拒绝 `.env.example` 占位文本。
- [ ] 增加 SecretStr 不会在 repr、日志、异常中泄露的测试。
- [ ] 增加缺少 Key 时启动失败的测试。

### 真实 API smoke 脚本

- [ ] `scripts/smoke_deepseek.py` 在导入 `settings` 前直接检查 `os.environ`。
- [ ] 因此只把 Key 写入 `.env`、未导出到 shell 时，脚本仍会错误退出 2。
- [ ] smoke 脚本应改为读取 `settings.deepseek_api_key_configured` 和实际 SecretStr。
- [ ] 文档中的 `DEEPSEEK_API_KEY=sk-...` 命令会进入 shell history，应改为从 `.env` 读取。
- [ ] `tests/test_deepseek_integration.py` 同样从 `os.environ` 读取 Key，不会读取 `.env`。
- [ ] 真实测试 fixture 应使用应用 Settings，而不是环境变量快照。
- [ ] 保留 CI secret 注入能力，但本地和配置文件路径必须一致。

### 真实 API 测试有效性

- [ ] `test_real_outline_and_page` 没有强制要求 `DEEPSEEK_REAL_NETWORK=1`；只要 shell 有 Key 就可能发起网络调用。
- [ ] 应统一显式网络开关。
- [ ] `smoke_deepseek.py` 即使全部页面 `degraded` 仍可能返回成功。
- [ ] 真实 smoke 应在出现非预期 degraded 页时失败。
- [ ] 真实 smoke 应确认至少生成一个图表页、关键数字页和引用页，不能只依赖模型自由选择。
- [ ] 真实 smoke 应覆盖“首次非法、第二次修复成功”。
- [ ] 真实 smoke 应覆盖“两次修复后仍非法并降级”。
- [ ] 真实测试应确认 usage ledger 每次上游调用只记录一次。
- [ ] 当前 Key 为空，以上均未验收。

## 三、P0 - 当前阻断项

### ARQ Worker 无法启动

- [ ] `backend/app/workers/arq_settings.py` 当前导入失败。
- [ ] 实测错误：`TypeError: Function.__init__() got multiple values for argument 'name'`。
- [ ] 当前 ARQ `Function` 签名是 `Function(name, coroutine, timeout_s=...)`。
- [ ] 代码错误地写成 `Function(callable, name="...", timeout=...)`。
- [ ] 所有 Function 都必须改为正确的位置参数和 `timeout_s`。
- [ ] `mypy` 对上述错误有 16 个明确报告。
- [ ] 增加 WorkerSettings 导入测试。
- [ ] Docker `worker` 当前必然启动失败，完整异步链路不可用。

### Cleanup 数据丢失

- [ ] cleanup 扫描 `documents` 前缀下所有旧对象。
- [ ] 引用集合只收集 `DocAsset.storage_key`。
- [ ] 没有收集 `Document.original_key`。
- [ ] 实测一个仍关联 `Document.original_key` 的原始文件在 cleanup 后被删除。
- [ ] 实测 `orphanAssets=1`，对象在 cleanup 后不存在。
- [ ] 这会导致后续重新解析、更新、恢复或审计失去原始文档。
- [ ] 修复前必须禁止在生产环境运行新增 orphan cleanup。
- [ ] 引用集合必须包含 `Document.original_key`。
- [ ] 引用集合还必须包含 `DocAsset.meta.aliases` 中仍被使用的对象 key。
- [ ] orphan 宽限期当前固定为 1 天，项目书要求 7 天。
- [ ] 使用配置项控制 orphan 宽限期，并在测试中覆盖原始文档和别名对象。
- [ ] 删除对象前应执行“对象 key 已被数据库任一路径引用”的完整检查。

### 编辑态与导出态

- [ ] 导出 HTML/PDF 仍只使用 `slide.slots`，没有读取 `slide.elements`、`styleOverride` 和 Element layout。
- [ ] 用户在画布中的字号、颜色、对齐和位置修改仍会从 PDF/GIF/HTML 中消失。
- [ ] PPTX 仍只输出标题、正文和页脚三个文本框。
- [ ] PPTX 仍未插入图片、图表、表格、GIF 和元素动效。
- [ ] GIF 仍只截取每页一张静态图并重复。
- [ ] GIF 仍没有逐帧 `seek(t)`。
- [ ] 深色主题 GIF 仍只提示浅底，没有实际换底。
- [ ] 导出降级未按页、按元素输出。
- [ ] `degraded_details` 数据库字段已新增，但 `create_export()` 从未赋值。
- [ ] `ExportArtifactView` 和前端没有暴露 degraded details。
- [ ] 必须建立统一编辑/导出 renderer 和逐页降级明细。

### Build Gate 失败

- [ ] `ruff check app tests` 失败，CI 会变红。
- [ ] 修复 `test_deepseek_integration.py` 的 import ordering。
- [ ] `mypy app` 失败，共 16 个错误。
- [ ] 修复 `Result.rowcount` 类型问题。
- [ ] 修复 ARQ Function 类型和参数问题。
- [ ] 提交前门禁必须恢复为 `ruff + mypy + pytest + frontend` 全绿。
- [ ] CI 当前会真实失败，不能把本地 54 项 pytest 通过视为交付通过。

## 四、P1 - 迁移与数据一致性

- [ ] `uq_doc_assets_document_sha` 在历史重复数据存在时会导致迁移失败。
- [ ] 实测插入两条相同 `(document_id, sha256)` 记录后，升级迁移报 UNIQUE constraint failed。
- [ ] 迁移前需要合并重复资产、迁移 sourceRef/aliases/引用并保留数据。
- [ ] 增加非空历史数据库升级测试。
- [ ] 增加迁移 downgrade 后数据可恢复测试。
- [ ] schema v2 已增加图表 derived 迁移逻辑，但没有旧 snapshot 迁移测试。
- [ ] 需要验证旧 v1 图表、关键数字和图片 provenance。
- [ ] Deck provenance 也应参与 v1 迁移测试。
- [ ] `expected_seq` 已加入 API，但前端 Patch 尚未发送 expectedSeq。
- [ ] 数据库行锁只对 PostgreSQL 生效；SQLite 使用进程内锁，多进程仍不安全。
- [ ] 本地锁字典没有回收，长期运行存在内存增长风险。
- [ ] 并发 `create_job` 的 batch 并发计数不是原子检查，仍可能超过配置上限。

## 五、P1 - JOBS 与 Worker

- [ ] WorkerSettings 导入崩溃必须先修复。
- [ ] `enqueue_job()` 在任务事务尚未提交时使用新 Session 查询 job。
- [ ] 新 Session 看不到未提交 job，会默认按 batch_generate 选择 ARQ function。
- [ ] ingest/export 可能进入错误的 function 超时包装。
- [ ] ARQ 入队失败时抛错，但调用方事务随后回滚，所谓“任务已保留为排队状态”不成立。
- [ ] 需要 outbox、提交后再入队或显式隔离事务。
- [ ] `persist_partial` 已保存完成页，但重试时 `generate_pages()` 仍从空列表开始。
- [ ] 断点续跑实际未实现。
- [ ] partialSlides 每次按页全量写入 job.result，有较大 JSON 写放大。
- [ ] `create_export()` 取消时抛 ConflictError，worker 会按普通失败处理，可能重试而不是 cancelled。
- [ ] `_mark_failure()` 未优先检查 cancel_requested。
- [ ] `_mark_failure()` 重新入队失败时，任务可能停在 queued 且没有 ARQ 消息。
- [ ] Worker healthcheck 只检查 Redis，不检查 ARQ worker 是否存活。
- [ ] 任务超时、取消、重复入队、partial resume 均没有新增测试。

## 六、P1 - 清理、资产与上传

- [ ] cleanup 原始文档误删问题属于 P0，先于其他清理功能修复。
- [ ] orphan cleanup 仍可能删除图片别名对象。
- [ ] `ref_count` 仍未维护。
- [ ] 重复图片创建 alias object，但数据库没有第二个 assetId 对应的 DocAsset。
- [ ] Markdown 仍可能引用不存在于资产表的第二个 assetId。
- [ ] 需要为同一图片的每次出现保留独立 sourceRef 或显式别名映射。
- [ ] `max_docx_uncompressed_mb` 配置新增但未被上传或解析代码使用。
- [ ] `max_docx_compression_ratio` 配置新增但未被使用。
- [ ] DOCX zip 展开炸弹防护仍未实现。
- [ ] MIME 白名单仍未实现。
- [ ] `max_deck_pages` 仍未在生成或大纲流程中执行。

## 七、P1 - 分享与安全

- [x] 错误分享密码开始写独立 ShareAccessLog。
- [x] 分享失败审计和 access log 有独立事务。
- [x] ShareToken 支持滑动续期。
- [x] 过期 Token 进入 cleanup。
- [x] S3 分享下载使用短时效签名 URL。
- [x] 文件下载再次检查格式白名单。
- [ ] `download_lock` 只是进程内 `asyncio.Lock`，多 API 实例之间不互斥。
- [ ] 分享 PDF/PPTX/GIF 下载仍在请求内同步渲染。
- [ ] 签名 URL 签发后，分享被吊销仍可能在下发 TTL 内继续访问。
- [ ] auth_fail/share token/滑动过期/签名 URL 仍缺少端到端测试。
- [ ] `audit_isolated` 失败只更新进程内指标和日志，没有持久化告警。
- [ ] 进程内 metrics 不跨 worker 实例聚合。

## 八、P1 - DeepSeek 计量与错误处理

- [x] usage ledger 开始记录 upstream_call_id。
- [x] 成功和 schema 失败不再对同一次调用写两条 usage。
- [x] 401/403/429/5xx 开始使用明确 error_code。
- [x] 错误响应不再拼接上游正文。
- [ ] 真实 Key 缺失，计量修复未通过真实调用验证。
- [ ] `existing_usage()` 已定义但未使用，重复 upstream_call_id 可能触发唯一约束异常。
- [ ] 429 多次 HTTP 尝试只写一条最终 usage，需要明确是否按调用或按最终请求计量。
- [ ] response.json() 失败、DeepSeek 返回非预期 JSON 结构等路径测试不足。
- [ ] `smoke_deepseek` 对 degraded 页和调用次数的断言不足。

## 九、P1 - 长文档和页面生成

- [ ] 大纲仍只处理前 60 个章节。
- [ ] 章节摘要仍是前 240 字符截断。
- [ ] 章节进入大纲前仍截断到 4000 字符。
- [ ] 页面仍只读取单章前 6000 字符。
- [ ] 资产列表仍限制 24 个，并以 8000 字符截断。
- [ ] 大纲 SSE item 仍在完整生成后统一发出。
- [ ] OMML 失败仍只写占位文本，没有裁剪图片。
- [ ] 长文档分块摘要和断点续跑仍未实现。

## 十、P1 - 前端与播放

- [ ] 播放器 step 仍未传入 iframe。
- [ ] “下一步”不会改变幻灯片画面。
- [ ] 转场仍只是标签展示。
- [ ] 版本时间轴仍无分支、diff 和分页 UI。
- [ ] 前端 Patch 未发送 expectedSeq。
- [ ] 大纲仍不能拖拽、新增和重新绑定章节。
- [ ] Monaco 双向定位仍未实现。
- [ ] 12 列栅格拖拽仍未实现。
- [ ] 图片替换、表格编辑和富文本白名单仍未实现。
- [ ] 样式面板仍只有字号、颜色和对齐。
- [ ] 导出面板没有 degraded details。
- [ ] MP4 仍不可用。

## 十一、P2 - 字体与 CJK

- [ ] 未接入统一字体文件和子集。
- [ ] 未提供 `@font-face`。
- [ ] 未在导出前校验字体 manifest 版本。
- [ ] 未实现字形覆盖检查。
- [ ] 中文 ×1.03 字号补偿仍未实际应用。
- [ ] `.cjk-compensate` 和 `--cjk-scale` 仍没有版式使用位置。
- [ ] `text-autospace` 零宽空格回退仍未实现。
- [ ] 尚未完成中英混排视觉回归。

## 十二、P2 - 尚未完成的产品功能

- [ ] MP4 WebCodecs 逐帧导出。
- [ ] 动效组件库和纯函数式 `seek(t)`。
- [ ] MotionBudget 六维缩放。
- [ ] 六类内置动效组件。
- [ ] 演讲者视图和计时。
- [ ] 用户模板包上传和七项校验器。
- [ ] 模板版式热加载。
- [ ] 自然语言指令转 JSON Patch。
- [ ] PDF/PPTX/HTML 完整溯源附录。
- [ ] 图表/表格导出静态降级明细。
- [ ] 按页增量重渲和缓存强化。

## 十三、P2 - Docker、文档与安全扫描

- [ ] Docker Compose 无法在当前环境实测，因为本机没有 Docker。
- [ ] MinIO bucket 初始化已添加，但尚未实跑。
- [ ] API 镜像已添加 pandoc。
- [ ] Redis、MinIO、render-svc、API、worker healthcheck 已添加。
- [ ] ARQ worker 当前导入崩溃，即使 Docker 配置正确也无法启动。
- [ ] README 仍把 mock 描述为默认开发模式，与 `.env.example` 的 deepseek 默认不一致。
- [ ] README 未说明从配置文件读取真实 Key 的验收流程。
- [ ] `check_no_secrets.py` 的 `ROOT` 是 `backend/`，没有扫描整个仓库。
- [ ] 因此 CI 的 secret scan 不会检查 `web/`、根目录配置或 Docker 文件。
- [ ] 将扫描根目录改为仓库根。
- [ ] 增加 `.env.example` 占位值、Web bundle、Source Map 和 Docker Compose 的泄露检查。

## 十四、测试补强

- [ ] 增加真实 `.env` 配置读取测试。
- [ ] 增加占位 Key 被拒绝测试。
- [ ] 增加 SecretStr 日志/repr 泄露测试。
- [ ] 增加缺少 Key 时 lifespan 启动失败测试。
- [ ] 增加 WorkerSettings 导入和 ARQ Function 签名测试。
- [ ] 恢复 `ruff check app tests` 全绿。
- [ ] 恢复 `mypy app` 全绿。
- [ ] 使用包含历史重复资产的数据库测试迁移。
- [ ] 增加旧 v1 Deck snapshot 迁移测试。
- [ ] 增加 cleanup 不删除 `Document.original_key` 测试。
- [ ] 增加 cleanup 不删除 aliases 对象测试。
- [ ] 增加 7 日 orphan 宽限测试。
- [ ] 增加 ARQ enqueue 事务可见性测试。
- [ ] 增加 partialSlides 真正恢复测试。
- [ ] 增加 export 取消状态测试。
- [ ] 增加 share auth_fail、token 续期、Token cleanup、签名 URL 测试。
- [ ] 增加 degraded_details 生成/API/UI 测试。
- [ ] 增加真实 DeepSeek smoke 从 `.env` 读取 Key 测试。
- [ ] 增加真实 DeepSeek 图表、关键数字、引用、修复和降级测试。
- [ ] 增加真实 render-svc PDF/GIF/PPTX 测试。
- [ ] 增加编辑态与导出态快照对比测试。
- [ ] 增加前端 Playwright 端到端测试。
- [ ] 增加 5 份真实 Word 回归。

## 建议下一轮修复顺序

1. 创建本地 `.env`，配置真实 `DEEPSEEK_API_KEY` 和 `LLM_PROVIDER=deepseek`。
2. 修复 smoke/integration 从 `.env` 读取 Key，并拒绝占位值。
3. 修复 ARQ WorkerSettings 导入崩溃和相关 mypy/ruff 错误。
4. 立即修复 cleanup 误删原始文档和别名对象的数据丢失风险。
5. 修复迁移对历史重复资产的兼容性。
6. 修复 degraded_details、enqueue 事务可见性、取消和 partial resume。
7. 建立统一编辑/导出渲染，修复 styleOverride、PPTX 和 GIF。
8. 修复分享并发锁、长文档、OMML 和上传防护。
9. 完成字体/CJK、播放器、前端编辑和真实导出验收。
10. 最后执行真实 DeepSeek、真实 render-svc、Docker 和 5 份 Word 文档全链路验收。
