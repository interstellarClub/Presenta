import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { JobView } from "@/types";

interface JobProgressProps {
  jobId: string | null;
  onTerminal?: (job: JobView) => void;
}

export default function JobProgress({ jobId, onTerminal }: JobProgressProps) {
  const [job, setJob] = useState<JobView | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setJob(null);
    setError(null);
    if (!jobId) return;

    let closed = false;
    const source = new EventSource(`/api/jobs/${jobId}/events`);
    source.addEventListener("progress", (event) => {
      try {
        const payload = JSON.parse((event as MessageEvent).data) as JobView;
        setJob(payload);
      } catch {
        setError("进度数据解析失败");
      }
    });
    source.addEventListener("done", () => {
      void api<JobView>(`/jobs/${jobId}`)
        .then((latest) => {
          if (!closed) {
            setJob(latest);
            onTerminal?.(latest);
          }
        })
        .catch(() => undefined)
        .finally(() => source.close());
    });
    source.addEventListener("error", () => {
      source.close();
      void api<JobView>(`/jobs/${jobId}`)
        .then((latest) => {
          setJob(latest);
          onTerminal?.(latest);
        })
        .catch((err: Error) => setError(err.message));
    });

    return () => {
      closed = true;
      source.close();
    };
  }, [jobId, onTerminal]);

  if (!jobId) return null;

  const percent = job?.progress ?? 0;
  const stage = job?.stage ?? "排队中";

  return (
    <div className="panel-stack">
      <div className="progress-line">
        <span className="mono">{stage}</span>
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${Math.max(4, percent)}%` }} />
        </div>
        <span className="mono">{percent}%</span>
      </div>
      {error ? <div className="notice">{error}</div> : null}
      {job?.status === "failed" ? (
        <div className="notice">
          任务失败：{String(job.error?.message ?? "未知错误")}
        </div>
      ) : null}
      {job?.status === "partial" ? (
        <div className="notice">
          部分页面降级为纯文本页，可在画布中逐页修正（详见 result.degradedSlides）。
        </div>
      ) : null}
    </div>
  );
}