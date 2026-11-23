import { useEffect, useMemo, useRef, useState } from "react";

import { buildSlideDocument } from "@/canvas/slideHtml";
import type { Slide, ThemeManifest } from "@/types";

export interface SlideSelection {
  slideId: string;
  slotPath: string;
}

interface SlideFrameProps {
  slide: Slide;
  theme: ThemeManifest | null;
  documentId: string | null;
  selectedSlot?: string | null;
  interactive?: boolean;
  onSelect?: (selection: SlideSelection) => void;
  title?: string;
  compact?: boolean;
}

export default function SlideFrame({
  slide,
  theme,
  documentId,
  selectedSlot = null,
  interactive = true,
  onSelect,
  title,
  compact = false,
}: SlideFrameProps) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(compact ? 0.12 : 0.6);

  const html = useMemo(
    () =>
      buildSlideDocument({
        slide,
        theme,
        documentId,
        selectedSlot,
        interactive,
      }),
    [slide, theme, documentId, selectedSlot, interactive],
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
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [interactive, onSelect]);

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
    </div>
  );
}