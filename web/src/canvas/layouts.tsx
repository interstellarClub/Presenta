import type { JSX, ReactNode } from "react";

import { assetUrl, type ThemeTokens } from "@/themes/theme";
import type { Slide } from "@/types";

export type SlotKind = "text" | "longText" | "list" | "media" | "chart" | "items";

export interface SlotEditorSpec {
  path: string;
  label: string;
  kind: SlotKind;
  fields?: string[];
}

export const LAYOUT_SLOTS: Record<string, SlotEditorSpec[]> = {
  cover: [
    { path: "kicker", label: "引导语", kind: "text" },
    { path: "title", label: "主标题", kind: "text" },
    { path: "subtitle", label: "副标题", kind: "text" },
  ],
  toc: [{ path: "title", label: "标题", kind: "text" }],
  bullets: [
    { path: "title", label: "标题", kind: "text" },
    { path: "lead", label: "引导句", kind: "text" },
    { path: "items", label: "要点（每行一条）", kind: "list" },
  ],
  "split-lr": [
    { path: "title", label: "标题", kind: "text" },
    { path: "body", label: "正文", kind: "longText" },
    { path: "media", label: "图片", kind: "media" },
  ],
  "split-tb": [
    { path: "title", label: "标题", kind: "text" },
    { path: "body", label: "正文", kind: "longText" },
    { path: "media", label: "图片", kind: "media" },
  ],
  "cards-3": [
    { path: "title", label: "标题", kind: "text" },
    { path: "cards", label: "卡片", kind: "items", fields: ["heading", "text"] },
  ],
  chart: [
    { path: "title", label: "标题", kind: "text" },
    { path: "caption", label: "图注", kind: "text" },
    { path: "source", label: "来源", kind: "text" },
  ],
  "big-number": [{ path: "title", label: "标题", kind: "text" }],
  quote: [
    { path: "quote", label: "引文", kind: "longText" },
    { path: "author", label: "作者", kind: "text" },
  ],
  compare: [{ path: "title", label: "标题", kind: "text" }],
  timeline: [{ path: "title", label: "标题", kind: "text" }],
  process: [{ path: "title", label: "标题", kind: "text" }],
  "full-image": [
    { path: "media", label: "图片", kind: "media" },
    { path: "caption", label: "图注", kind: "text" },
  ],
  ending: [
    { path: "title", label: "标题", kind: "text" },
    { path: "message", label: "一句话", kind: "text" },
    { path: "contact", label: "联系方式", kind: "text" },
  ],
};

function text(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

function CjkText({ value }: { value: string }): JSX.Element {
  const raw = value;
  const parts = raw.split(/([\u3400-\u9fff\u3000-\u303f]+)/g).filter(Boolean);
  return (
    <>
      {parts.map((part, index) => {
        const isCjk = /[\u3400-\u9fff]/.test(part);
        const previous = parts[index - 1] ?? "";
        const next = parts[index + 1] ?? "";
        const needsCjkGap =
          !isCjk &&
          /[A-Za-z0-9]/.test(part) &&
          (/[\u3400-\u9fff]/.test(previous) || /[\u3400-\u9fff]/.test(next));
        return (
          <span key={index} className={isCjk ? "cjk-compensate" : undefined}>
            {needsCjkGap ? "\u200b" : ""}
            {part}
            {needsCjkGap ? "\u200b" : ""}
          </span>
        );
      })}
    </>
  );
}

function TypographyText({ value }: { value: unknown }): JSX.Element {
  const tokens = text(value).split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*|\^[^^]+\^)/g);
  return (
    <>
      {tokens.map((token, index) => {
        if (token.startsWith("**") && token.endsWith("**")) {
          return <strong key={index}><CjkText value={token.slice(2, -2)} /></strong>;
        }
        if (token.startsWith("`") && token.endsWith("`")) {
          return <code key={index}><CjkText value={token.slice(1, -1)} /></code>;
        }
        if (token.startsWith("*") && token.endsWith("*")) {
          return <em key={index}><CjkText value={token.slice(1, -1)} /></em>;
        }
        if (token.startsWith("^") && token.endsWith("^")) {
          return <sup key={index}><CjkText value={token.slice(1, -1)} /></sup>;
        }
        return <CjkText key={index} value={token} />;
      })}
    </>
  );
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

interface SlotProps {
  path: string;
  selected: string | null;
  children: ReactNode;
  tag?: "div" | "span" | "section" | "li" | "h1" | "h2" | "p" | "figure" | "blockquote";
  className?: string;
}

function Slot({ path, selected, children, tag = "div", className = "" }: SlotProps): JSX.Element {
  const Tag = tag;
  return (
    <Tag
      className={`slot ${className} ${selected === path ? "is-selected" : ""}`.trim()}
      data-slot={path}
    >
      {children}
    </Tag>
  );
}

function MediaView({
  media,
  tokens,
  documentId,
  selected,
  path,
}: {
  media: unknown;
  tokens: ThemeTokens;
  documentId: string | null;
  selected: string | null;
  path: string;
}): JSX.Element {
  const data = record(media);
  const kind = text(data.kind);
  if (kind === "image") {
    const id = text(data.assetId);
    return (
      <Slot path={path} selected={selected} className="media-frame" tag="figure">
        <img src={assetUrl(documentId, id)} alt={text(data.alt)} style={{ objectFit: (data.fit as "cover" | "contain") ?? "cover" }} />
      </Slot>
    );
  }
  if (kind === "chart") {
    return (
      <Slot path={path} selected={selected} className="media-frame" tag="figure">
        <ChartView chart={data} tokens={tokens} />
      </Slot>
    );
  }
  if (kind === "table") {
    return (
      <Slot path={path} selected={selected} className="media-frame" tag="figure">
        <TableView columns={list(data.columns).map(text)} rows={list(data.rows)} />
      </Slot>
    );
  }
  return (
    <Slot path={path} selected={selected} className="media-placeholder" tag="figure">
      <span className="mono">媒体占位</span>
    </Slot>
  );
}

interface ChartLike {
  type?: string;
  title?: string;
  unit?: string;
  series?: unknown[];
}

export function ChartView({ chart, tokens }: { chart: ChartLike; tokens: ThemeTokens }): JSX.Element {
  const series = list(chart.series).map((entry) => {
    const item = record(entry);
    return {
      name: text(item.name),
      points: list(item.points).map((point) => {
        const data = record(point);
        return { label: text(data.label), value: Number(data.value) || 0 };
      }),
    };
  });
  const width = 760;
  const height = 360;
  const pad = { left: 54, right: 28, top: 26, bottom: 46 };
  const values = series.flatMap((entry) => entry.points.map((point) => point.value));
  const max = Math.max(1, ...values);
  const min = Math.min(0, ...values);
  const span = max - min || 1;
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const labels = series[0]?.points.map((point) => point.label) ?? [];
  const accent = tokens.vars["--color-accent"] ?? "#1F4E79";
  const primary = tokens.vars["--color-primary"] ?? "#7A1F1F";
  const palette = [primary, accent, "#8c8a7a", "#5f8b73", "#b57b3a", "#6e6f91"];
  const y = (value: number) => pad.top + plotH - ((value - min) / span) * plotH;
  const x = (index: number) =>
    pad.left + (labels.length <= 1 ? plotW / 2 : (index / (labels.length - 1)) * plotW);

  if (text(chart.type) === "pie") {
    const total = series[0]?.points.reduce((sum, point) => sum + point.value, 0) ?? 0;
    let angle = -Math.PI / 2;
    const cx = width / 2;
    const cy = height / 2;
    const radius = Math.min(plotW, plotH) / 2.2;
    return (
      <svg viewBox={`0 0 ${width} ${height}`} className="chart-svg" role="img" aria-label={text(chart.title)}>
        {series[0]?.points.map((point, index) => {
          const sweep = total ? (point.value / total) * Math.PI * 2 : 0;
          const startX = cx + radius * Math.cos(angle);
          const startY = cy + radius * Math.sin(angle);
          angle += sweep;
          const endX = cx + radius * Math.cos(angle);
          const endY = cy + radius * Math.sin(angle);
          const large = sweep > Math.PI ? 1 : 0;
          return (
            <path
              key={`${point.label}-${index}`}
              d={`M ${cx} ${cy} L ${startX} ${startY} A ${radius} ${radius} 0 ${large} 1 ${endX} ${endY} Z`}
              fill={palette[index % palette.length]}
              stroke={tokens.vars["--color-bg"] ?? "#fff"}
              strokeWidth={2}
            />
          );
        })}
      </svg>
    );
  }

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="chart-svg" role="img" aria-label={text(chart.title)}>
      {[0, 0.25, 0.5, 0.75, 1].map((ratio) => (
        <line
          key={ratio}
          x1={pad.left}
          x2={width - pad.right}
          y1={pad.top + plotH * ratio}
          y2={pad.top + plotH * ratio}
          stroke="rgba(0,0,0,0.12)"
          strokeDasharray="3 5"
        />
      ))}
      {series.map((entry, seriesIndex) => {
        const color = palette[seriesIndex % palette.length];
        if (text(chart.type) === "bar") {
          const groupWidth = plotW / Math.max(1, entry.points.length);
          const barWidth = Math.max(8, (groupWidth * 0.6) / series.length);
          return (
            <g key={entry.name}>
              {entry.points.map((point, index) => (
                <rect
                  key={`${point.label}-${index}`}
                  x={pad.left + index * groupWidth + groupWidth * 0.2 + seriesIndex * barWidth}
                  y={y(point.value)}
                  width={barWidth}
                  height={pad.top + plotH - y(point.value)}
                  fill={color}
                  rx={3}
                />
              ))}
            </g>
          );
        }
        if (text(chart.type) === "scatter") {
          return (
            <g key={entry.name}>
              {entry.points.map((point, index) => (
                <circle key={`${point.label}-${index}`} cx={x(index)} cy={y(point.value)} r={6} fill={color} />
              ))}
            </g>
          );
        }
        const d = entry.points
          .map((point, index) => `${index === 0 ? "M" : "L"} ${x(index)} ${y(point.value)}`)
          .join(" ");
        return (
          <g key={entry.name}>
            {text(chart.type) === "area" ? (
              <path
                d={`${d} L ${x(entry.points.length - 1)} ${pad.top + plotH} L ${x(0)} ${pad.top + plotH} Z`}
                fill={color}
                opacity={0.18}
              />
            ) : null}
            <path d={d} fill="none" stroke={color} strokeWidth={3} strokeLinejoin="round" />
            {entry.points.map((point, index) => (
              <circle key={`${point.label}-${index}`} cx={x(index)} cy={y(point.value)} r={4} fill={color} />
            ))}
          </g>
        );
      })}
      {labels.map((label, index) => (
        <text key={`${label}-${index}`} x={x(index)} y={height - 14} textAnchor="middle" fontSize={13} fill="#55565c">
          {label}
        </text>
      ))}
      {[min, (min + max) / 2, max].map((value) => (
        <text key={value} x={pad.left - 10} y={y(value) + 4} textAnchor="end" fontSize={12} fill="#55565c">
          {Math.round(value * 100) / 100}
          {text(chart.unit)}
        </text>
      ))}
    </svg>
  );
}

function TableView({ columns, rows }: { columns: string[]; rows: unknown[] }): JSX.Element {
  return (
    <table className="slot-table">
      <thead>
        <tr>
          {columns.map((column, index) => (
            <th key={`${column}-${index}`}>{column}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.slice(0, 10).map((row, rowIndex) => (
          <tr key={rowIndex}>
            {list(row).map((cell, cellIndex) => (
              <td key={cellIndex}>{text(cell)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

interface LayoutProps {
  slide: Slide;
  tokens: ThemeTokens;
  documentId: string | null;
  selected: string | null;
}

function CoverLayout({ slide, tokens, documentId, selected }: LayoutProps): JSX.Element {
  const bg = record(slide.slots.bg);
  const hasImage = text(bg.kind) === "image" && text(bg.assetId);
  return (
    <div className={`layout cover ${hasImage ? "with-bg" : ""}`}>
      {hasImage ? (
        <img className="cover-bg" src={assetUrl(documentId, text(bg.assetId))} alt="" />
      ) : null}
      <div className="cover-inner">
        {slide.slots.kicker ? (
          <Slot path="kicker" selected={selected}>
            <span className="kicker">{text(slide.slots.kicker)}</span>
          </Slot>
        ) : null}
        <Slot path="title" selected={selected} tag="h1" className="cover-title">
          <TypographyText value={slide.slots.title} />
        </Slot>
        {slide.slots.subtitle ? (
          <Slot path="subtitle" selected={selected} tag="p" className="cover-subtitle">
            {text(slide.slots.subtitle)}
          </Slot>
        ) : null}
      </div>
      <div className="cover-rule" style={{ background: tokens.vars["--color-primary"] }} />
    </div>
  );
}

function TocLayout({ slide, selected }: LayoutProps): JSX.Element {
  return (
    <div className="layout padded">
      <Slot path="title" selected={selected} tag="h2" className="section-title">
        <TypographyText value={slide.slots.title} />
      </Slot>
      <ol className="toc-list">
        {list(slide.slots.items).map((item, index) => (
          <li key={index} data-fragment>
            <span className="toc-index mono">{String(index + 1).padStart(2, "0")}</span>
            <span><TypographyText value={item} /></span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function BulletsLayout({ slide, selected }: LayoutProps): JSX.Element {
  return (
    <div className="layout padded">
      <Slot path="title" selected={selected} tag="h2" className="section-title">
        <TypographyText value={slide.slots.title} />
      </Slot>
      {slide.slots.lead ? (
        <Slot path="lead" selected={selected} tag="p" className="lead">
          <TypographyText value={slide.slots.lead} />
        </Slot>
      ) : null}
      <Slot path="items" selected={selected} tag="div" className="bullets">
        <ul>
          {list(slide.slots.items).map((item, index) => {
            const data = record(item);
            const main = data.text !== undefined ? text(data.text) : text(item);
            const sub = data.sub !== undefined ? text(data.sub) : "";
            return (
              <li key={index} data-fragment>
                <span className="bullet-mark" />
                <span className="bullet-body">
                  <span className="bullet-main"><TypographyText value={main} /></span>
                  {sub ? <span className="bullet-sub"><TypographyText value={sub} /></span> : null}
                </span>
              </li>
            );
          })}
        </ul>
      </Slot>
    </div>
  );
}

function SplitLrLayout(props: LayoutProps): JSX.Element {
  const { slide, selected, tokens, documentId } = props;
  const side = text(slide.slots.mediaSide) === "left" ? "left" : "right";
  return (
    <div className="layout padded">
      <Slot path="title" selected={selected} tag="h2" className="section-title">
        <TypographyText value={slide.slots.title} />
      </Slot>
      <div className={`split-lr media-${side}`}>
        <Slot path="body" selected={selected} tag="div" className="body-text">
          <TypographyText value={slide.slots.body} />
        </Slot>
        <MediaView media={slide.slots.media} tokens={tokens} documentId={documentId} selected={selected} path="media" />
      </div>
    </div>
  );
}

function SplitTbLayout(props: LayoutProps): JSX.Element {
  const { slide, selected, tokens, documentId } = props;
  return (
    <div className="layout padded">
      <Slot path="title" selected={selected} tag="h2" className="section-title">
        <TypographyText value={slide.slots.title} />
      </Slot>
      <div className="split-tb">
        <Slot path="body" selected={selected} tag="div" className="body-text">
          <TypographyText value={slide.slots.body} />
        </Slot>
        <MediaView media={slide.slots.media} tokens={tokens} documentId={documentId} selected={selected} path="media" />
      </div>
    </div>
  );
}

function CardsLayout({ slide, selected }: LayoutProps): JSX.Element {
  return (
    <div className="layout padded">
      <Slot path="title" selected={selected} tag="h2" className="section-title">
        <TypographyText value={slide.slots.title} />
      </Slot>
      <div className="cards">
        {list(slide.slots.cards).map((card, index) => {
          const data = record(card);
          return (
            <div className="card" key={index} data-fragment>
              <span className="card-index mono">{String(index + 1).padStart(2, "0")}</span>
              <h3><TypographyText value={data.heading} /></h3>
              <p><TypographyText value={data.text} /></p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ChartLayout(props: LayoutProps): JSX.Element {
  const { slide, selected, tokens } = props;
  return (
    <div className="layout padded">
      <Slot path="title" selected={selected} tag="h2" className="section-title">
        <TypographyText value={slide.slots.title} />
      </Slot>
      <div className="chart-wrap">
        <ChartView chart={record(slide.slots.chart)} tokens={tokens} />
        <div className="chart-caption">
          <Slot path="caption" selected={selected} tag="span">
            <TypographyText value={slide.slots.caption} />
          </Slot>
          <Slot path="source" selected={selected} tag="span" className="source-line">
            <TypographyText value={slide.slots.source} />
          </Slot>
        </div>
      </div>
    </div>
  );
}

function BigNumberLayout({ slide, selected }: LayoutProps): JSX.Element {
  return (
    <div className="layout padded">
      <Slot path="title" selected={selected} tag="h2" className="section-title">
        <TypographyText value={slide.slots.title} />
      </Slot>
      <div className="numbers">
        {list(slide.slots.numbers).map((entry, index) => {
          const data = record(entry);
          return (
            <div className="number-block" key={index}>
              <span className="number-value"><TypographyText value={data.value} /></span>
              <span className="number-label"><TypographyText value={data.label} /></span>
            </div>
          );
        })}
      </div>
      {slide.slots.note ? <p className="note-line"><TypographyText value={slide.slots.note} /></p> : null}
    </div>
  );
}

function QuoteLayout({ slide, selected }: LayoutProps): JSX.Element {
  return (
    <div className="layout quote-layout">
      <span className="quote-mark">“</span>
      <Slot path="quote" selected={selected} tag="blockquote" className="quote-text">
        <TypographyText value={slide.slots.quote} />
      </Slot>
      <div className="quote-meta">
        {slide.slots.author ? (
          <Slot path="author" selected={selected} tag="span">
            <TypographyText value={slide.slots.author} />
          </Slot>
        ) : null}
        <span className="source-line"><TypographyText value={slide.slots.source} /></span>
      </div>
    </div>
  );
}

function CompareLayout({ slide, selected }: LayoutProps): JSX.Element {
  return (
    <div className="layout padded">
      <Slot path="title" selected={selected} tag="h2" className="section-title">
        <TypographyText value={slide.slots.title} />
      </Slot>
      <div className="compare">
        {(["left", "right"] as const).map((side) => (
          <div className={`compare-col ${side}`} key={side}>
            <span className="compare-tag mono">{side === "left" ? "A" : "B"}</span>
            <ul>
              {list(slide.slots[side]).map((item, index) => (
                <li key={index} data-fragment><TypographyText value={item} /></li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

function TimelineLayout({ slide, selected }: LayoutProps): JSX.Element {
  return (
    <div className="layout padded">
      <Slot path="title" selected={selected} tag="h2" className="section-title">
        <TypographyText value={slide.slots.title} />
      </Slot>
      <div className="timeline">
        {list(slide.slots.nodes).map((node, index) => {
          const data = record(node);
          return (
            <div className="timeline-node" key={index} data-fragment>
              <span className="timeline-time mono"><TypographyText value={data.time} /></span>
              <span className="timeline-dot" />
              <span className="timeline-text"><TypographyText value={data.text} /></span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ProcessLayout({ slide, selected }: LayoutProps): JSX.Element {
  return (
    <div className="layout padded">
      <Slot path="title" selected={selected} tag="h2" className="section-title">
        <TypographyText value={slide.slots.title} />
      </Slot>
      <div className="process">
        {list(slide.slots.steps).map((step, index) => {
          const data = record(step);
          return (
            <div className="process-step" key={index} data-fragment>
              <span className="process-index">{index + 1}</span>
              <h3><TypographyText value={data.label} /></h3>
              <p><TypographyText value={data.text} /></p>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function FullImageLayout(props: LayoutProps): JSX.Element {
  const { slide, selected, tokens, documentId } = props;
  return (
    <div className="layout full-image">
      <div className="full-image-media">
        <MediaView media={slide.slots.media} tokens={tokens} documentId={documentId} selected={selected} path="media" />
      </div>
      <div className="full-image-meta">
        <Slot path="caption" selected={selected} tag="span">
          <TypographyText value={slide.slots.caption} />
        </Slot>
        <span className="source-line"><TypographyText value={slide.slots.source} /></span>
      </div>
    </div>
  );
}

function EndingLayout({ slide, selected }: LayoutProps): JSX.Element {
  return (
    <div className="layout ending">
      <Slot path="title" selected={selected} tag="h2" className="ending-title">
        <TypographyText value={slide.slots.title} />
      </Slot>
      {slide.slots.message ? (
        <Slot path="message" selected={selected} tag="p" className="ending-message">
          <TypographyText value={slide.slots.message} />
        </Slot>
      ) : null}
      {slide.slots.contact ? (
        <Slot path="contact" selected={selected} tag="span" className="ending-contact mono">
          <TypographyText value={slide.slots.contact} />
        </Slot>
      ) : null}
    </div>
  );
}

const LAYOUT_COMPONENTS: Record<string, (props: LayoutProps) => JSX.Element> = {
  cover: CoverLayout,
  toc: TocLayout,
  bullets: BulletsLayout,
  "split-lr": SplitLrLayout,
  "split-tb": SplitTbLayout,
  "cards-3": CardsLayout,
  chart: ChartLayout,
  "big-number": BigNumberLayout,
  quote: QuoteLayout,
  compare: CompareLayout,
  timeline: TimelineLayout,
  process: ProcessLayout,
  "full-image": FullImageLayout,
  ending: EndingLayout,
};

export function LayoutView(props: LayoutProps): JSX.Element {
  const Component = LAYOUT_COMPONENTS[props.slide.layout] ?? BulletsLayout;
  return <Component {...props} />;
}

export const SLIDE_CSS = `
.stage {
  width: 1280px;
  height: 720px;
  background: var(--color-bg);
  color: var(--color-text);
  position: relative;
  overflow: hidden;
  box-sizing: border-box;
}
.layout {
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
}
.padded { padding: 64px 84px 56px; gap: 18px; }
.section-title { font-size: 46px; letter-spacing: -0.01em; color: var(--color-text); margin: 0 0 6px; }
.lead { font-size: 20px; color: var(--color-muted); margin: 0 0 6px; }
.slot { position: relative; border-radius: 6px; }
.slot.is-selected { outline: 2px solid var(--color-primary); outline-offset: 6px; }
[data-slot]:hover { outline: 1px dashed rgba(0,0,0,0.28); outline-offset: 4px; }
.kicker { display:inline-block; font-size: 15px; letter-spacing: .22em; text-transform: uppercase; color: var(--color-primary); }
.cover { justify-content: flex-end; padding: 0 0 84px 96px; }
.cover-inner { position: relative; z-index: 2; display: flex; flex-direction: column; gap: 16px; max-width: 820px; }
.cover-title { font-size: 76px; line-height: 1.06; margin: 0; letter-spacing: -0.02em; }
.cover-subtitle { font-size: 24px; color: var(--color-muted); margin: 0; max-width: 34ch; }
.cover-rule { position: absolute; left: 96px; bottom: 56px; width: 132px; height: 5px; z-index: 2; }
.cover.with-bg .cover-inner { padding: 26px 30px; background: rgba(255,255,255,0.86); border-radius: 12px; }
.cover-bg { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.toc-list { list-style: none; margin: 14px 0 0; padding: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 14px 40px; }
.toc-list li { display: flex; gap: 16px; align-items: baseline; font-size: 24px; border-bottom: 1px solid rgba(0,0,0,0.12); padding-bottom: 12px; }
.toc-index { color: var(--color-primary); font-size: 14px; }
.bullets { flex: 1; }
.bullets ul { list-style: none; margin: 6px 0 0; padding: 0; display: flex; flex-direction: column; gap: 16px; }
.bullets li { display: flex; gap: 16px; font-size: 22px; line-height: 1.5; }
.bullet-mark { width: 8px; height: 8px; border-radius: 50%; background: var(--color-primary); margin-top: 11px; flex: none; }
.bullet-body { display: flex; flex-direction: column; gap: 4px; }
.bullet-sub { font-size: 16px; color: var(--color-muted); }
.split-lr { display: grid; grid-template-columns: 1fr 1fr; gap: 40px; flex: 1; min-height: 0; align-items: center; }
.split-lr.media-left { direction: ltr; }
.split-lr.media-left .body-text { order: 2; }
.split-tb { display: grid; grid-template-rows: auto 1fr; gap: 22px; flex: 1; min-height: 0; }
.body-text { font-size: 21px; line-height: 1.72; }
.media-frame { margin: 0; display: flex; align-items: center; justify-content: center; overflow: hidden; border-radius: 10px; min-height: 0; height: 100%; }
.media-frame img { width: 100%; height: 100%; border-radius: 10px; }
.media-placeholder { display: grid; place-items: center; border: 1px dashed rgba(0,0,0,0.25); color: #6b6c73; border-radius: 10px; height: 100%; }
.chart-svg { width: 100%; height: auto; max-height: 420px; }
.slot-table { width: 100%; border-collapse: collapse; font-size: 16px; }
.slot-table th { text-align: left; border-bottom: 2px solid var(--color-primary); padding: 8px 10px; font-weight: 600; }
.slot-table td { border-bottom: 1px solid rgba(0,0,0,0.1); padding: 8px 10px; }
.cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; flex: 1; }
.card { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: 26px; box-shadow: var(--shadow-sm); display: flex; flex-direction: column; gap: 10px; }
.card-index { color: var(--color-primary); font-size: 13px; }
.card h3 { font-size: 24px; margin: 0; }
.card p { margin: 0; font-size: 16px; line-height: 1.62; color: var(--color-muted); }
.chart-wrap { flex: 1; display: flex; flex-direction: column; justify-content: center; gap: 10px; }
.chart-caption { display: flex; justify-content: space-between; gap: 16px; font-size: 15px; color: var(--color-muted); }
.source-line { font-size: 13px; color: var(--color-muted); letter-spacing: .02em; }
.numbers { display: flex; gap: 54px; flex-wrap: wrap; margin-top: 26px; }
.number-block { display: flex; flex-direction: column; gap: 6px; }
.number-value { font-family: var(--font-display); font-size: 96px; line-height: 1; color: var(--color-primary); }
.number-label { font-size: 19px; color: var(--color-muted); }
.note-line { margin-top: auto; font-size: 14px; color: var(--color-muted); }
.quote-layout { justify-content: center; padding: 90px 110px; gap: 20px; }
.quote-mark { font-family: var(--font-display); font-size: 140px; line-height: .6; color: var(--color-primary); }
.quote-text { margin: 0; font-family: var(--font-display); font-size: 40px; line-height: 1.42; border: none; }
.quote-meta { display: flex; gap: 18px; align-items: baseline; font-size: 16px; color: var(--color-muted); }
.compare { display: grid; grid-template-columns: 1fr 1fr; gap: 26px; flex: 1; }
.compare-col { border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: 24px; background: var(--color-surface); }
.compare-col.right { background: color-mix(in srgb, var(--color-surface) 82%, var(--color-primary) 18%); }
.compare-tag { font-size: 12px; letter-spacing: .2em; color: var(--color-primary); }
.compare-col ul { margin: 12px 0 0; padding-left: 20px; display: flex; flex-direction: column; gap: 10px; font-size: 18px; }
.timeline { display: flex; gap: 18px; margin-top: 34px; flex: 1; align-items: flex-start; }
.timeline-node { flex: 1; display: flex; flex-direction: column; gap: 10px; position: relative; }
.timeline-time { color: var(--color-primary); font-size: 14px; }
.timeline-dot { width: 12px; height: 12px; border-radius: 50%; background: var(--color-primary); }
.timeline-text { font-size: 17px; line-height: 1.55; padding-top: 8px; border-top: 1px solid var(--color-border); }
.process { display: flex; gap: 16px; margin-top: 26px; flex: 1; }
.process-step { flex: 1; border-top: 3px solid var(--color-primary); padding-top: 18px; display: flex; flex-direction: column; gap: 8px; }
.process-index { font-family: var(--font-display); font-size: 34px; color: var(--color-primary); }
.process-step h3 { font-size: 21px; margin: 0; }
.process-step p { margin: 0; font-size: 15px; color: var(--color-muted); line-height: 1.6; }
.full-image { position: relative; }
.full-image-media { position: absolute; inset: 0; }
.full-image-media .media-frame { border-radius: 0; height: 100%; }
.full-image-meta { position: absolute; left: 64px; right: 64px; bottom: 36px; display: flex; justify-content: space-between; gap: 16px; color: #fff; background: rgba(10,10,14,0.55); padding: 10px 16px; border-radius: 8px; font-size: 14px; }
.ending { align-items: center; justify-content: center; gap: 18px; text-align: center; padding: 80px; }
.ending-title { font-size: 74px; margin: 0; }
.ending-message { font-size: 24px; color: var(--color-muted); margin: 0; max-width: 40ch; }
.ending-contact { font-size: 14px; letter-spacing: .18em; color: var(--color-primary); }
.degraded-flag { position: absolute; right: 18px; top: 16px; font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: #b23; border: 1px solid #b23; padding: 2px 8px; border-radius: 999px; background: rgba(255,255,255,.6); }
`;


export { Slot as SlotWrapper };
export type { LayoutProps };
