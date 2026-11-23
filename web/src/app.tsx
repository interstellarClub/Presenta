import type { ReactNode } from "react";
import { NavLink, Navigate, Route, Routes, useNavigate } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import DeckPlayerPage from "@/pages/DeckPlayerPage";
import DocumentPage from "@/pages/DocumentPage";
import DocumentsPage from "@/pages/DocumentsPage";
import LoginPage from "@/pages/LoginPage";
import SharePage from "@/pages/SharePage";
import StudioPage from "@/pages/StudioPage";

function Protected({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="boot">正在加载会话…</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function Chrome({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="chrome">
      <header className="topbar">
        <NavLink to="/" className="brand">
          <span className="brand-mark">P</span>
          <span className="brand-text">
            <strong>Presenta</strong>
            <small>文档进 · 演示文稿出</small>
          </span>
        </NavLink>
        <nav className="topnav">
          <NavLink to="/" end>
            文稿
          </NavLink>
        </nav>
        <div className="account">
          <span className="account-email">{user?.displayName || user?.email}</span>
          <button
            type="button"
            className="ghost"
            onClick={() => {
              void logout().then(() => navigate("/login"));
            }}
          >
            退出
          </button>
        </div>
      </header>
      <main className="page">{children}</main>
    </div>
  );
}

export default function App() {
  const { user, loading } = useAuth();
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/share/:slug" element={<SharePage />} />
      <Route path="/s/:slug" element={<SharePage />} />
      <Route
        path="/"
        element={
          <Protected>
            <Chrome>
              <DocumentsPage />
            </Chrome>
          </Protected>
        }
      />
      <Route
        path="/documents/:documentId"
        element={
          <Protected>
            <Chrome>
              <DocumentPage />
            </Chrome>
          </Protected>
        }
      />
      <Route
        path="/decks/:deckId"
        element={
          <Protected>
            <StudioPage />
          </Protected>
        }
      />
      <Route
        path="/decks/:deckId/present"
        element={
          <Protected>
            <DeckPlayerPage />
          </Protected>
        }
      />
      <Route
        path="*"
        element={<Navigate to={loading || user ? "/" : "/login"} replace />}
      />
    </Routes>
  );
}