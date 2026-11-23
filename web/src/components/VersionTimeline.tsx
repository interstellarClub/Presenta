import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { VersionSummary } from "@/types";

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

  return (
    <div className="panel-stack">
      {error ? <div className="notice">{error}</div> : null}
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
            disabled={pending || version.seq === currentSeq}
            onClick={() => void rollback(version.seq)}
          >
            回退
          </button>
        </div>
      ))}
    </div>
  );
}