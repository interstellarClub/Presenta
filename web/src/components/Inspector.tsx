import { useEffect, useMemo, useState } from "react";

import { LAYOUT_SLOTS } from "@/canvas/layouts";
import type { DeckPayload, Slide, SlideElement, ThemeManifest } from "@/types";

export type PatchOp = Record<string, unknown>;

interface InspectorProps {
  deck: DeckPayload;
  slide: Slide;
  slideIndex: number;
  selectedSlot: string | null;
  theme: ThemeManifest | null;
  documentId: string | null;
  onPatch: (operations: PatchOp[]) => Promise<void> | void;
}

type TabKey = "content" | "style" | "motion" | "source";

function asText(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

function findElement(slide: Slide, slotPath: string): { element: SlideElement; index: number } | null {
  const index = slide.elements.findIndex((element) => element.slotPath === slotPath);
  if (index < 0) return null;
  return { element: slide.elements[index], index };
}

export default function Inspector({
  deck,
  slide,
  slideIndex,
  selectedSlot,
  theme,
  documentId,
  onPatch,
}: InspectorProps) {
  const [tab, setTab] = useState<TabKey>("content");
  const [draft, setDraft] = useState("");
  const [jsonDraft, setJsonDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fontSize, setFontSize] = useState("");
  const [color, setColor] = useState("");
  const [align, setAlign] = useState("");

  const specs = useMemo(() => LAYOUT_SLOTS[slide.layout] ?? [], [slide.layout]);
  const activeSpec = useMemo(
    () => specs.find((spec) => spec.path === selectedSlot) ?? null,
    [specs, selectedSlot],
  );
  const found = useMemo(
    () => (selectedSlot ? findElement(slide, selectedSlot) : null),
    [slide, selectedSlot],
  );
  const styleOverride = useMemo(() => found?.element.styleOverride ?? {}, [found]);
  const slotValue = selectedSlot ? slide.slots[selectedSlot] : undefined;

  useEffect(() => {
    setError(null);
    if (!activeSpec) {
      setDraft("");
      setJsonDraft("");
      return;
    }
    if (activeSpec.kind === "list") {
      const items = Array.isArray(slotValue) ? slotValue : [];
      setDraft(
        items
          .map((item) =>
            typeof item === "object" && item !== null
              ? asText((item as Record<string, unknown>).text)
              : asText(item),
          )
          .join("\n"),
      );
      setJsonDraft("");
      return;
    }
    if (activeSpec.kind === "items") {
      setDraft("");
      setJsonDraft(JSON.stringify(slotValue ?? [], null, 2));
      return;
    }
    setDraft(asText(slotValue));
    setJsonDraft("");
  }, [activeSpec, slotValue, selectedSlot]);

  useEffect(() => {
    setFontSize(asText(styleOverride.fontSize));
    setColor(asText(styleOverride.color));
    setAlign(asText(styleOverride.textAlign));
  }, [styleOverride, selectedSlot]);

  const commitText = async () => {
    if (!activeSpec || !selectedSlot) return;
    try {
      if (activeSpec.kind === "list") {
        const items = draft
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean);
        await onPatch([
          { op: "replace", path: `/slides/${slideIndex}/slots/${selectedSlot}`, value: items },
        ]);
        return;
      }
      if (activeSpec.kind === "items") {
        const parsed = JSON.parse(jsonDraft) as unknown;
        if (!Array.isArray(parsed)) throw new Error("必须是数组");
        await onPatch([
          { op: "replace", path: `/slides/${slideIndex}/slots/${selectedSlot}`, value: parsed },
        ]);
        return;
      }
      await onPatch([
        { op: "replace", path: `/slides/${slideIndex}/slots/${selectedSlot}`, value: draft },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
    }
  };

  const applyStyle = async () => {
    if (!selectedSlot) return;
    const value: Record<string, string> = {};
    if (fontSize.trim()) value.fontSize = `${Number(fontSize) || 0}px`;
    if (color.trim()) value.color = color.trim();
    if (align.trim()) value.textAlign = align.trim();
    if (Object.keys(value).length === 0) return;
    const ops: PatchOp[] = [];
    if (found) {
      ops.push({
        op: "replace",
        path: `/slides/${slideIndex}/elements/${found.index}/styleOverride`,
        value: { ...found.element.styleOverride, ...value },
      });
    } else {
      ops.push({
        op: "add",
        path: `/slides/${slideIndex}/elements/-`,
        value: {
          id: `el-${Date.now().toString(36)}`,
          type: "text",
          slotPath: selectedSlot,
          styleOverride: value,
          anim: [],
          layout: null,
          component: null,
          provenance: null,
        },
      });
    }
    try {
      await onPatch(ops);
    } catch (err) {
      setError(err instanceof Error ? err.message : "样式提交失败");
    }
  };

  const resetStyle = async () => {
    if (!found || !selectedSlot) return;
    try {
      await onPatch([
        {
          op: "replace",
          path: `/slides/${slideIndex}/elements/${found.index}/styleOverride`,
          value: {},
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "重置失败");
    }
  };

  const applyTransition = async (effect: string, duration: number) => {
    try {
      await onPatch([
        {
          op: "replace",
          path: `/slides/${slideIndex}/transition`,
          value: { effect, duration },
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "转场提交失败");
    }
  };

  return (
    <aside className="inspector">
      <div className="tabs">
        {(["content", "style", "motion", "source"] as TabKey[]).map((key) => (
          <button
            key={key}
            type="button"
            className={tab === key ? "active" : ""}
            onClick={() => setTab(key)}
          >
            {key === "content"
              ? "内容"
              : key === "style"
                ? "样式"
                : key === "motion"
                  ? "动效"
                  : "来源"}
          </button>
        ))}
      </div>

      {error ? <div className="notice">{error}</div> : null}

      {tab === "content" ? (
        <div className="panel-stack">
          <div className="field-row">
            <label>当前版式</label>
            <span className="mono">{slide.layout}</span>
          </div>
          {selectedSlot ? (
            <>
              <div className="field-row">
                <label>选中插槽</label>
                <span className="mono">{selectedSlot}</span>
              </div>
              {activeSpec ? (
                activeSpec.kind === "items" ? (
                  <div className="field-row">
                    <label>{activeSpec.label}（JSON 数组）</label>
                    <textarea
                      rows={10}
                      value={jsonDraft}
                      className="mono"
                      onChange={(event) => setJsonDraft(event.target.value)}
                    />
                    <button type="button" onClick={() => void commitText()}>
                      应用 JSON
                    </button>
                  </div>
                ) : (
                  <div className="field-row">
                    <label>{activeSpec.label}</label>
                    <textarea
                      rows={activeSpec.kind === "text" ? 2 : 5}
                      value={draft}
                      onChange={(event) => setDraft(event.target.value)}
                    />
                    <button type="button" onClick={() => void commitText()}>
                      应用修改
                    </button>
                  </div>
                )
              ) : (
                <div className="muted small">该插槽不支持在此面板直接编辑。</div>
              )}
            </>
          ) : (
            <div className="muted small">
              在画布中点击元素即可选中插槽。版式骨架只读，内容可改。
            </div>
          )}

          {slide.degraded ? (
            <div className="notice">
              该页为降级页：{slide.degradedReason ?? "模型输出未通过校验"}
            </div>
          ) : null}
        </div>
      ) : null}

      {tab === "style" ? (
        <div className="panel-stack">
          {selectedSlot ? (
            <>
              <div className="field-row">
                <label>字号（px）</label>
                <input value={fontSize} onChange={(event) => setFontSize(event.target.value)} />
              </div>
              <div className="field-row">
                <label>颜色</label>
                <input
                  value={color}
                  placeholder="#1B1B1F"
                  onChange={(event) => setColor(event.target.value)}
                />
              </div>
              <div className="field-row">
                <label>对齐</label>
                <select value={align} onChange={(event) => setAlign(event.target.value)}>
                  <option value="">默认</option>
                  <option value="left">左对齐</option>
                  <option value="center">居中</option>
                  <option value="right">右对齐</option>
                </select>
              </div>
              <div className="inline-actions">
                <button type="button" onClick={() => void applyStyle()}>
                  应用样式
                </button>
                <button type="button" className="ghost" onClick={() => void resetStyle()}>
                  重置
                </button>
              </div>
              <div className="muted small">
                微调只写入 styleOverride，不污染主题 Token；切主题仍可追溯。
              </div>
            </>
          ) : (
            <div className="muted small">先选中一个元素。</div>
          )}
        </div>
      ) : null}

      {tab === "motion" ? (
        <div className="panel-stack">
          <div className="field-row">
            <label>整稿 motionLevel</label>
            <span className="mono">{deck.motionLevel.toFixed(2)}</span>
          </div>
          <div className="field-row">
            <label>换页转场</label>
            <select
              value={slide.transition?.effect ?? ""}
              onChange={(event) => {
                const effect = event.target.value;
                if (!effect) {
                  void onPatch([
                    { op: "replace", path: `/slides/${slideIndex}/transition`, value: null },
                  ]);
                  return;
                }
                void applyTransition(effect, slide.transition?.duration ?? 400);
              }}
            >
              <option value="">无</option>
              <option value="fade">fade</option>
              <option value="push">push</option>
              <option value="wipe">wipe</option>
              <option value="cover">cover</option>
              <option value="zoom">zoom</option>
            </select>
          </div>
          <div className="field-row">
            <label>转场时长（ms）</label>
            <input
              type="number"
              min={0}
              max={3000}
              value={slide.transition?.duration ?? 400}
              onChange={(event) => {
                const duration = Number(event.target.value) || 0;
                void applyTransition(slide.transition?.effect ?? "fade", duration);
              }}
            />
          </div>
          <div className="field-row">
            <label>fragment 步进（每行一步）</label>
            <textarea
              rows={4}
              value={slide.steps.join("\n")}
              className="mono"
              onChange={(event) => {
                const steps = event.target.value
                  .split("\n")
                  .map((line) => line.trim())
                  .filter(Boolean);
                void onPatch([
                  { op: "replace", path: `/slides/${slideIndex}/steps`, value: steps },
                ]);
              }}
            />
          </div>
          <div className="muted small">
            动效参数受 motionLevel 统一缩放；播放器与非 0 强度场景在后续阶段启用 seek(t)。
          </div>
        </div>
      ) : null}

      {tab === "source" ? (
        <div className="panel-stack">
          {slide.provenance.length === 0 ? (
            <div className="muted small">该页没有 provenance 记录。</div>
          ) : (
            slide.provenance.map((provenance, index) => (
              <div key={index} className="outline-item">
                <div className="doc-meta">
                  <span className="chip accent">{provenance.type}</span>
                  <span className="mono">
                    L{provenance.sourceRef.lineStart}–L{provenance.sourceRef.lineEnd}
                  </span>
                </div>
                <blockquote style={{ margin: 0, fontSize: 13, color: "var(--muted)" }}>
                  {provenance.quote.slice(0, 240)}
                </blockquote>
                <span className="muted small mono">
                  文档 {documentId ? documentId.slice(0, 8) : "—"}
                </span>
              </div>
            ))
          )}
          <div className="muted small">
            image 插槽只接受资产表 id；图表数值与 quote 逐字符串比对后才能入库。
          </div>
          {theme ? (
            <div className="muted small">
              主题 {theme.name} · WCAG {theme.wcag.passesAA ? "AA 通过" : "存在低对比组合"}
            </div>
          ) : null}
        </div>
      ) : null}
    </aside>
  );
}