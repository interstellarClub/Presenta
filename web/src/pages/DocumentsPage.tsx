import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import JobProgress from "@/components/JobProgress";
import { api, uploadDocument } from "@/lib/api";
import type { DocumentCreated, DocumentSummary } from "@/types";

const STATUS_LABEL: Record<string, string> = {
  parsing: "解析中",
  normalizing: "归一化",
  extracting_assets: "抽取资产",
  indexing: "建索引",
  ready: "已就绪",
  failed: "失败",
};

export default function DocumentsPage() {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [markdown, setMarkdown] = useState("");
  const [creating, setCreating] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const data = await api<DocumentSummary[]>("/documents");
      setDocuments(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const ingestFile = async (file: File) => {
    setError(null);
    try {
      const created = (await uploadDocument(file)) as DocumentCreated;
      setJobId(created.jobId ?? null);
      await load();
      navigate(`/documents/${created.document.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    }
  };

  const onDrop = async (event: React.DragEvent) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) await ingestFile(file);
  };

  const createMarkdown = async () => {
    if (!title.trim() || !markdown.trim()) {
      setError("请填写标题与 Markdown 正文");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const created = await api<DocumentCreated>("/documents/editor", {
        method: "POST",
        body: JSON.stringify({ title: title.trim(), markdown }),
      });
      setJobId(created.jobId ?? null);
      navigate(`/documents/${created.document.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div>
      <div className="section-head">
        <div>
          <h1>你的文稿</h1>
          <p>上传 Word 或直接写 Markdown；确认大纲后才会逐页生成。</p>
        </div>
        <span className="chip">M1 · 结构化生成</span>
      </div>

      {error ? <div className="notice" style={{ marginBottom: 16 }}>{error}</div> : null}

      <div className="new-doc">
        <div
          className={`dropzone ${dragging ? "dragging" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => void onDrop(event)}
        >
          <div>
            <h2 style={{ fontSize: 20 }}>导入文档</h2>
            <p className="muted small" style={{ margin: "6px 0 0" }}>
              拖入 .docx / .md，或选择文件。上限 50MB，图片只从文档内抽取。
            </p>
          </div>
          <div className="inline-actions">
            <input
              ref={fileInput}
              type="file"
              accept=".docx,.md,.markdown"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void ingestFile(file);
              }}
            />
            <button type="button" className="primary" onClick={() => fileInput.current?.click()}>
              选择文件
            </button>
          </div>
        </div>

        <div className="panel">
          <h2>从 Markdown 开始</h2>
          <div className="panel-stack">
            <input
              placeholder="文档标题"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
            <textarea
              placeholder={"# 一级标题\n\n正文段落…"}
              rows={5}
              value={markdown}
              onChange={(event) => setMarkdown(event.target.value)}
            />
            <button type="button" onClick={() => void createMarkdown()} disabled={creating}>
              {creating ? "创建中…" : "创建文稿"}
            </button>
          </div>
        </div>
      </div>

      {jobId ? (
        <div className="panel" style={{ marginBottom: 20 }}>
          <h2>解析任务</h2>
          <JobProgress jobId={jobId} onTerminal={() => void load()} />
        </div>
      ) : null}

      {loading ? (
        <div className="empty">加载中…</div>
      ) : documents.length === 0 ? (
        <div className="empty">还没有文稿。先上传一份真实文档试试。</div>
      ) : (
        <div className="doc-grid">
          {documents.map((document) => (
            <article
              key={document.id}
              className="doc-card"
              role="link"
              tabIndex={0}
              onClick={() => navigate(`/documents/${document.id}`)}
              onKeyDown={(event) => {
                if (event.key === "Enter") navigate(`/documents/${document.id}`);
              }}
            >
              <div className="doc-meta">
                <span className={`chip ${document.status === "ready" ? "ok" : "warn"}`}>
                  {STATUS_LABEL[document.status] ?? document.status}
                </span>
                {document.hasOutline ? <span className="chip accent">已确认大纲</span> : null}
                {document.degraded ? <span className="chip warn">有降级项</span> : null}
              </div>
              <h3>{document.title}</h3>
              <div className="doc-meta" style={{ marginTop: "auto" }}>
                <span>{document.sectionCount} 个章节</span>
                <span>{document.assetCount} 个资产</span>
                <span className="mono">{new Date(document.updatedAt).toLocaleString()}</span>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}