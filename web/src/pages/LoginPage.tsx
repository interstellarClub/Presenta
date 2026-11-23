import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { ApiError } from "@/lib/api";

type Mode = "login" | "register";

export default function LoginPage() {
  const { user, login, register } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (user) navigate("/", { replace: true });
  }, [user, navigate]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register({
          email,
          password,
          inviteCode,
          displayName: displayName || undefined,
        });
      }
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("操作失败，请稍后再试");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-screen">
      <section className="auth-poster">
        <div className="auth-meta">
          <span>PROJECT PROPOSAL · V1.0</span>
          <span>M1 — M7</span>
        </div>
        <div>
          <h1>文档进，演示文稿出。</h1>
          <p className="tagline">
            结构化的 Schema 是唯一真相，HTML 只是渲染产物。
            每一处编辑都是 JSON Patch，每一份导出都能溯源回原文。
          </p>
        </div>
        <div className="auth-meta">
          <span>Deck · Slide · Element</span>
          <span>DeepSeek · FastAPI · React</span>
        </div>
      </section>

      <section className="auth-form-wrap">
        <form className="auth-card" onSubmit={submit}>
          <div>
            <h2>{mode === "login" ? "回到你的文稿" : "申请一个账号"}</h2>
            <p className="muted small">
              {mode === "login"
                ? "使用邀请码注册的邮箱登录。"
                : "平台统一出 Key，注册需要邀请码。"}
            </p>
          </div>

          <div className="auth-tabs">
            <button
              type="button"
              className={mode === "login" ? "active" : ""}
              onClick={() => setMode("login")}
            >
              登录
            </button>
            <button
              type="button"
              className={mode === "register" ? "active" : ""}
              onClick={() => setMode("register")}
            >
              注册
            </button>
          </div>

          <div className="field">
            <span>邮箱</span>
            <input
              type="email"
              value={email}
              autoComplete="email"
              required
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>

          <div className="field">
            <span>密码</span>
            <input
              type="password"
              value={password}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              minLength={mode === "register" ? 10 : 1}
              onChange={(event) => setPassword(event.target.value)}
            />
            {mode === "register" ? (
              <span className="muted small">至少 10 位，同时包含字母与数字。</span>
            ) : null}
          </div>

          {mode === "register" ? (
            <>
              <div className="field">
                <span>邀请码</span>
                <input
                  value={inviteCode}
                  placeholder="XXXX-XXXX-XXXX"
                  required
                  onChange={(event) => setInviteCode(event.target.value)}
                />
              </div>
              <div className="field">
                <span>显示名称（可选）</span>
                <input
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                />
              </div>
            </>
          ) : null}

          <div className="form-error">{error}</div>

          <button type="submit" className="primary" disabled={busy}>
            {busy ? "处理中…" : mode === "login" ? "登录" : "创建账号"}
          </button>
        </form>
      </section>
    </div>
  );
}