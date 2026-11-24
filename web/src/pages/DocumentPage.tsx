import Editor from "@monaco-editor/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import type { editor } from "monaco-editor";

import { api, ApiError, streamSse } from "@/lib/api";
import type {
  DeckResponse,
  DocumentCreated,
  DocumentDetail,
  Outline,
  OutlineItem,
} from "@/types";

const STATUS_LABEL: Record<string, string> = {
  parsing: "解析中",
  normalizing: "归一化中",
  extracting_assets: "抽取资产中",
  indexing: "建立索引中",
  ready: "已就绪",
  failed: "解析失败",
};

export default function DocumentPage() {
  const { documentId = "" } = useParams();
  const navigate = useNavigate();
  const [document, setDocument] = useState<DocumentDetail | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [outline, setOutline] = useState<Outline | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [streamLog, setStreamLog] = useState<string>("");
  const abortRef = useRef<AbortController | null>(null);
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);
  const draggedOutlineIndex = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api<DocumentDetail>(`/documents/${documentId}`);
      setDocument(data);
      setMarkdown((current) => (current === "" ? data.normalizedMd : current));
      if (data.outline && !outline) setOutline(data.outline);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    }
  }, [documentId, outline]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId]);

  useEffect(() => {
    if (!document || document.status === "ready" || document.status === "failed") return;
    const timer = window.setInterval(() => {
      void load();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [document, load]);

  const generateOutline = async () => {
    if (!document || document.status !== "ready") return;
    setStreaming(true);
    setError(null);
    setStreamLog("正在分块摘要…");
    const controller = new AbortController();
    abortRef.current = controller;
    const draft: Outline = { title: document.title, subtitle: "", items: [] };
    try {
      await streamSse(
        `/documents/${documentId}/outline`,
        {},
        (event, data) => {
          if (event === "stage") {
            const payload = data as { stage?: string; sections?: number; items?: number };
            setStreamLog(
              payload.stage === "summarizing"
                ? `正在处理 ${payload.sections ?? 0} 个章节…`
                : `正在规划 ${payload.items ?? 0} 页…`,
            );
          } else if (event === "item") {
            const item = data as OutlineItem;
            draft.items.push(item);
            setOutline({ ...draft, items: [...draft.items] });
          } else if (event === "done") {
            const final = data as Outline;
            draft.title = final.title || draft.title;
            draft.subtitle = final.subtitle ?? "";
            if (final.items?.length) draft.items = final.items;
            setOutline({ ...draft, items: final.items ?? draft.items });
          } else if (event === "error") {
            const payload = data as { message?: string };
            setError(payload.message ?? "大纲生成失败");
          }
        },
        controller.signal,
      );
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setError(err instanceof ApiError ? err.message : "大纲生成失败");
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
      setStreamLog("");
    }
  };

  const saveMarkdown = async () => {
    setBusy(true);
    setError(null);
    try {
      await api<DocumentCreated>(`/documents/${documentId}/markdown`, {
        method: "PUT",
        body: JSON.stringify({ markdown }),
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  const updateItem = (index: number, patch: Partial<OutlineItem>) => {
    if (!outline) return;
    const items = outline.items.map((item, itemIndex) =>
      itemIndex === index ? { ...item, ...patch } : item,
    );
    setOutline({ ...outline, items });
  };

  const removeItem = (index: number) => {
    if (!outline) return;
    setOutline({ ...outline, items: outline.items.filter((_, itemIndex) => itemIndex !== index) });
  };

  const addItem = () => {
    if (!outline) return;
    const id = `item-${Date.now().toString(36)}`;
    const sectionId = sections[0]?.id ?? null;
    setOutline({
      ...outline,
      items: [
        ...outline.items,
        {
          id,
          title: "新页面",
          points: ["请补充本页要点"],
          sectionId,
        },
      ],
    });
  };

  const moveItem = (from: number, to: number) => {
    if (!outline || from === to) return;
    const items = [...outline.items];
    const [moved] = items.splice(from, 1);
    items.splice(to, 0, moved);
    setOutline({ ...outline, items });
  };

  const revealSection = (sectionId: string | null | undefined) => {
    const section = sections.find((entry) => entry.id === sectionId);
    const instance = editorRef.current;
    if (!section || !instance) return;
    instance.revealLineInCenter(section.lineStart);
    instance.setPosition({ lineNumber: section.lineStart, column: 1 });
    instance.focus();
  };

  const confirmAndCreate = async () => {
    if (!outline || outline.items.length === 0) {
      setError("大纲为空，无法创建演示文稿");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api(`/documents/${documentId}/outline/confirm`, {
        method: "POST",
        body: JSON.stringify({
          title: outline.title,
          subtitle: outline.subtitle,
          items: outline.items.map((item, index) => ({
            ...item,
            id: item.id || `item-${index + 1}`,
          })),
          ...(outline.items.length ? {} : {}),
        }),
      });
      const created = await api<DeckResponse>("/decks", {
        method: "POST",
        body: JSON.stringify({ documentId, outline }),
      });
      navigate(`/decks/${created.deck.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "创建失败");
    } finally {
      setBusy(false);
    }
  };

  const outlineReady = Boolean(outline && outline.items.length > 0);
  const sections = useMemo(() => document?.sections ?? [], [document]);

  if (!document) {
    return (
      <div className="empty">
        {error ? error : "加载中…"} {error ? <Link to="/">返回文稿列表</Link> : null}
      </div>
    );
  }

  return (
    <div>
      <div className="section-head">
        <div>
          <div className="doc-meta" style={{ marginBottom: 8 }}>
            <Link to="/" className="muted small">
              ← 文稿列表
            </Link>
            <span className={`chip ${document.status === "ready" ? "ok" : "warn"}`}>
              {STATUS_LABEL[document.status] ?? document.status}
            </span>
            {document.degraded ? <span className="chip warn">解析有降级项</span> : null}
          </div>
          <h1>{document.title}</h1>
          <p>
            {document.sectionCount} 个章节 · {document.assetCount} 个资产 · 原文逐字保留
          </p>
        </div>
        <div className="stage-actions">
          <button type="button" onClick={() => void saveMarkdown()} disabled={busy}>
            {busy ? "保存中…" : "保存 Markdown"}
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => void generateOutline()}
            disabled={streaming || document.status !== "ready"}
          >
            {streaming ? "生成中…" : outlineReady ? "重新生成大纲" : "生成大纲"}
          </button>
          <button
            type="button"
            disabled={!outlineReady || busy}
            onClick={() => void confirmAndCreate()}
          >
            确认并创建文稿
          </button>
        </div>
      </div>

      {error ? <div className="notice" style={{ marginBottom: 14 }}>{error}</div> : null}
      {document.degraded ? (
        <div className="notice" style={{ marginBottom: 14 }}>
          解析过程中存在降级项（例如 OMML 公式无法转换），原始内容仍完整保留在文中。
        </div>
      ) : null}

      <div className="workbench">
        <section className="panel" style={{ padding: 0 }}>
          <div className="monaco-shell">
            <Editor
              height="560px"
              defaultLanguage="markdown"
              theme="vs-dark"
              value={markdown}
              onChange={(value) => setMarkdown(value ?? "")}
              onMount={(instance) => {
                editorRef.current = instance;
              }}
              options={{
                minimap: { enabled: false },
                wordWrap: "on",
                fontSize: 14,
                scrollBeyondLastLine: false,
                automaticLayout: true,
                padding: { top: 16 },
              }}
            />
          </div>
          <div className="panel" style={{ border: "none" }}>
            <h2>章节定位</h2>
            <div className="outline-list">
              {sections.map((section) => (
                <button
                  key={section.id}
                  type="button"
                  className="version-row"
                  onClick={() => revealSection(section.id)}
                  style={{ width: "100%", textAlign: "left", border: 0, background: "transparent", cursor: "pointer" }}
                >
                  <span className="mono">L{section.lineStart}</span>
                  <span style={{ flex: 1 }}>{section.title}</span>
                  <span className="muted small mono">h{section.level}</span>
                </button>
              ))}
              {sections.length === 0 ? <div className="muted small">暂无章节</div> : null}
            </div>
          </div>
        </section>

        <aside className="panel">
          <h2>大纲</h2>
          {streaming ? (
            <div className="progress-line" style={{ marginBottom: 12 }}>
              <span className="mono">{streamLog || "生成中…"}</span>
              <div className="progress-track">
                <div className="progress-fill" style={{ width: "60%" }} />
              </div>
            </div>
          ) : null}

          {!outline || outline.items.length === 0 ? (
            <div className="empty">
              还没有大纲。点击右上角「生成大纲」，确认后再逐页生成。
            </div>
          ) : (
            <div className="panel-stack">
              <div className="field-row">
                <label>整稿标题</label>
                <input
                  value={outline.title}
                  onChange={(event) => setOutline({ ...outline, title: event.target.value })}
                />
              </div>
              <div className="field-row">
                <label>副标题</label>
                <input
                  value={outline.subtitle}
                  onChange={(event) => setOutline({ ...outline, subtitle: event.target.value })}
                />
              </div>
              <div className="outline-list">
                {outline.items.map((item, index) => (
                  <div
                    key={item.id || index}
                    className="outline-item"
                    draggable
                    onDragStart={() => {
                      draggedOutlineIndex.current = index;
                    }}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={(event) => {
                      event.preventDefault();
                      const from = draggedOutlineIndex.current;
                      if (from !== null) moveItem(from, index);
                      draggedOutlineIndex.current = null;
                    }}
                  >
                    <div className="doc-meta">
                      <span className="mono">#{index + 1}</span>
                      <select
                        className="small"
                        value={item.sectionId ?? ""}
                        onChange={(event) =>
                          updateItem(index, { sectionId: event.target.value || null })
                        }
                      >
                        <option value="">未绑定章节</option>
                        {sections.map((section) => (
                          <option key={section.id} value={section.id}>
                            {section.title}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        className="ghost small"
                        onClick={() => revealSection(item.sectionId)}
                      >
                        原文
                      </button>
                      <button
                        type="button"
                        className="ghost small"
                        style={{ marginLeft: "auto" }}
                        onClick={() => removeItem(index)}
                      >
                        删除
                      </button>
                    </div>
                    <h4>
                      <input
                        value={item.title}
                        onChange={(event) => updateItem(index, { title: event.target.value })}
                        style={{ width: "100%" }}
                      />
                    </h4>
                    <div className="outline-points">
                      {item.points.map((point, pointIndex) => (
                        <input
                          key={pointIndex}
                          value={point}
                          onChange={(event) => {
                            const points = item.points.map((current, currentIndex) =>
                              currentIndex === pointIndex ? event.target.value : current,
                            );
                            updateItem(index, { points });
                          }}
                        />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <button type="button" className="ghost" onClick={addItem}>
                新增页面
              </button>
              <button type="button" onClick={() => void confirmAndCreate()} disabled={busy}>
                确认大纲并创建
              </button>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
