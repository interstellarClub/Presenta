import { useCallback, useEffect, useState } from "react";

import JobProgress from "@/components/JobProgress";
import { api, ApiError } from "@/lib/api";
import { exportDeckMp4 } from "@/export/video";
import type {
  DeckResponse,
  ExportArtifact,
  JobView,
  ShareSummary,
  ThemeManifest,
} from "@/types";

interface ExportPanelProps {
  deckId: string;
  versionSeq: number;
}

const FORMAT_LABEL: Record<string, string> = {
  html: "独立 HTML",
  pdf: "PDF",
  pptx: "PPTX",
  gif: "GIF",
  mp4: "MP4（客户端）",
};

export default function ExportPanel({ deckId, versionSeq }: ExportPanelProps) {
  const [artifacts, setArtifacts] = useState<ExportArtifact[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [shares, setShares] = useState<ShareSummary[]>([]);
  const [password, setPassword] = useState("");
  const [ttlHours, setTtlHours] = useState(72);
  const [formats, setFormats] = useState<string[]>(["pdf", "html", "pptx", "gif", "mp4"]);
  const [busy, setBusy] = useState(false);
  const [videoProgress, setVideoProgress] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const [artifactList, shareList] = await Promise.all([
        api<ExportArtifact[]>(`/exports?deckId=${deckId}`),
        api<ShareSummary[]>(`/shares?deckId=${deckId}`),
      ]);
      setArtifacts(artifactList);
      setShares(shareList);
    } catch (err) {
      setError(err instanceof Error ? err.message : "导出记录加载失败");
    }
  }, [deckId]);

  useEffect(() => {
    void load();
  }, [load, versionSeq]);

  const startExport = async (format: string) => {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      if (format === "mp4") {
        setVideoProgress(0);
        const [deckResponse, themes] = await Promise.all([
          api<DeckResponse>(`/decks/${deckId}`),
          api<ThemeManifest[]>("/themes"),
        ]);
        const theme =
          themes.find((entry) => entry.id === deckResponse.deck.themeId) ?? themes[0];
        if (!theme) throw new Error("没有可用于 MP4 导出的主题");
        const blob = await exportDeckMp4(deckResponse.deck, theme, {
          fps: 30,
          secondsPerSlide: 2,
          onProgress: setVideoProgress,
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `presenta-${deckId}.mp4`;
        link.click();
        URL.revokeObjectURL(url);
        setNotice("MP4 已完成 WebCodecs 逐帧编码。");
        return;
      }
      const payload = await api<{
        jobId?: string;
        artifact?: ExportArtifact;
        cached: boolean;
      }>("/exports", {
        method: "POST",
        body: JSON.stringify({ deckId, format, options: {} }),
      });
      if (payload.artifact) {
        setNotice(payload.cached ? "命中同版本缓存，秒出。" : "导出完成。");
        await load();
      }
      if (payload.jobId) setJobId(payload.jobId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "导出失败");
    } finally {
      setBusy(false);
      setVideoProgress(null);
    }
  };

  const createShare = async () => {
    setError(null);
    setBusy(true);
    try {
      await api<ShareSummary>("/shares", {
        method: "POST",
        body: JSON.stringify({
          deckId,
          password,
          ttlHours,
          allowDownload: true,
          formats,
        }),
      });
      setPassword("");
      setNotice("分享已创建。过期与吊销独立于文稿留存。");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "创建分享失败");
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (shareId: string) => {
    try {
      await api(`/shares/${shareId}/revoke`, { method: "POST" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "吊销失败");
    }
  };

  const onJobTerminal = (job: JobView) => {
    if (job.status === "partial" && job.result?.notes) {
      setNotice(`导出完成，存在降级：${(job.result.notes as string[]).join("；")}`);
    }
    void load();
  };

  return (
    <div className="panel-stack">
      {error ? <div className="notice">{error}</div> : null}
      {notice ? <div className="notice">{notice}</div> : null}
      {videoProgress !== null ? (
        <div className="progress-line">
          <span className="mono">MP4 逐帧编码</span>
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${Math.max(2, videoProgress)}%` }} />
          </div>
          <span className="mono">{videoProgress}%</span>
        </div>
      ) : null}

      <div>
        <h2 style={{ marginBottom: 8 }}>导出</h2>
        <div className="inline-actions">
          {Object.keys(FORMAT_LABEL).map((format) => (
            <button
              key={format}
              type="button"
              className={format === "html" ? "primary" : ""}
              disabled={busy}
              onClick={() => void startExport(format)}
            >
              {FORMAT_LABEL[format]}
            </button>
          ))}
        </div>
        <p className="muted small" style={{ marginTop: 8 }}>
          详情：PDF 服务端 Chromium 静态快照；PPTX 转场白名单 + 静态图；GIF 256 色；任何降级会在下方标注。
        </p>
      </div>

      {jobId ? <JobProgress jobId={jobId} onTerminal={onJobTerminal} /> : null}

      <div className="panel-stack">
        {artifacts.length === 0 ? (
          <div className="muted small">当前版本还没有导出产物。</div>
        ) : (
          artifacts.map((artifact) => (
            <div key={artifact.id} className="version-row" style={{ flexDirection: "column", alignItems: "flex-start" }}>
              <div className="inline-actions" style={{ width: "100%" }}>
                <span className="chip">{artifact.format.toUpperCase()}</span>
                <span className="mono muted small">{Math.round(artifact.bytes / 1024)} KB</span>
                {artifact.degraded ? <span className="chip warn">有降级</span> : null}
                <a
                  href={artifact.downloadUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="ghost small"
                  style={{ marginLeft: "auto", padding: "4px 10px" }}
                >
                  下载
                </a>
              </div>
              {artifact.degradedNotes.length > 0 ? (
                <span className="muted small">{artifact.degradedNotes.join("；")}</span>
              ) : null}
              {artifact.degradedDetails.length > 0 ? (
                <div className="muted small" style={{ marginTop: 4 }}>
                  降级页面：
                  {artifact.degradedDetails.map((detail) => (
                    <span key={detail.slideId} className="chip warn" style={{ marginLeft: 6 }}>
                      第 {detail.slideIndex + 1} 页 · {detail.reason}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          ))
        )}
      </div>

      <div>
        <h2 style={{ marginBottom: 8 }}>分享</h2>
        <div className="panel-stack">
          <input
            placeholder="访问密码（至少 4 位）"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <div className="inline-actions">
            <label className="muted small">
              有效期（小时）
              <input
                type="number"
                min={1}
                max={8760}
                value={ttlHours}
                style={{ width: 90, marginLeft: 8 }}
                onChange={(event) => setTtlHours(Number(event.target.value) || 72)}
              />
            </label>
            {["pdf", "html", "pptx", "gif", "mp4"].map((format) => (
              <label key={format} className="muted small">
                <input
                  type="checkbox"
                  checked={formats.includes(format)}
                  onChange={(event) => {
                    setFormats((current) =>
                      event.target.checked
                        ? [...current, format]
                        : current.filter((entry) => entry !== format),
                    );
                  }}
                />{" "}
                {format.toUpperCase()}
              </label>
            ))}
          </div>
          <button type="button" onClick={() => void createShare()} disabled={busy || password.length < 4}>
            创建分享链接
          </button>
        </div>

        {shares.map((share) => (
          <div key={share.id} className="version-row" style={{ marginTop: 8 }}>
            <span className="mono small">{share.slug}</span>
            <span className="muted small">
              {new Date(share.expiresAt).toLocaleString()} · {share.viewCount} 次查看
            </span>
            <button
              type="button"
              className="ghost small"
              onClick={() => void navigator.clipboard?.writeText(`${window.location.origin}/s/${share.slug}`)}
            >
              复制
            </button>
            <button type="button" className="ghost small" onClick={() => void revoke(share.id)}>
              吊销
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
