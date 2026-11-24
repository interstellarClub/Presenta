import { useEffect, useMemo, useState } from "react";

import { LAYOUT_SLOTS } from "@/canvas/layouts";
import { api } from "@/lib/api";
import type {
  AssetSummary,
  DeckPayload,
  Slide,
  SlideElement,
  ThemeManifest,
} from "@/types";

export type PatchOp = Record<string, unknown>;

interface InspectorProps {
  deckId: string;
  expectedSeq: number;
  deck: DeckPayload;
  slide: Slide;
  slideIndex: number;
  selectedSlot: string | null;
  theme: ThemeManifest | null;
  documentId: string | null;
  assets: AssetSummary[];
  onPatch: (operations: PatchOp[]) => Promise<void> | void;
}

type TabKey = "content" | "style" | "motion" | "ai" | "source";

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
  deckId,
  expectedSeq,
  deck,
  slide,
  slideIndex,
  selectedSlot,
  theme,
  documentId,
  assets,
  onPatch,
}: InspectorProps) {
  const [tab, setTab] = useState<TabKey>("content");
  const [draft, setDraft] = useState("");
  const [jsonDraft, setJsonDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fontSize, setFontSize] = useState("");
  const [color, setColor] = useState("");
  const [align, setAlign] = useState("");
  const [fontWeight, setFontWeight] = useState("");
  const [lineHeight, setLineHeight] = useState("");
  const [letterSpacing, setLetterSpacing] = useState("");
  const [padding, setPadding] = useState("");
  const [borderRadius, setBorderRadius] = useState("");
  const [opacity, setOpacity] = useState("");
  const [background, setBackground] = useState("");
  const [intentInstruction, setIntentInstruction] = useState("");
  const [intentOperations, setIntentOperations] = useState<PatchOp[]>([]);
  const [intentExplanation, setIntentExplanation] = useState("");
  const [intentBusy, setIntentBusy] = useState(false);
  const [componentName, setComponentName] = useState("StepReveal");
  const [componentConfig, setComponentConfig] = useState("{}");

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
    setFontWeight(asText(styleOverride.fontWeight));
    setLineHeight(asText(styleOverride.lineHeight));
    setLetterSpacing(asText(styleOverride.letterSpacing));
    setPadding(asText(styleOverride.padding));
    setBorderRadius(asText(styleOverride.borderRadius));
    setOpacity(asText(styleOverride.opacity));
    setBackground(asText(styleOverride.background));
  }, [styleOverride, selectedSlot]);

  useEffect(() => {
    setComponentName(found?.element.component?.name ?? "StepReveal");
    setComponentConfig(JSON.stringify(found?.element.component?.config ?? {}, null, 2));
  }, [found]);

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
    if (fontWeight.trim()) value.fontWeight = fontWeight.trim();
    if (lineHeight.trim()) value.lineHeight = lineHeight.trim();
    if (letterSpacing.trim()) value.letterSpacing = letterSpacing.trim();
    if (padding.trim()) value.padding = padding.trim();
    if (borderRadius.trim()) value.borderRadius = borderRadius.trim();
    if (opacity.trim()) value.opacity = opacity.trim();
    if (background.trim()) value.background = background.trim();
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

  const chooseImage = async (assetId: string) => {
    if (!selectedSlot || !assetId) return;
    try {
      await onPatch([
        {
          op: "replace",
          path: `/slides/${slideIndex}/slots/${selectedSlot}`,
          value: { kind: "image", assetId, alt: "", fit: "cover" },
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "图片替换失败");
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

  const previewIntent = async () => {
    if (!intentInstruction.trim()) return;
    setIntentBusy(true);
    setError(null);
    try {
      const result = await api<{
        operations: PatchOp[];
        explanation: string;
      }>(`/decks/${deckId}/intent`, {
        method: "POST",
        body: JSON.stringify({
          instruction: intentInstruction.trim(),
          expectedSeq,
        }),
      });
      setIntentOperations(result.operations);
      setIntentExplanation(result.explanation);
    } catch (err) {
      setError(err instanceof Error ? err.message : "自然语言编辑失败");
    } finally {
      setIntentBusy(false);
    }
  };

  const applyIntent = async () => {
    if (intentOperations.length === 0) return;
    try {
      await onPatch(intentOperations);
      setIntentOperations([]);
      setIntentExplanation("");
      setIntentInstruction("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "应用 Patch 失败");
    }
  };

  const applyComponent = async () => {
    if (!selectedSlot) return;
    try {
      const config = JSON.parse(componentConfig) as Record<string, unknown>;
      const value = {
        ...(found?.element ?? {
          id: `motion-${Date.now().toString(36)}`,
          slotPath: selectedSlot,
          styleOverride: {},
          anim: [],
          provenance: null,
        }),
        type: "component",
        layout: found?.element.layout ?? { x: 2, y: 20, w: 8, h: 40 },
        component: { name: componentName, config },
      };
      await onPatch([
        found
          ? {
              op: "replace",
              path: `/slides/${slideIndex}/elements/${found.index}`,
              value,
            }
          : {
              op: "add",
              path: `/slides/${slideIndex}/elements/-`,
              value,
            },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "动效组件提交失败");
    }
  };

  return (
    <aside className="inspector">
      <div className="tabs">
        {(["content", "style", "motion", "ai", "source"] as TabKey[]).map((key) => (
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
                  : key === "ai"
                    ? "AI 编辑"
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
                activeSpec.kind === "media" ? (
                  <div className="field-row">
                    <label>{activeSpec.label}</label>
                    <select
                      value={
                        typeof slotValue === "object" &&
                        slotValue !== null &&
                        "assetId" in slotValue
                          ? String((slotValue as Record<string, unknown>).assetId ?? "")
                          : ""
                      }
                      onChange={(event) => void chooseImage(event.target.value)}
                    >
                      <option value="">选择文档图片资产</option>
                      {assets
                        .filter((asset) => asset.kind === "image")
                        .map((asset) => (
                          <option key={asset.id} value={asset.id}>
                            {String(asset.meta?.name ?? asset.id.slice(0, 8))}
                          </option>
                        ))}
                    </select>
                  </div>
                ) : activeSpec.kind === "items" ? (
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
              <div className="field-row">
                <label>字重</label>
                <select value={fontWeight} onChange={(event) => setFontWeight(event.target.value)}>
                  <option value="">默认</option>
                  <option value="400">常规</option>
                  <option value="500">中等</option>
                  <option value="600">半粗</option>
                  <option value="700">粗体</option>
                </select>
              </div>
              <div className="field-row">
                <label>行高</label>
                <input
                  value={lineHeight}
                  placeholder="1.5"
                  onChange={(event) => setLineHeight(event.target.value)}
                />
              </div>
              <div className="field-row">
                <label>字距</label>
                <input
                  value={letterSpacing}
                  placeholder="0"
                  onChange={(event) => setLetterSpacing(event.target.value)}
                />
              </div>
              <div className="field-row">
                <label>内边距</label>
                <input
                  value={padding}
                  placeholder="0"
                  onChange={(event) => setPadding(event.target.value)}
                />
              </div>
              <div className="field-row">
                <label>圆角</label>
                <input
                  value={borderRadius}
                  placeholder="0"
                  onChange={(event) => setBorderRadius(event.target.value)}
                />
              </div>
              <div className="field-row">
                <label>不透明度</label>
                <input
                  value={opacity}
                  placeholder="1"
                  onChange={(event) => setOpacity(event.target.value)}
                />
              </div>
              <div className="field-row">
                <label>背景</label>
                <input
                  value={background}
                  placeholder="transparent"
                  onChange={(event) => setBackground(event.target.value)}
                />
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
          <div className="field-row">
            <label>受控动效组件</label>
            <select
              value={componentName}
              onChange={(event) => setComponentName(event.target.value)}
              disabled={!selectedSlot}
            >
              <option value="StepReveal">StepReveal</option>
              <option value="ChartReveal">ChartReveal</option>
              <option value="FlowDiagram">FlowDiagram</option>
              <option value="FormulaStep">FormulaStep</option>
              <option value="CodeType">CodeType</option>
              <option value="FlowParticles">FlowParticles</option>
            </select>
          </div>
          <div className="field-row">
            <label>组件配置 JSON</label>
            <textarea
              rows={6}
              className="mono"
              value={componentConfig}
              disabled={!selectedSlot}
              onChange={(event) => setComponentConfig(event.target.value)}
            />
            <button type="button" onClick={() => void applyComponent()} disabled={!selectedSlot}>
              应用动效组件
            </button>
          </div>
          <div className="muted small">
            动效参数受 motionLevel 统一缩放，统一通过纯函数 seek(t) 计算帧状态。
          </div>
        </div>
      ) : null}

      {tab === "ai" ? (
        <div className="panel-stack">
          <div className="field-row">
            <label>自然语言指令</label>
            <textarea
              rows={4}
              value={intentInstruction}
              placeholder="例如：把这页标题改短，并强调关键数字"
              onChange={(event) => setIntentInstruction(event.target.value)}
            />
          </div>
          <button
            type="button"
            onClick={() => void previewIntent()}
            disabled={intentBusy || !intentInstruction.trim()}
          >
            {intentBusy ? "生成 Patch 中…" : "生成 Patch 预览"}
          </button>
          {intentExplanation ? <div className="notice">{intentExplanation}</div> : null}
          {intentOperations.length > 0 ? (
            <>
              <pre
                className="mono small"
                style={{ whiteSpace: "pre-wrap", maxHeight: 240, overflow: "auto" }}
              >
                {JSON.stringify(intentOperations, null, 2)}
              </pre>
              <button type="button" className="primary" onClick={() => void applyIntent()}>
                确认应用 Patch
              </button>
            </>
          ) : null}
          <div className="muted small">
            模型只生成可校验的 JSON Patch；确认前不会修改 Deck。
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
