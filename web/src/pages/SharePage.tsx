import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import SlideFrame from "@/canvas/SlideFrame";
import { exportDeckMp4 } from "@/export/video";
import { api, ApiError } from "@/lib/api";
import type { DeckPayload, ThemeManifest } from "@/types";

interface GuestInfo {
  title: string;
  requiresPassword: boolean;
  expiresAt: string;
}

interface UnlockedPayload {
  deck: DeckPayload;
  versionSeq: number;
  allowDownload: boolean;
  downloadFormats: string[];
  degradedSlides: string[];
}

interface DownloadPayload {
  url: string;
  degraded: boolean;
  degradedNotes: string[];
}

export default function SharePage() {
  const { slug = "" } = useParams();
  const [info, setInfo] = useState<GuestInfo | null>(null);
  const [password, setPassword] = useState("");
  const [unlocked, setUnlocked] = useState<UnlockedPayload | null>(null);
  const [themes, setThemes] = useState<ThemeManifest[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloadNote, setDownloadNote] = useState<string | null>(null);

  useEffect(() => {
    void api<GuestInfo>(`/shares/guest/${slug}`)
      .then(setInfo)
      .catch((err: Error) => setError(err.message));
    void api<ThemeManifest[]>("/themes").then(setThemes).catch(() => undefined);
  }, [slug]);

  const unlock = async () => {
    setError(null);
    try {
      const payload = await api<UnlockedPayload>(`/shares/guest/${slug}/unlock`, {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      setUnlocked(payload);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "解锁失败");
    }
  };

  const download = async (format: string) => {
    setDownloadError(null);
    setDownloadNote(null);
    try {
      if (format === "mp4") {
        const theme = themes.find((entry) => entry.id === unlocked?.deck.themeId);
        if (!theme) throw new Error("没有可用于 MP4 导出的主题");
        const blob = await exportDeckMp4(unlocked!.deck, theme, {
          fps: 30,
          secondsPerSlide: 2,
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `presenta-${slug}.mp4`;
        link.click();
        URL.revokeObjectURL(url);
        setDownloadNote("MP4 已在本地逐帧编码，未上传到服务器。");
        return;
      }
      const payload = await api<DownloadPayload>(
        `/shares/guest/${slug}/downloads/${format}`,
        { method: "POST" },
      );
      if (payload.degraded) {
        setDownloadNote(payload.degradedNotes.join("；"));
      }
      window.open(payload.url, "_blank", "noopener");
    } catch (err) {
      setDownloadError(err instanceof ApiError ? err.message : "下载失败");
    }
  };

  if (error && !info) return <div className="share-screen"><div className="share-card">{error}</div></div>;

  if (!info) {
    return (
      <div className="share-screen">
        <div className="share-card">正在加载分享内容…</div>
      </div>
    );
  }

  if (!unlocked) {
    return (
      <div className="share-screen">
        <form
          className="share-card"
          onSubmit={(event) => {
            event.preventDefault();
            void unlock();
          }}
        >
          <span className="badge">Presenta 分享</span>
          <h2 style={{ fontSize: 28 }}>{info.title}</h2>
          <p className="muted small">
            该分享有效期至 {new Date(info.expiresAt).toLocaleString()}。
            {info.requiresPassword ? "需要访问密码。" : ""}
          </p>
          {info.requiresPassword ? (
            <div className="field">
              <span>访问密码</span>
              <input
                type="password"
                value={password}
                required
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
          ) : null}
          {error ? <div className="form-error">{error}</div> : null}
          <button type="submit" className="primary">
            进入播放
          </button>
        </form>
      </div>
    );
  }

  const deck = unlocked.deck;
  const slide = deck.slides[index];

  return (
    <div className="share-screen" style={{ display: "block" }}>
      <div className="share-player" style={{ margin: "0 auto" }}>
        <div className="share-toolbar">
          <div className="inline-actions">
            <span className="badge">只读播放</span>
            <strong>{deck.meta.title}</strong>
            {unlocked.degradedSlides.length > 0 ? (
              <span className="chip warn">{unlocked.degradedSlides.length} 页降级</span>
            ) : null}
          </div>
          <div className="inline-actions">
            <span className="mono muted">
              {index + 1}/{deck.slides.length}
            </span>
            {unlocked.allowDownload
              ? unlocked.downloadFormats.map((format) => (
                  <button
                    key={format}
                    type="button"
                    className="ghost small"
                    onClick={() => void download(format)}
                  >
                    {format.toUpperCase()}
                  </button>
                ))
              : null}
          </div>
        </div>
        {downloadNote ? <div className="notice">下载说明：{downloadNote}</div> : null}
        {downloadError ? <div className="notice">{downloadError}</div> : null}
        {slide ? (
          <SlideFrame
            slide={slide}
            theme={themes.find((entry) => entry.id === deck.themeId) ?? null}
            documentId={deck.meta.sourceDocumentId ?? null}
            motionLevel={deck.motionLevel}
            interactive={false}
            title={`share-${slide.id}`}
          />
        ) : null}
        <div className="inline-actions" style={{ justifyContent: "center" }}>
          <button
            type="button"
            className="ghost"
            disabled={index === 0}
            onClick={() => setIndex((value) => Math.max(0, value - 1))}
          >
            上一页
          </button>
          <button
            type="button"
            className="primary"
            disabled={index >= deck.slides.length - 1}
            onClick={() => setIndex((value) => Math.min(deck.slides.length - 1, value + 1))}
          >
            下一页
          </button>
        </div>
      </div>
    </div>
  );
}
