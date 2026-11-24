import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import SlideFrame from "@/canvas/SlideFrame";
import type { SlideDragSelection, SlideSelection } from "@/canvas/SlideFrame";
import Inspector from "@/components/Inspector";
import JobProgress from "@/components/JobProgress";
import ExportPanel from "@/components/ExportPanel";
import VersionTimeline from "@/components/VersionTimeline";
import { api, ApiError, uploadThemePack } from "@/lib/api";
import type {
  AssetSummary,
  DeckPayload,
  DeckResponse,
  DocumentDetail,
  GenerateResponse,
  ThemeManifest,
} from "@/types";

export default function StudioPage() {
  const { deckId = "" } = useParams();
  const navigate = useNavigate();
  const [response, setResponse] = useState<DeckResponse | null>(null);
  const [themes, setThemes] = useState<ThemeManifest[]>([]);
  const [index, setIndex] = useState(0);
  const [selection, setSelection] = useState<SlideSelection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [showVersions, setShowVersions] = useState(false);
  const [showExport, setShowExport] = useState(false);
  const [motionDraft, setMotionDraft] = useState(0);
  const [assets, setAssets] = useState<AssetSummary[]>([]);
  const themeInput = useRef<HTMLInputElement>(null);

  const deck: DeckPayload | null = response?.deck ?? null;
  const slide = deck?.slides[index] ?? null;
  const documentId = useMemo(
    () => deck?.meta.sourceDocumentId ?? deck?.provenance[0]?.documentId ?? null,
    [deck],
  );
  const theme = useMemo(
    () => themes.find((entry) => entry.id === deck?.themeId) ?? null,
    [themes, deck],
  );

  const loadDeck = useCallback(async () => {
    try {
      const data = await api<DeckResponse>(`/decks/${deckId}`);
      setResponse(data);
      setMotionDraft(data.deck.motionLevel);
      setIndex((current) => Math.min(current, Math.max(0, data.deck.slides.length - 1)));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载失败");
    }
  }, [deckId]);

  useEffect(() => {
    void loadDeck();
    void api<ThemeManifest[]>("/themes")
      .then(setThemes)
      .catch(() => setThemes([]));
  }, [loadDeck]);

  useEffect(() => {
    if (!documentId) {
      setAssets([]);
      return;
    }
    void api<DocumentDetail>(`/documents/${documentId}`)
      .then((detail) => setAssets(detail.assets))
      .catch(() => setAssets([]));
  }, [documentId]);

  useEffect(() => {
    setSelection(null);
  }, [index]);

  const patch = async (operations: Record<string, unknown>[]) => {
    setPending(true);
    setError(null);
    try {
      const data = await api<DeckResponse>(`/decks/${deckId}`, {
        method: "PATCH",
        body: JSON.stringify({
          operations,
          kind: "autosave",
          expectedSeq: response?.versionSeq ?? 0,
        }),
      });
      setResponse(data);
      setMotionDraft(data.deck.motionLevel);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "提交失败");
      throw err;
    } finally {
      setPending(false);
    }
  };

  const moveSlot = (selection: SlideDragSelection) => {
    if (!deck) return;
    const targetSlideIndex = deck.slides.findIndex(
      (entry) => entry.id === selection.slideId,
    );
    if (targetSlideIndex < 0) return;
    const targetSlide = deck.slides[targetSlideIndex];
    const elementIndex = targetSlide.elements.findIndex(
      (element) => element.slotPath === selection.slotPath,
    );
    const layout = selection.layout;
    const operations =
      elementIndex >= 0
        ? [
            {
              op: "replace",
              path: `/slides/${targetSlideIndex}/elements/${elementIndex}/layout`,
              value: layout,
            },
          ]
        : [
            {
              op: "add",
              path: `/slides/${targetSlideIndex}/elements/-`,
              value: {
                id: `el-${Date.now().toString(36)}`,
                type: "text",
                slotPath: selection.slotPath,
                layout,
                styleOverride: {},
                anim: [],
                component: null,
                provenance: null,
              },
            },
          ];
    void patch(operations).then(() => setSelection(selection));
  };

  const generate = async () => {
    setError(null);
    try {
      const created = await api<GenerateResponse>(`/decks/${deckId}/generate`, {
        method: "POST",
      });
      setJobId(created.jobId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "生成失败");
    }
  };

  const changeTheme = async (themeId: string) => {
    setPending(true);
    try {
      const data = await api<DeckResponse>(
        `/decks/${deckId}/theme?themeId=${encodeURIComponent(themeId)}`,
        { method: "PUT" },
      );
      setResponse(data);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "主题切换失败");
    } finally {
      setPending(false);
    }
  };

  const loadThemes = useCallback(async () => {
    try {
      setThemes(await api<ThemeManifest[]>("/themes"));
    } catch {
      setThemes([]);
    }
  }, []);

  const uploadTheme = async (file: File) => {
    setPending(true);
    setError(null);
    try {
      await uploadThemePack(file, file.name.replace(/\.zip$/i, ""));
      await loadThemes();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "模板包上传失败");
    } finally {
      setPending(false);
    }
  };

  if (!deck || !slide) {
    return (
      <div className="empty">
        {error ?? "加载中…"} {error ? <Link to="/">返回</Link> : null}
      </div>
    );
  }

  return (
    <div className="studio">
      <header className="studio-top">
        <span className="brand-mark" aria-hidden>
          P
        </span>
        <div className="studio-title">
          <strong>{deck.meta.title}</strong>
          <span className="muted small mono">
            v{response?.versionSeq ?? 0} · {deck.slides.length} 页 · {theme?.name ?? deck.themeId}
          </span>
        </div>

        <div className="stage-actions" style={{ marginLeft: "auto" }}>
          <select
            value={deck.themeId}
            onChange={(event) => void changeTheme(event.target.value)}
            disabled={pending}
          >
            {themes.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.name}
              </option>
            ))}
          </select>
          <input
            ref={themeInput}
            type="file"
            accept=".zip"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void uploadTheme(file);
              event.target.value = "";
            }}
          />
          <button
            type="button"
            className="ghost small"
            disabled={pending}
            onClick={() => themeInput.current?.click()}
          >
            上传主题包
          </button>

          <label className="progress-line" style={{ minWidth: 190 }}>
            <span className="muted small">动效</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={motionDraft}
              onChange={(event) => setMotionDraft(Number(event.target.value))}
              onMouseUp={() => {
                if (Math.abs(motionDraft - deck.motionLevel) > 0.001) {
                  void patch([
                    { op: "replace", path: "/motionLevel", value: motionDraft },
                  ]).catch(() => undefined);
                }
              }}
              style={{ flex: 1 }}
            />
            <span className="mono">{motionDraft.toFixed(2)}</span>
          </label>

          <button type="button" onClick={() => void generate()} disabled={pending}>
            重新生成
          </button>
          <button type="button" className="ghost" onClick={() => setShowVersions((value) => !value)}>
            版本
          </button>
          <button type="button" className="ghost" onClick={() => setShowExport((value) => !value)}>
            导出 / 分享
          </button>
          <button type="button" className="primary" onClick={() => navigate(`/decks/${deckId}/present`)}>
            播放
          </button>
        </div>
      </header>

      <div className="studio-body">
        <div className="rail">
          {deck.slides.map((entry, entryIndex) => (
            <button
              key={entry.id}
              type="button"
              className={`thumb ${entryIndex === index ? "active" : ""}`}
              onClick={() => setIndex(entryIndex)}
              title={`第 ${entryIndex + 1} 页 · ${entry.layout}`}

            >
              <span className="thumb-index mono">{entryIndex + 1}</span>
              <SlideFrame
                slide={entry}
                theme={theme}
                documentId={documentId}
              motionLevel={deck.motionLevel}
                interactive={false}
                compact
                title={`thumb-${entryIndex}`}
              />
            </button>
          ))}
        </div>

        <div className="canvas-area">
          <div className="slide-shell">
            {error ? <div className="notice">{error}</div> : null}
            {jobId ? (
              <div className="panel" style={{ padding: 12 }}>
                <JobProgress
                  jobId={jobId}
                  onTerminal={(job) => {
                    if (job.status === "succeeded" || job.status === "partial") {
                      void loadDeck();
                    }
                  }}
                />
              </div>
            ) : null}
            <SlideFrame
              slide={slide}
              theme={theme}
              documentId={documentId}
              motionLevel={deck.motionLevel}
              selectedSlot={selection?.slotPath ?? null}
              onSelect={(next) => {
                setSelection(next);
                setIndex((current) => {
                  const target = deck.slides.findIndex((entry) => entry.id === next.slideId);
                  return target >= 0 ? target : current;
                });
              }}
              onDrag={moveSlot}
            />
            <div className="slide-caption">
              <span>
                第 {index + 1} / {deck.slides.length} 页 · 版式{" "}
                <span className="mono">{slide.layout}</span>
                {slide.degraded ? <span className="chip warn" style={{ marginLeft: 8 }}>degraded</span> : null}
              </span>
              <span className="inline-actions">
                <button
                  type="button"
                  className="ghost small"
                  disabled={index === 0}
                  onClick={() => setIndex((value) => Math.max(0, value - 1))}
                >
                  上一页
                </button>
                <button
                  type="button"
                  className="ghost small"
                  disabled={index >= deck.slides.length - 1}
                  onClick={() => setIndex((value) => Math.min(deck.slides.length - 1, value + 1))}
                >
                  下一页
                </button>
              </span>
            </div>
          </div>
        </div>

        <Inspector
          deckId={deckId}
          expectedSeq={response?.versionSeq ?? 0}
          deck={deck}
          slide={slide}
          slideIndex={index}
          selectedSlot={selection?.slotPath ?? null}
          theme={theme}
          documentId={documentId}
          assets={assets}
          onPatch={(operations) => patch(operations)}
        />

        {showVersions ? (
          <div
            className="panel"
            style={{
              position: "fixed",
              right: 16,
              top: 70,
              width: 380,
              zIndex: 40,
              maxHeight: "70vh",
              overflow: "auto",
              boxShadow: "0 24px 60px rgba(0,0,0,0.5)",
            }}
          >
            <div className="inline-actions" style={{ justifyContent: "space-between" }}>
              <h2 style={{ marginBottom: 8 }}>版本历史</h2>
              <button type="button" className="ghost small" onClick={() => setShowVersions(false)}>
                关闭
              </button>
            </div>
            <VersionTimeline
              deckId={deckId}
              currentSeq={response?.versionSeq ?? 0}
              onRolledBack={() => void loadDeck()}
            />
          </div>
        ) : null}
      {showExport ? (
          <div
            className="panel"
            style={{
              position: "fixed",
              right: 16,
              top: 70,
              width: 430,
              zIndex: 40,
              maxHeight: "80vh",
              overflow: "auto",
              boxShadow: "0 24px 60px rgba(0,0,0,0.5)",
            }}
          >
            <div className="inline-actions" style={{ justifyContent: "space-between" }}>
              <h2 style={{ marginBottom: 8 }}>导出与分享</h2>
              <button type="button" className="ghost small" onClick={() => setShowExport(false)}>
                关闭
              </button>
            </div>
            <ExportPanel deckId={deckId} versionSeq={response?.versionSeq ?? 0} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
