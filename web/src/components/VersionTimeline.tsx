import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { VersionDiff, VersionSummary } from "@/types";

interface VersionTimelineProps {
  deckId: string;
  currentSeq: number;
  onRolledBack: () => void;
}

const KIND_LABEL: Record<string, string> = {
  anchor: "锚点",
  milestone: "里程碑",
  autosave: "自动保存",
};

export default function VersionTimeline({ deckId, currentSeq, onRolledBack }: VersionTimelineProps) {
  const [versions, setVersions] = useState<VersionSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [diff, setDiff] = useState<VersionDiff | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api<VersionSummary[]>(`/decks/${deckId}/versions`);
      setVersions(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "版本列表加载失败");
    }
  }, [deckId]);

  useEffect(() => {
    void load();
  }, [load, currentSeq]);

  const rollback = async (seq: number) => {
    setPending(true);
    setError(null);
    try {
      await api(`/decks/${deckId}/rollback`, {
        method: "POST",
        body: JSON.stringify({ targetSeq: seq }),
      });
      await load();
      onRolledBack();
    } catch (err) {
      setError(
        err instanceof ApiError ? `${err.message}（${err.code}）` : "回滚失败",
      );
    } finally {
      setPending(false);
    }
  };

  const compare = async (seq: number) => {
    setError(null);
    try {
      const result = await api<VersionDiff>(
        `/decks/${deckId}/diff?fromSeq=${seq}&toSeq=${currentSeq}`,
      );
      setDiff(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "版本对比失败");
    }
  };

  return (
    <div className="panel-stack">
      {error ? <div className="notice">{error}</div> : null}
      {diff ? (
        <div className="notice" style={{ maxHeight: 220, overflow: "auto" }}>
          <div className="doc-meta">
            <strong>
              v{diff.fromSeq} → v{diff.toSeq}
            </strong>
            <span className="muted small">{diff.count} 处变化</span>
            <button
              type="button"
              className="ghost small"
              style={{ marginLeft: "auto" }}
              onClick={() => setDiff(null)}
            >
              关闭
            </button>
          </div>
          <pre className="mono small" style={{ whiteSpace: "pre-wrap" }}>
            {JSON.stringify(diff.operations.slice(0, 30), null, 2)}
          </pre>
        </div>
      ) : null}
      {versions.length === 0 ? <div className="muted small">暂无版本</div> : null}
      {versions.map((version) => (
        <div
          key={version.id}
          className={`version-row ${version.seq === currentSeq ? "current" : ""}`}
        >
          <span className="mono">v{version.seq}</span>
          <span className={`chip ${version.kind === "milestone" ? "accent" : ""}`}>
            {KIND_LABEL[version.kind] ?? version.kind}
          </span>
          <span className="muted small" style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
            {version.label ?? version.createdAt}
          </span>
          <button
            type="button"
            className="ghost small"
            disabled={pending || version.seq === currentSeq || version.seq === 1}
            onClick={() => void rollback(version.seq)}
            title={version.seq === 1 ? "初始版本尚未生成页面，不能回退" : undefined}
          >
            回退
          </button>
          <button
            type="button"
            className="ghost small"
            disabled={version.seq === currentSeq}
            onClick={() => void compare(version.seq)}
          >
            对比
          </button>
        </div>
      ))}
    </div>
  );
}
