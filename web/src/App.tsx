import { useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import ChatPage from "./pages/ChatPage";
import EmotionPage from "./pages/EmotionPage";
import InterestPage from "./pages/InterestPage";
import LoginPage from "./pages/LoginPage";
import LuckinPage from "./pages/LuckinPage";
import MainLayout from "./layouts/MainLayout";
import MemoryPage from "./pages/MemoryPage";
import SettingsPage from "./pages/SettingsPage";
import RegisterPage from "./pages/RegisterPage";
import { useAuthStore } from "./stores/authStore";

/** 路由守卫:未登录重定向到 /login */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return <>{children}</>;
}

/** 反向守卫:已登录重定向到 / */
function RedirectIfAuth({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

function App() {
  const fetchMe = useAuthStore((s) => s.fetchMe);
  const token = useAuthStore((s) => s.token);

  // 启动时验证 token 有效性
  useEffect(() => {
    if (token) {
      fetchMe();
    }
  }, []);

  return (
    <Routes>
      <Route
        path="/login"
        element={
          <RedirectIfAuth>
            <LoginPage />
          </RedirectIfAuth>
        }
      />
      <Route
        path="/register"
        element={
          <RedirectIfAuth>
            <RegisterPage />
          </RedirectIfAuth>
        }
      />
      <Route
        path="/"
        element={
          <RequireAuth>
            <MainLayout />
          </RequireAuth>
        }
      >
        <Route index element={<Navigate to="/chat" replace />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="memory" element={<MemoryPage />} />
        <Route path="interest" element={<InterestPage />} />
        <Route path="emotion" element={<EmotionPage />} />
        <Route path="luckin" element={<LuckinPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}

export default App;
