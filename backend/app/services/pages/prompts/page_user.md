本页任务信息（全部来自服务端，不要改写其中的事实）：
- 文稿标题：{document_title}
- 页码：{page_index} / {page_total}
- 本页标题候选：{item_title}
- 本页要点：{points}
- 绑定的章节 id：{section_id}
- 原文定位（行号范围）：{source_ref}
- 允许的版式 id：{allowed_layouts}
- 文档 id：{document_id}

原文片段（逐字，禁止改写；图表与关键数字只能取自这里）：
{section_text}

可用资产（JSON，可能为空数组）：
{assets}

输出约定：只输出 {"layout","slots","notes"} 三字段的 JSON；不要输出 provenance/elements/额外字段。
