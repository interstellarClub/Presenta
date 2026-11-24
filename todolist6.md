# Presenta 第六轮验收整改清单

> 基线：`README.md`、项目书 PDF、`AGENTS.md`、`todolist1.md` 至 `todolist5.md`、本轮更新后的代码与测试。
>
> 结论：本轮修复了 WorkerSettings、构建门禁、cleanup 原始文档误删、迁移去重和降级详情等关键问题，但整体验收仍不通过。真实 DeepSeek Key 仍未配置；导出 `styleOverride` 存在 HTML 注入漏洞；编辑样式仍未正确映射到导出；GIF 仍忽略新增的逐帧参数；播放器 step 仍没有 iframe 消费端。

## 一、本轮实际检查结果

### 通过的检查

- [x] `pytest -q`：72 passed，2 个真实 DeepSeek 测试被排除。
- [x] `ruff check app tests` 通过。
- [x] `mypy app` 通过。
- [x] 前端 `typecheck`、`lint`、生产构建通过。
- [x] 空数据库 Alembic `upgrade -> downgrade -> upgrade` 通过。
- [x] WorkerSettings 可成功导入，5 个 ARQ function 已注册。
- [x] mock 冒烟流程通过。
- [x] `check_no_secrets.py` 扫描整个仓库且未发现明显 Key。
- [x] cleanup 手工复现确认不会删除 `Document.original_key`。
- [x] 历史重复 `doc_assets` 的空库迁移测试通过。
- [x] degraded_details 已从 DB 写入 API，并显示到导出面板。
- [x] 前端 Patch 已发送 expectedSeq。

### 未通过的检查

- [ ] **真实 DeepSeek Key 未配置，真实 API 仍未执行。**
- [ ] `.env` 和 `backend/.env` 均不存在。
- [ ] 当前进程 `DEEPSEEK_API_KEY` 为空。
- [ ] 当前 provider 为 deepseek，但 `deepseek_api_key_configured=false`。
- [ ] `scripts/smoke_deepseek.py` 当前退出码为 2。
- [ ] `pytest -m deepseek -q` 为 2 skipped。
- [ ] 真实 API、真实计量、真实修复和降级均未验收。
- [ ] 导出 `styleOverride` 可注入任意 HTML。
- [ ] 导出样式 overlay 对实际 Inspector 创建的元素无效。
- [ ] GIF render-svc 仍忽略 frameTimes/slideSteps/darkTheme。
- [ ] 播放器 step 消息仍没有 iframe 端处理器。

## 二、P0 - 真实 API Key 与真实调用

### 配置文件

- [ ] 创建本地 `.env`，不能提交到 Git。
- [ ] 设置 `LLM_PROVIDER=deepseek`。
- [ ] 设置真实 `DEEPSEEK_API_KEY`。
- [ ] 设置 `DEEPSEEK_MODEL=deepseek-flash`。
- [ ] 设置 `DEEPSEEK_BASE_URL=https://api.deepseek.com`。
- [ ] 确认应用从根 `.env` 或 `backend/.env` 读取 Key。
- [ ] 当前 `.env` 缺失导致 API 默认配置无法通过 lifespan。
- [ ] 真实 API 验收完成前不能把本版标记为通过。

### 已完成的 Key 安全措施

- [x] `deepseek_api_key` 已改为 `SecretStr`。
- [x] 默认 provider 已改为 deepseek。
- [x] 占位 Key 和过短 Key 会被拒绝。
- [x] 缺少/占位 Key 时 lifespan 会失败。
- [x] 日志只显示是否配置。
- [x] smoke 与真实测试开始读取 Settings。
- [x] secret scanner 已扫描整个仓库。
- [ ] 增加真实 `.env` 文件读取集成测试。
- [ ] 增加 CI 和本机均使用相同配置路径的验证。

### 真实 API 测试质量

- [ ] `test_real_outline_and_page` 仍未强制 `DEEPSEEK_REAL_NETWORK=1`。
- [ ] 只要 shell 中出现 Key，该测试就可能直接访问网络。
- [ ] 应统一要求 Key 和显式网络开关同时存在。
- [ ] `smoke_deepseek.py` 即使所有页面 degraded 仍返回成功。
- [ ] smoke 必须在非预期 degraded 页出现时失败。
- [ ] smoke 应强制覆盖图表页、关键数字页和引用页。
- [ ] smoke 应覆盖首次非法、第二次修复成功。
- [ ] smoke 应覆盖两次修复后降级。
- [ ] smoke 应验证每个 upstream_call_id 只生成一条 usage。
- [ ] 当前 Key 为空，以上均未执行。

## 三、P0 - 导出 HTML 注入

- [ ] **`styleOverride` 值未经转义直接拼进 HTML `style` 属性。**
- [ ] Patch API 接受任意字符串作为 styleOverride 值。
- [ ] Pydantic 只校验 styleOverride 的 key，不校验 value。
- [ ] 实测可写入 `background: red"><img src=x onerror=alert(1)>`。
- [ ] `render_slide_html()` 会输出真实 `<img onerror>`。
- [ ] 独立 HTML 下载后可直接执行注入脚本。
- [ ] render-svc 也会接收同一未过滤内容和更多用户正文。
- [ ] 这违反“不得开放用户自定义 JS”的红线。
- [ ] 为每个样式属性定义值白名单或严格类型解析。
- [ ] 禁止引号、尖括号、反斜杠、分号、`url()`、`expression()` 和任意函数表达式。
- [ ] HTML 属性输出必须使用 `html.escape(..., quote=True)`。
- [ ] 增加导出 HTML 的 CSP，禁止 inline script 和外链资源。
- [ ] 增加恶意 styleOverride 负向测试。

## 四、P0 - 编辑态与导出态

### Style overlay 实现错误

- [ ] `_render_elements()` 只渲染 `layout != null` 的 Element。
- [ ] Inspector 新建样式 Element 时固定写入 `layout: null`。
- [ ] 因此用户最常见的字体、颜色、对齐修改不会进入导出。
- [ ] 实测 `fontSize: 99px` 在 layout 为 null 时完全不出现在 HTML 输出中。
- [ ] 有 layout 时虽然输出 99px，但 Element 内容为空。
- [ ] text/chart/table 等元素只生成空占位 `<span>`。
- [ ] image Element 以 `element.id` 查图片，而实际图片 key 是 media assetId。
- [ ] `.element-layer` 没有对应 CSS。
- [ ] overlay 被拼在 base layout 之后而不是作为 slide 内部覆盖层。
- [ ] 独立 HTML 中 slide 容器没有 `position: relative`，绝对定位可能错误。
- [ ] 对已有 slot 的 styleOverride，应生成对应 `[data-slot="..."]` 规则，而不是创建空 Element。
- [ ] 对真正自由布局 Element，应输出真实文本、图片、图表和表格内容。
- [ ] 统一编辑 iframe 与导出 renderer，禁止维护两套不一致的渲染逻辑。
- [ ] 增加编辑后 HTML/PDF/GIF/PPTX 快照对照测试。

### PPTX

- [x] split/full-image 图片开始插入 PPTX。
- [x] table 开始插入 PPTX。
- [ ] chart 分支仍只把文本标记为 media inserted，没有插入图表图片。
- [ ] PPTX 不使用 styleOverride 或 Element layout。
- [ ] 图片固定放在右侧，正文仍是 11.5 英寸宽，可能发生重叠。
- [ ] 全图、左右分栏、上下分栏没有对应 PPT 排版。
- [ ] 元素动效没有 GIF 化。
- [ ] notes 中“已插入媒体内容”不能证明视觉布局正确。
- [ ] 仍需真实 PowerPoint/WPS 打开验收。

### GIF

- [ ] backend 已发送 `frameTimes`、`slideSteps`、`darkTheme`。
- [ ] render-svc 的 GifRequest 没有接收这些字段。
- [ ] render-svc 仍每页只截一张图，再复制相同帧。
- [ ] 帧时间没有驱动 `seek(t)`。
- [ ] steps 没有驱动 fragment/frame 状态。
- [ ] darkTheme 没有改变背景。
- [ ] 后端仍会追加“深色主题已自动换浅底”的说明，但实际未换底。
- [ ] 这属于静默且虚假的 fidelity 声明。

### 播放器

- [ ] `SlideFrame` 已发送 `presenta:step` postMessage。
- [ ] `slideHtml` iframe bridge 没有处理 `presenta:step`。
- [ ] 实测全仓库只有发送端，没有消费端。
- [ ] 点击下一步仍不会改变幻灯片画面。
- [ ] 转场仍只是标签展示。

## 五、P1 - JOBS 与事务

- [x] WorkerSettings 导入错误已修复。
- [x] ARQ Function 使用 `timeout_s`。
- [x] WorkerSettings 导入测试已添加。
- [x] 按任务类型超时已实现。
- [x] reclaim 改为每分钟巡检。
- [x] heartbeat 在本地和队列模式均启动。
- [x] Job claim 使用 UPDATE 条件实现基本原子领取。
- [x] partialSlides 已支持重试时恢复。
- [x] 导出取消会优先标记 cancelled。
- [ ] Job 创建仍然是 flush 后立即 enqueue，事务尚未提交。
- [ ] ARQ worker 可能在 commit 前收到消息，`_claim_job` 查不到 queued job 后直接返回。
- [ ] 此时消息被消费而数据库任务仍 queued，没有补偿。
- [ ] 需要 outbox/提交后 enqueue/事务提交回调。
- [ ] enqueue 失败时异常回滚数据库事务，但错误文案声称“任务已保留为排队状态”。
- [ ] `create_job` 的 batch 并发计数仍不是原子检查，并发请求可能超过上限。
- [ ] `_mark_failure` 重新入队失败仍可能让任务停在 queued 且没有消息。
- [ ] Worker healthcheck 只验证 Redis，不验证 ARQ worker 存活。
- [ ] JOBS 超时、取消、部分恢复和 queue 可见性仍无端到端测试。

## 六、P1 - 迁移与资产一致性

- [x] 迁移前会合并重复 doc_assets。
- [x] 历史重复资产的迁移不再触发唯一约束失败。
- [x] v1 Deck provenance 迁移测试已添加。
- [ ] dedup 迁移只保留被选中的 `storage_key`。
- [ ] 被删除重复行的 `storage_key` 没有写入 aliases。
- [ ] 实测 key1/key2 两条重复记录迁移后只剩 key1，key2 完全丢失引用。
- [ ] 被删除 duplicate asset id 可能仍存在于 `normalized_md` 的 `asset://` 引用。
- [ ] 被删除 duplicate asset id 可能仍存在于 deck_versions snapshot。
- [ ] 迁移没有重写文档、Slide、Element 中的 assetId。
- [ ] 迁移没有合并 sourceRef。
- [ ] 迁移没有保留重复文件对象用于后续恢复。
- [ ] 增加迁移后 Markdown/Deck 引用仍可解析测试。
- [ ] 增加迁移后所有历史 storage key 均有 alias 或清理策略测试。
- [ ] 唯一约束迁移在 PostgreSQL 真实数据副本上验证。

## 七、P1 - 长文档与数据完整性

- [ ] 配置上限已扩大，但仍会静默截断。
- [ ] 大纲最多 120 个章节，第 121 个及以后仍被丢弃。
- [ ] 摘要仍是前 480 字符截断，不是分块摘要。
- [ ] 大纲章节正文仍截断到 8000 字符。
- [ ] 页面章节正文仍截断到 12000 字符。
- [ ] 资产仍最多 48 个并截断到 16000 字符。
- [ ] 截断时没有告警、degraded 标记或分块处理。
- [ ] 大纲 SSE 仍在完整生成后统一发 item。
- [ ] OMML 失败只保存原始 XML 和占位文本，没有按项目书生成裁剪图片。
- [ ] 二次处理或后续重试 OMML 的流程未实现。
- [ ] 重复图片仍可能产生文档里的 assetId 与 DB 资产不一致。
- [ ] `ref_count` 已累加，但没有完整消费/释放语义。

## 八、P1 - 分享与下载

- [x] auth_fail 已写独立 ShareAccessLog。
- [x] ShareToken 支持滑动续期。
- [x] 过期 token 进入 cleanup。
- [x] S3 使用短时签名下载 URL。
- [x] 文件下载检查分享格式白名单。
- [ ] download_lock 仅是进程内锁，多实例不互斥。
- [ ] 分享 PDF/PPTX/GIF 仍在 HTTP 请求内同步渲染。
- [ ] 签名 URL 签发后，在 TTL 内仍可访问已吊销分享的产物。
- [ ] auth_fail、token 续期、cleanup、签名 URL 仍无端到端测试。
- [ ] 进程内 metrics 不跨 API 实例聚合。

## 九、P1 - 前端编辑与版本

- [x] 样式面板已增加字重、行高、字距、内距、圆角、透明度和背景。
- [x] Patch 已发送 expectedSeq。
- [x] 导出面板显示逐页 degraded details。
- [ ] Step iframe 消费端仍未实现。
- [ ] 转场仍不播放。
- [ ] 大纲仍不能拖拽、新增和重新绑定章节。
- [ ] Monaco 双向定位仍未实现。
- [ ] 12 列栅格拖拽仍未实现。
- [ ] 图片替换、表格编辑和富文本白名单仍未实现。
- [ ] 版本时间轴仍无分支、diff 和分页 UI。
- [ ] 空初始版本仍显示可点击回退。
- [ ] 版本时间轴不展示 degraded/anchor 等差异。

## 十、P2 - 字体与 CJK

- [ ] 仍未接入统一字体文件和字体子集。
- [ ] 仍无 `@font-face`。
- [ ] manifest 字体版本已校验，但实际字体文件没有接入。
- [ ] 无字形覆盖检查。
- [ ] 中文字号 = 西文字号 × 1.03 仍未实际应用。
- [ ] `.cjk-compensate` 和 `--cjk-scale` 仍无版式使用位置。
- [ ] `text-autospace` 零宽空格回退仍未实现。
- [ ] 中英混排视觉回归未完成。

## 十一、P2 - 尚未完成功能

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

## 十二、P2 - Docker、文档与 CI

- [ ] 当前机器没有 Docker，无法实测完整 Compose。
- [ ] WorkerSettings 已能导入，但仍需真实 ARQ+Redis 运行测试。
- [ ] MinIO bucket 初始化、health checks 未实跑。
- [ ] render-svc health 与真实 Chromium/FFmpeg 未实跑。
- [ ] README 已补充真实 Key 验收说明。
- [ ] README 仍保留 mock 为默认开发模式的旧示例。
- [ ] secret scanner 已扫描仓库根，但未扫描未跟踪 `.env` 内容。
- [ ] CI 真实 DeepSeek job 依赖仓库 secret，当前无法本地验收。
- [ ] CI 不含真实 Docker/render-svc/PowerPoint 验收。

## 十三、测试补强

- [ ] 创建真实 `.env` 并读取 Key 的验收测试。
- [ ] 真实 DeepSeek 网络开关双条件测试。
- [ ] 真实 DeepSeek 非预期 degraded 失败测试。
- [ ] 恶意 styleOverride HTML 注入测试。
- [ ] styleOverride 对现有 slot 的导出快照测试。
- [ ] 导出 overlay 文本、图片、图表内容测试。
- [ ] GIF frameTimes/slideSteps/darkTheme 真实测试。
- [ ] 播放器 step postMessage 消费测试。
- [ ] JOBS enqueue-before-commit 测试。
- [ ] partialSlides 恢复和取消测试。
- [ ] 历史资产迁移后 Markdown/Deck 引用完整性测试。
- [ ] cleanup 原始文件、aliases、7 日宽限自动化测试。
- [ ] share auth_fail、token 续期、cleanup、签名 URL 测试。
- [ ] 长文档 120+ 章节、超长章节和资产截断告警测试。
- [ ] OMML 失败裁剪图片测试。
- [ ] 真实 render-svc PDF/GIF/PPTX 测试。
- [ ] 真实 PPTX 打开与渲染测试。
- [ ] 前端 Playwright 端到端测试。
- [ ] 5 份真实 Word 文档回归。

## 建议下一轮修复顺序

1. 创建 `.env`，配置真实 Key 并执行真实 DeepSeek 验收。
2. 立即修复 styleOverride HTML/CSS 注入漏洞。
3. 重做导出样式映射，禁止通过空 overlay 代替 slot 样式。
4. 修复 GIF 逐帧与播放器 step。
5. 修复 JOBS enqueue 事务可见性和迁移资产引用完整性。
6. 补齐真实 DeepSeek、cleanup、分享和 JOBS 自动化测试。
7. 修复长文档截断、OMML 裁剪图和上传安全。
8. 完成字体/CJK、PPTX 保真和前端编辑功能。
9. 最后执行真实 Docker、render-svc、DeepSeek 和 5 份 Word 全链路验收。
