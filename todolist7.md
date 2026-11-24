# Presenta 第七轮验收整改清单

> 基线：`README.md`、项目书 PDF、`AGENTS.md`、`todolist1.md` 至 `todolist6.md`、本轮更新后的代码与测试。
>
> 结论：本轮关闭了 styleOverride HTML 注入、Worker 启动、构建门禁、cleanup 原始文件误删和迁移 storage alias 丢失等问题。但整体验收仍不通过：真实 DeepSeek Key 仍未配置；slot 样式在导出中会跨页污染；GIF 仍忽略逐帧参数；播放器 step 桥接仍不生效；PPTX 图表、长文档、字体和完整编辑能力仍未完成。

## 一、本轮实际检查结果

### 通过的检查

- [x] `pytest -q`：86 passed，2 个真实 DeepSeek 测试被排除。
- [x] `ruff check app tests` 通过。
- [x] `mypy app` 通过。
- [x] 前端 `typecheck`、`lint`、生产构建通过。
- [x] Alembic `upgrade -> downgrade -> upgrade` 通过。
- [x] WorkerSettings 可导入，5 个 ARQ function 已注册。
- [x] mock 冒烟流程通过。
- [x] `check_no_secrets.py` 未发现明显 Key。
- [x] cleanup 手工复现确认原始文档对象不再被误删。
- [x] 迁移会把重复资产 storage key 保存为 alias，不再直接丢失 key2。
- [x] 迁移会重写 deck_versions snapshot/patch 中的 assetId。
- [x] styleOverride 值注入 `<img onerror>` 已被拒绝。
- [x] 独立 HTML 已加入 CSP。
- [x] degraded_details 已写入 API 和 UI。
- [x] Patch 已发送 expectedSeq。
- [x] 播放器 iframe 已增加 `presenta:step` 处理代码。

### 未通过的检查

- [ ] **真实 DeepSeek Key 未配置，真实 API 仍未执行。**
- [ ] `.env` 与 `backend/.env` 不存在。
- [ ] 当前进程 `DEEPSEEK_API_KEY` 为空。
- [ ] `deepseek_api_key_configured=false`。
- [ ] 真实 smoke 退出码为 2。
- [ ] `pytest -m deepseek -q` 为 2 skipped。
- [ ] 导出 slot 样式选择器没有按 slide 隔离。
- [ ] GIF render-svc 仍不接受 frameTimes/slideSteps/darkTheme。
- [ ] 播放器 `interactive=false` 时 iframe bridge 不生成，step 仍失效。

## 二、P0 - 真实 API Key 与真实调用

### 配置

- [ ] 创建本地 `.env`，不能提交到 Git。
- [ ] 设置 `LLM_PROVIDER=deepseek`。
- [ ] 设置真实 `DEEPSEEK_API_KEY`。
- [ ] 设置 `DEEPSEEK_BASE_URL=https://api.deepseek.com`。
- [ ] 设置 `DEEPSEEK_MODEL=deepseek-flash`。
- [ ] 确认应用从 `.env` 读取真实 Key。
- [ ] 当前默认 provider 为 deepseek，但 Key 为空，API lifespan 将拒绝启动。
- [ ] 真实 Key 配置完成前不能通过本版验收。

### 已完成的 Key 安全措施

- [x] Key 使用 SecretStr。
- [x] 占位值和过短值会被拒绝。
- [x] 启动时校验 Key。
- [x] smoke 与集成测试开始读取 Settings。
- [x] secret scanner 扫描仓库根。
- [x] 前端构建未发现 Key。
- [ ] 增加读取真实 `.env` 的启动集成测试。
- [ ] 增加 Key 轮换和配置错误提示测试。
- [ ] 增加 CI 与本地配置读取路径一致性测试。

### 真实测试质量

- [ ] `test_real_outline_and_page` 仍未强制 `DEEPSEEK_REAL_NETWORK=1`。
- [ ] shell 中只要存在 Key，就可能直接发起网络请求。
- [ ] 应要求“有效 Key + 显式网络开关”同时满足。
- [ ] `smoke_deepseek.py` 仍可能在存在 degraded 页时返回成功。
- [ ] smoke 应强制失败于非预期 degraded 页。
- [ ] smoke 应覆盖图表页、关键数字页和引用页。
- [ ] smoke 应覆盖首次非法、第二次修复成功。
- [ ] smoke 应覆盖两次修复失败后降级。
- [ ] smoke 应确认 upstream_call_id 与 usage 一一对应。
- [ ] 当前 Key 缺失，以上均未执行。

## 三、P0 - 导出样式与安全

### 已修复

- [x] styleOverride 禁止引号、尖括号、反斜杠、分号和花括号。
- [x] styleOverride 禁止 url()、expression()、javascript:。
- [x] 样式值限定最大长度。
- [x] CSS 值经过 HTML 转义。
- [x] Element id/type/slotPath 输出经过转义。
- [x] image Element 使用 media assetId，不再使用 Element id 查图。
- [x] text Element 会输出真实 slot 内容。
- [x] 独立 HTML 增加严格 CSP。

### 未修复

- [ ] `_slot_style_rules()` 生成 `[data-slot="title"]` 全局选择器。
- [ ] 每页样式 `<style>` 在整份 HTML 中具有全局作用域。
- [ ] 第一页设置了标题颜色，会污染第二页及所有后续同名 slot。
- [ ] 实测 HTML 中存在全局 `[data-slot="title"] { color:red }`。
- [ ] 选择器必须使用 slide id 作用域，如 `[data-slide-id="..."] [data-slot="..."]`。
- [ ] 或在渲染阶段直接将样式内联到对应 slot，不生成全局 CSS。
- [ ] 增加“只修改第 1 页，不影响第 2 页”的导出测试。

### Free Element overlay

- [ ] `.element-layer` 已增加 absolute CSS。
- [ ] 但 overlay 仍是 `.layout` 的 sibling，而不是 layout 内部层。
- [ ] `.presenta-slide` 没有 `position: relative`。
- [ ] 独立 HTML 中 absolute Element 的定位基准可能不是当前 slide。
- [ ] render-svc 的 `.page` 有 position relative，PDF 路径与 standalone 不一致。
- [ ] chart/table 类型 free Element 仍输出空内容。
- [ ] 需要统一 CSS positioning 基准。
- [ ] 增加 standalone 与 PDF 的位置对比测试。

## 四、P0 - GIF

- [ ] backend 发送 frameTimes。
- [ ] backend 发送 slideSteps。
- [ ] backend 发送 darkTheme。
- [ ] render-svc `GifRequest` 没有 frameTimes 字段。
- [ ] render-svc 没有 slideSteps 字段。
- [ ] render-svc 没有 darkTheme 字段。
- [ ] render-svc 仍每页只截一张图。
- [ ] 仍把同一静态图复制成多帧。
- [ ] 仍不调用 seek(t)。
- [ ] 仍不改变深色主题背景。
- [ ] backend 仍会追加“深色主题已自动换浅底”说明。
- [ ] 当前说明与实际渲染不一致，属于虚假降级声明。
- [ ] 必须在 render-svc 内按 frameTimes 逐帧 seek。
- [ ] 必须按 slideSteps 控制 fragment 可见状态。
- [ ] 必须真正应用 darkTheme。
- [ ] 增加真实 FFmpeg 多帧差异测试。

## 五、P0 - 播放器 step

- [ ] SlideFrame 已发送 `presenta:step`。
- [ ] slideHtml 已增加 message listener 和 opacity 控制。
- [ ] 但 bridge 仅在 `interactive=true` 时生成。
- [ ] DeckPlayerPage 使用 `interactive=false`。
- [ ] 因此播放器 iframe 中没有任何 message listener。
- [ ] 点击“下一步”仍不会改变画面。
- [ ] 将 selection bridge 与 step bridge 解耦。
- [ ] 播放器模式也必须启用 step listener。
- [ ] mount 后首次 postMessage 可能早于 iframe load，需在 load 后补发当前 step。
- [ ] 目前只控制 `[data-fragment]`，没有根据 slide.steps 建立稳定映射。
- [ ] 非 bullets 布局没有 fragment 节点。
- [ ] 增加播放器 step Playwright 测试。

## 六、P1 - PPTX 与导出保真

- [x] split/full-image 图片开始插入 PPTX。
- [x] table 开始插入 PPTX。
- [ ] chart 分支仍只检查 chart 文本，没有插入图表图片。
- [ ] chart 仍只在正文 text box 中输出数据文本。
- [ ] PPTX 不使用 Element layout 或 styleOverride。
- [ ] 图片固定放在右侧，正文仍为总宽，存在重叠。
- [ ] full-image 没有铺满页面。
- [ ] split-lr/split-tb 没有对应版式。
- [ ] 元素动效仍未 GIF 化。
- [ ] “已插入媒体内容”不能证明版式正确。
- [ ] 需要 PowerPoint/WPS 真实打开验收。
- [ ] 需要编辑态与 PPTX 截图对比。

## 七、P1 - JOBS 事务与并发

- [x] WorkerSettings 导入已修复。
- [x] ARQ Function 参数已修复。
- [x] 按任务类型超时已实现。
- [x] claim 使用条件 UPDATE。
- [x] partialSlides 已用于重试恢复。
- [x] cancel_requested 会优先落到 cancelled。
- [ ] 创建 job 后仍先 flush 再 enqueue，事务尚未提交。
- [ ] ARQ worker 可能先收到消息，查不到 queued job 并直接返回。
- [ ] 消息已消费，数据库任务仍可能永久 queued。
- [ ] 需要 outbox 或 commit 后 enqueue。
- [ ] enqueue 失败会抛错并回滚 job 插入，但错误消息仍称“任务已保留”。
- [ ] batch 并发计数不是原子数据库检查。
- [ ] `_mark_failure()` 重新入队失败仍可能留下无消息的 queued 状态。
- [ ] Worker healthcheck 只检查 Redis，不检查 ARQ worker。
- [ ] 缺少 enqueue/commit 竞态测试。
- [ ] 缺少 partial resume、超时和取消测试。

## 八、P1 - 迁移与资产引用

- [x] 历史重复 doc_assets 可以完成迁移。
- [x] duplicate storage_key 已写入 aliases。
- [x] deck_versions snapshot/patch assetId 已重写。
- [ ] migration test 仍主要检查行数与 meta 非空。
- [ ] 未检查被保留的 key2 alias 值。
- [ ] 未检查 deck snapshot 中 duplicate assetId 是否全部改写。
- [ ] `documents.normalized_md` 中的 `asset://duplicateId` 没有改写。
- [ ] Document AST/编辑器中的资产引用没有检查。
- [ ] duplicate `sourceRef` 没有合并。
- [ ] 图床 API 仍不能通过 alias assetId 获取对象。
- [ ] 重复图片在 docx→Markdown 中仍可能产生第二个 DB 不存在的 assetId。
- [ ] 需要把 document Markdown/AST 一并纳入迁移与引用解析。
- [ ] 增加“迁移后所有 asset:// 均可解析”测试。

## 九、P1 - 长文档与解析

- [ ] 大纲默认最多 120 章节，超过后仍静默丢弃。
- [ ] 摘要仍是前 480 字符截断，不是分块摘要。
- [ ] 大纲章节正文仍截断到 8000 字符。
- [ ] 逐页正文仍截断到 12000 字符。
- [ ] 资产仍限制 48 个并截断到 16000 字符。
- [ ] 截断没有告警或 degraded 标记。
- [ ] 大纲 SSE item 仍在完整生成后统一发出。
- [ ] OMML 失败仍只保存原始 XML 和占位文本。
- [ ] 未生成项目书要求的公式裁剪图片。
- [ ] `maximum pages` 已用于大纲，但未定义超 500 页自动异步分批策略。

## 十、P1 - 分享与下载

- [x] auth_fail 写独立 share access log。
- [x] ShareToken 随机化和 hash 存储。
- [x] Token 支持 DB 滑动续期。
- [x] Token cleanup。
- [x] S3 签名 URL。
- [ ] 分享 Cookie 的浏览器 expires 不会因 DB 滑动续期而更新，滑续实际可能无效。
- [ ] download_lock 仅进程内有效，多 API 实例不互斥。
- [ ] 分享 PDF/PPTX/GIF 仍在 HTTP 请求内同步渲染。
- [ ] 签名 URL 在 TTL 内不能立即随分享吊销失效。
- [ ] auth_fail、续期、cleanup、签名 URL 仍无端到端测试。
- [ ] 进程内 metrics 不跨实例聚合。

## 十一、P1 - 前端编辑与版本

- [x] 样式面板已增加更多属性。
- [x] expectedSeq 已发送。
- [x] degraded details 已显示。
- [ ] step 在播放器中仍失效。
- [ ] 转场仍不播放。
- [ ] 大纲拖拽、新增和章节重绑定未实现。
- [ ] Monaco 双向定位未实现。
- [ ] 12 列栅格拖拽未实现。
- [ ] 图片替换、表格编辑、富文本白名单未实现。
- [ ] 版本分支/diff/分页 UI 未实现。
- [ ] 空初始版本仍显示可点击回退。
- [ ] 版本历史没有展示废弃分支。

## 十二、P2 - 字体与 CJK

- [ ] 统一字体文件和字体子集未接入。
- [ ] 无 `@font-face`。
- [ ] 缺少字形覆盖检查。
- [ ] 中文 ×1.03 字号仍未实际应用。
- [ ] `.cjk-compensate` 和 `--cjk-scale` 仍无版式使用位置。
- [ ] `text-autospace` 零宽空格回退未实现。
- [ ] 中英混排视觉回归未完成。

## 十三、P2 - 未完成功能

- [ ] MP4 WebCodecs 逐帧导出。
- [ ] 动效组件库和纯函数式 `seek(t)`。
- [ ] MotionBudget 六维缩放。
- [ ] 六类内置动效组件。
- [ ] 演讲者视图和计时。
- [ ] 用户模板包上传和七项校验器。
- [ ] 模板版式热加载。
- [ ] 自然语言指令转 JSON Patch。
- [ ] PDF/PPTX/HTML 完整溯源附录。
- [ ] 图表/表格静态降级明细。
- [ ] 按页增量重渲和缓存强化。

## 十四、P2 - Docker、文档与 CI

- [ ] 当前机器无 Docker，Compose 未实测。
- [ ] MinIO bucket 初始化未实跑。
- [ ] Redis/MinIO/render-svc/API worker health 未实跑。
- [ ] 真实 ARQ worker 未实跑。
- [ ] 真实 render-svc Chromium/FFmpeg 未实跑。
- [ ] README 已增加真实 Key 验收说明。
- [ ] README 仍保留 mock 为默认开发模式的旧命令。
- [ ] `.env.example` 真实 Key 为空/占位值，配置校验会拒绝。
- [ ] CI 真实 DeepSeek job 依赖 secret，当前无法验收。
- [ ] 无 Docker/render-svc/PowerPoint CI。

## 十五、测试补强

- [ ] 创建真实 `.env` 并读取 Key。
- [ ] 真实 DeepSeek 网络开关双条件测试。
- [ ] 真实 DeepSeek degraded 失败测试。
- [ ] 真实 DeepSeek 修复和最终降级测试。
- [ ] 导出 slot 样式按 slide 隔离测试。
- [ ] Free Element 在 standalone/PDF 中定位一致测试。
- [ ] chart/table free Element 内容测试。
- [ ] GIF frameTimes/slideSteps/darkTheme 测试。
- [ ] 播放器 `interactive=false` step 测试。
- [ ] JOBS enqueue-before-commit 测试。
- [ ] partial resume/超时/cancel 测试。
- [ ] 迁移后 document Markdown asset 引用完整性测试。
- [ ] cleanup 原始文件、别名和 7 日宽限测试。
- [ ] share auth_fail、续期 cookie、cleanup、签名 URL 测试。
- [ ] 长文档 120+ 章节和超长资产截断告警测试。
- [ ] OMML 失败裁剪图片测试。
- [ ] 真实 render-svc PDF/GIF/PPTX 测试。
- [ ] 真实 PPTX 打开和排版测试。
- [ ] 前端 Playwright 端到端测试。
- [ ] 5 份真实 Word 文档回归。

## 建议下一轮修复顺序

1. 创建 `.env`，配置真实 Key 并执行真实 DeepSeek 验收。
2. 修复导出 slot 样式的跨页污染。
3. 修复 GIF 逐帧和播放器 step。
4. 修复 standalone/PDF Element overlay 定位一致性。
5. 修复 JOBS 提交前入队和并发事务。
6. 修复迁移后文档资产引用与重复图片 assetId。
7. 修复长文档截断、OMML 裁剪图和上传安全。
8. 完成字体/CJK、PPTX 保真和前端编辑功能。
9. 最后执行真实 Docker、render-svc、DeepSeek 和 5 份 Word 全链路验收。
