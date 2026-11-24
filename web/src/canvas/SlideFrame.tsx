import { useEffect, useMemo, useRef, useState } from "react";

import { buildSlideDocument } from "@/canvas/slideHtml";
import { installMotionComponents } from "@/motion/components";
import type { Slide, ThemeManifest } from "@/types";

export interface SlideSelection {
  slideId: string;
  slotPath: string;
}

export interface SlideDragSelection extends SlideSelection {
  layout: { x: number; y: number; w: number; h: number };
}

interface SlideFrameProps {
  slide: Slide;
  theme: ThemeManifest | null;
  documentId: string | null;
  selectedSlot?: string | null;
  interactive?: boolean;
  onSelect?: (selection: SlideSelection) => void;
  onDrag?: (selection: SlideDragSelection) => void;
  title?: string;
  compact?: boolean;
  step?: number;
  motionLevel?: number;
}

export default function SlideFrame({
  slide,
  theme,
  documentId,
  selectedSlot = null,
  interactive = true,
  onSelect,
  onDrag,
  title,
  compact = false,
  step,
  motionLevel = 0,
}: SlideFrameProps) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const motionRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(compact ? 0.12 : 0.6);

  const html = useMemo(
    () =>
      buildSlideDocument({
        slide,
        theme,
        documentId,
        selectedSlot,
        interactive,
        step,
      }),
    [slide, theme, documentId, selectedSlot, interactive, step],
  );

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? 0;
      if (width > 0) setScale(width / 1280);
    });
    observer.observe(wrap);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!interactive || !onSelect) return;
    const handler = (event: MessageEvent) => {
      if (frameRef.current && event.source !== frameRef.current.contentWindow) return;
      const data = event.data as { type?: string; slideId?: string; slotPath?: string };
      if (data?.type === "presenta:select" && data.slideId && data.slotPath) {
        onSelect({ slideId: data.slideId, slotPath: data.slotPath });
      }
      const dragData = event.data as {
        type?: string;
        slideId?: string;
        slotPath?: string;
        layout?: { x: number; y: number; w: number; h: number };
      };
      if (
        dragData?.type === "presenta:drag" &&
        dragData.slideId &&
        dragData.slotPath &&
        dragData.layout &&
        onDrag
      ) {
        onDrag({
          slideId: dragData.slideId,
          slotPath: dragData.slotPath,
          layout: dragData.layout,
        });
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [interactive, onSelect, onDrag]);

  useEffect(() => {
    if (step === undefined) return;
    const frame = frameRef.current;
    if (!frame || !frame.contentWindow) return;
    frame.contentWindow.postMessage(
      { type: "presenta:step", step, slideId: slide.id },
      "*",
    );
  }, [step, slide.id]);

  useEffect(() => {
    const layer = motionRef.current;
    if (!layer || compact) return;
    layer.replaceChildren();
    installMotionComponents(
      layer,
      slide.elements
        .filter((element) => element.component && element.layout)
        .map((element) => ({
          name: element.component!.name,
          config: element.component!.config,
          layout: element.layout!,
        })),
      motionLevel,
      true,
    );
  }, [compact, motionLevel, slide]);

  return (
    <div className={`slide-frame-wrap ${compact ? "compact" : ""}`} ref={wrapRef}>
      <iframe
        ref={frameRef}
        title={title ?? `slide-${slide.id}`}
        sandbox="allow-scripts"
        srcDoc={html}
        style={{ transform: `scale(${scale})` }}
        tabIndex={-1}
      />
      {!compact ? (
        <div
          ref={motionRef}
          className="motion-layer"
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            width: 1280,
            height: 720,
            transform: `scale(${scale})`,
            transformOrigin: "top left",
            pointerEvents: "none",
          }}
        />
      ) : null}
    </div>
  );
}
