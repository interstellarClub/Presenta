import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import SlideFrame from "@/canvas/SlideFrame";
import { api } from "@/lib/api";
import type { DeckResponse, ThemeManifest } from "@/types";

export default function DeckPlayerPage() {
  const { deckId = "" } = useParams();
  const [response, setResponse] = useState<DeckResponse | null>(null);
  const [themes, setThemes] = useState<ThemeManifest[]>([]);
  const [index, setIndex] = useState(0);
  const [step, setStep] = useState(0);
  const [notesVisible, setNotesVisible] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api<DeckResponse>(`/decks/${deckId}`)
      .then(setResponse)
      .catch((err: Error) => setError(err.message));
    void api<ThemeManifest[]>("/themes").then(setThemes).catch(() => undefined);
  }, [deckId]);

  const deck = response?.deck ?? null;
  const slide = deck?.slides[index] ?? null;
  const documentId = deck?.meta.sourceDocumentId ?? null;
  const theme = useMemo(
    () => themes.find((entry) => entry.id === deck?.themeId) ?? null,
    [themes, deck],
  );
  const maxStep = slide ? Math.max(0, slide.steps.length) : 0;

  const next = useCallback(() => {
    if (!deck) return;
    if (step < maxStep) {
      setStep((value) => value + 1);
      return;
    }
    setIndex((value) => Math.min(deck.slides.length - 1, value + 1));
    setStep(0);
  }, [deck, step, maxStep]);

  const previous = useCallback(() => {
    if (step > 0) {
      setStep((value) => value - 1);
      return;
    }
    setIndex((value) => Math.max(0, value - 1));
    setStep(0);
  }, [step]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "ArrowRight" || event.key === "PageDown" || event.key === " ") {
        event.preventDefault();
        next();
      } else if (event.key === "ArrowLeft" || event.key === "PageUp") {
        event.preventDefault();
        previous();
      } else if (event.key.toLowerCase() === "n") {
        setNotesVisible((value) => !value);
      } else if (event.key === "Escape") {
        setNotesVisible(false);
      } else if (event.key.toLowerCase() === "f") {
        void document.documentElement.requestFullscreen?.();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [next, previous]);

  if (error) return <div className="empty">{error}</div>;
  if (!deck || !slide) return <div className="empty">加载中…</div>;

  return (
    <div className="share-screen" style={{ display: "block", padding: 20 }}>
      <div className="share-player">
        <div className="share-toolbar">
          <div className="inline-actions">
            <Link className="muted small" to={`/decks/${deckId}`}>
              ← 返回编辑
            </Link>
            <span className="badge">{theme?.name ?? deck.themeId}</span>
            <span className="badge">motion {deck.motionLevel.toFixed(2)}</span>
            {slide.transition ? <span className="badge">{slide.transition.effect}</span> : null}
          </div>
          <div className="inline-actions">
            <span className="mono muted">
              {index + 1}/{deck.slides.length}
              {maxStep ? ` · step ${step}/${maxStep}` : ""}
            </span>
            <button type="button" className="ghost small" onClick={() => setNotesVisible((v) => !v)}>
              备注
            </button>
            <button type="button" className="ghost small" onClick={() => void document.documentElement.requestFullscreen?.()}>
              全屏
            </button>
          </div>
        </div>

        <SlideFrame
          slide={slide}
          theme={theme}
          documentId={documentId}
          motionLevel={deck.motionLevel}
          interactive={false}
          title={`player-${slide.id}`}
          step={maxStep > 0 ? step : undefined}
        />

        {notesVisible ? (
          <div className="panel">
            <h2>演讲备注</h2>
            <p className="muted">{slide.notes || "本页没有备注。"}</p>
            {slide.steps.length > 0 ? (
              <ol className="muted small">
                {slide.steps.map((entry, stepIndex) => (
                  <li key={stepIndex} style={{ opacity: stepIndex < step ? 0.5 : 1 }}>
                    {entry}
                  </li>
                ))}
              </ol>
            ) : null}
          </div>
        ) : null}

        <div className="inline-actions" style={{ justifyContent: "center" }}>
          <button type="button" className="ghost" onClick={previous}>
            上一页
          </button>
          <button type="button" className="primary" onClick={next}>
            {step < maxStep ? "下一步" : "下一页"}
          </button>
        </div>
      </div>
    </div>
  );
}
