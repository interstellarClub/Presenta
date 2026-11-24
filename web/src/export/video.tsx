import { createRoot } from "react-dom/client";
import { toCanvas } from "html-to-image";
import { ArrayBufferTarget, Muxer } from "mp4-muxer";
import { useEffect, useRef, type CSSProperties } from "react";

import { LayoutView, SLIDE_CSS } from "@/canvas/layouts";
import { installMotionComponents, type MotionSpec } from "@/motion/components";
import { buildTypographyCss } from "@/themes/fontStack";
import { themeTokens } from "@/themes/theme";
import type { DeckPayload, Slide, ThemeManifest } from "@/types";

interface EncoderChoice {
  encoderCodec: string;
  containerCodec: "avc" | "vp9";
}

export interface Mp4ExportOptions {
  fps?: number;
  secondsPerSlide?: number;
  bitrate?: number;
  onProgress?: (progress: number) => void;
}

function VideoSlide({
  slide,
  theme,
  documentId,
  motionLevel,
}: {
  slide: Slide;
  theme: ThemeManifest;
  documentId: string | null;
  motionLevel: number;
}) {
  const tokens = themeTokens(theme);
  const motionRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!motionRef.current) return;
    const specs: MotionSpec[] = slide.elements
      .filter((element) => element.component && element.layout)
      .map((element) => ({
        name: element.component!.name,
        config: element.component!.config,
        layout: element.layout!,
      }));
    installMotionComponents(motionRef.current, specs, motionLevel, false);
  }, [slide, motionLevel]);
  const style = {
    ...tokens.vars,
    width: "1280px",
    height: "720px",
  } as CSSProperties;
  return (
    <div style={style}>
      <style>{`${buildTypographyCss()}\n${SLIDE_CSS}`}</style>
      <LayoutView slide={slide} tokens={tokens} documentId={documentId} selected={null} />
      <div ref={motionRef} style={{ position: "absolute", inset: 0, pointerEvents: "none" }} />
    </div>
  );
}

async function pickEncoder(width: number, height: number, bitrate: number): Promise<EncoderChoice> {
  if (typeof VideoEncoder === "undefined") {
    throw new Error("当前浏览器不支持 WebCodecs VideoEncoder");
  }
  const candidates: EncoderChoice[] = [
    { encoderCodec: "avc1.42001f", containerCodec: "avc" },
    { encoderCodec: "vp09.00.10.08", containerCodec: "vp9" },
  ];
  for (const candidate of candidates) {
    const support = await VideoEncoder.isConfigSupported({
      codec: candidate.encoderCodec,
      width,
      height,
      bitrate,
      framerate: 30,
    });
    if (support.supported) return candidate;
  }
  throw new Error("浏览器未提供可用的 H.264 或 VP9 WebCodecs 编码器");
}

async function waitForImages(root: HTMLElement): Promise<void> {
  const images = Array.from(root.querySelectorAll("img"));
  await Promise.all(
    images.map(
      (image) =>
        new Promise<void>((resolve) => {
          if (image.complete) {
            resolve();
            return;
          }
          image.addEventListener("load", () => resolve(), { once: true });
          image.addEventListener("error", () => resolve(), { once: true });
        }),
    ),
  );
}

export async function exportDeckMp4(
  deck: DeckPayload,
  theme: ThemeManifest,
  options: Mp4ExportOptions = {},
): Promise<Blob> {
  const fps = Math.max(1, Math.min(60, Math.round(options.fps ?? 30)));
  const secondsPerSlide = Math.max(0.25, options.secondsPerSlide ?? 2);
  const bitrate = Math.max(250_000, options.bitrate ?? 4_000_000);
  const width = 1280;
  const height = 720;
  const encoderChoice = await pickEncoder(width, height, bitrate);

  const target = new ArrayBufferTarget();
  const muxer = new Muxer({
    target,
    video: {
      codec: encoderChoice.containerCodec,
      width,
      height,
      frameRate: fps,
    },
    fastStart: "in-memory",
    firstTimestampBehavior: "offset",
  });

  let encoderError: Error | null = null;
  const encoder = new VideoEncoder({
    output: (chunk, meta) => muxer.addVideoChunk(chunk, meta),
    error: (error) => {
      encoderError = error instanceof Error ? error : new Error(String(error));
    },
  });
  encoder.configure({
    codec: encoderChoice.encoderCodec,
    width,
    height,
    bitrate,
    framerate: fps,
    latencyMode: "quality",
  });

  const host = document.createElement("div");
  host.style.position = "fixed";
  host.style.left = "-20000px";
  host.style.top = "0";
  host.style.width = `${width}px`;
  host.style.height = `${height}px`;
  host.style.background = "#fff";
  host.style.zIndex = "-1";
  document.body.appendChild(host);
  const root = createRoot(host);
  const documentId = deck.meta.sourceDocumentId ?? null;
  let frameIndex = 0;
  const totalFrames = Math.max(
    1,
    deck.slides.length * Math.max(1, Math.ceil(fps * secondsPerSlide)),
  );

  try {
    for (const slide of deck.slides) {
      root.render(
        <VideoSlide
          slide={slide}
          theme={theme}
          documentId={documentId}
          motionLevel={deck.motionLevel}
        />,
      );
      await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
      await document.fonts.ready;
      await waitForImages(host);
      const fragments = Array.from(host.querySelectorAll<HTMLElement>("[data-fragment]"));
      const frameCount = Math.max(1, Math.ceil(fps * secondsPerSlide));
      const stepCount = slide.steps.length;
      for (let localFrame = 0; localFrame < frameCount; localFrame += 1) {
        if (encoderError) throw encoderError;
        (window as unknown as { presentaMotion?: { seek: (timeMs: number) => void } })
          .presentaMotion?.seek((localFrame / fps) * 1000);
        const visibleSteps =
          stepCount === 0
            ? fragments.length
            : Math.min(
                stepCount,
                Math.ceil(((localFrame + 1) * stepCount) / frameCount),
              );
        fragments.forEach((node, index) => {
          node.style.opacity = index < visibleSteps ? "1" : "0";
          node.style.transition = "none";
        });
        const canvas = await toCanvas(host, {
          width,
          height,
          pixelRatio: 1,
          backgroundColor: "#ffffff",
          fetchRequestInit: { credentials: "include" },
        });
        const timestamp = Math.round((frameIndex * 1_000_000) / fps);
        const frame = new VideoFrame(canvas, {
          timestamp,
          duration: Math.round(1_000_000 / fps),
        });
        encoder.encode(frame, { keyFrame: frameIndex % fps === 0 });
        frame.close();
        frameIndex += 1;
        if (encoder.encodeQueueSize > 8) {
          await new Promise<void>((resolve) => setTimeout(resolve, 4));
        }
        options.onProgress?.(Math.round((frameIndex / totalFrames) * 90));
      }
    }
    await encoder.flush();
    if (encoderError) throw encoderError;
    muxer.finalize();
    options.onProgress?.(100);
    return new Blob([target.buffer], { type: "video/mp4" });
  } finally {
    root.unmount();
    host.remove();
    if (encoder.state !== "closed") encoder.close();
  }
}
