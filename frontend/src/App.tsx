import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api";
import { useAuth } from "./auth";
import { AccountsProvider } from "./accounts";
import { useWsStatus } from "./hooks";
import { Toaster, notify, useAction } from "./components/ui";
import LoginPage from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import AccountsPage from "./pages/Accounts";
import TerminalPage from "./pages/Terminal";
import BotsPage from "./pages/Bots";
import BotDetail from "./pages/BotDetail";
import AuditPage from "./pages/Audit";
import UsersPage from "./pages/Users";
import SystemPage from "./pages/System";

const NAV = [
  { to: "/", label: "Обзор", icon: "◧" },
  { to: "/terminal", label: "Терминал", icon: "⇅" },
  { to: "/bots", label: "Торговые боты", icon: "⚙" },
  { to: "/accounts", label: "Счета MT5", icon: "▣" },
  { to: "/audit", label: "Журнал аудита", icon: "☰", role: "trader" as const },
  { to: "/users", label: "Пользователи", icon: "☺", role: "admin" as const },
  { to: "/system", label: "Система", icon: "ⓘ" },
];

export default function App() {
  const { user, ready, logout, can } = useAuth();
  const wsOk = useWsStatus();
  const kill = useAction();

  if (!ready) return <div className="splash">Загрузка…</div>;
  if (!user) {
    return (
      <>
        <LoginPage />
        <Toaster />
      </>
    );
  }

  async function stopAll() {
    if (!confirm("Остановить ВСЕ торговые боты?")) return;
    await kill.run(() => api<{ stopped: number[] }>("/api/bots/stop-all", { method: "POST" }), (r) => `Остановлено ботов: ${r.stopped.length}`);
  }

  return (
    <AccountsProvider>
      <div className="layout">
        <aside className="sidebar">
          <div className="brand">
            <span className="brand-logo">◢</span>
            <div>
              <div className="brand-name">AI Trading Office</div>
              <div className="brand-sub">MetaTrader 5</div>
            </div>
          </div>
          <nav>
            {NAV.filter((n) => !n.role || can(n.role)).map((n) => (
              <NavLink key={n.to} to={n.to} end={n.to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
                <span className="nav-icon">{n.icon}</span>
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-foot">
            <div className={`ws-state ${wsOk ? "ok" : "bad"}`} title="Состояние потока данных WebSocket">
              <span className="dot" /> {wsOk ? "Поток данных активен" : "Поток данных: переподключение…"}
            </div>
            <div className="user-box">
              <div>
                <div className="user-name">{user.username}</div>
                <div className="user-role">{user.role}</div>
              </div>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  logout();
                  notify("info", "Вы вышли из системы");
                }}
              >
                Выйти
              </button>
            </div>
          </div>
        </aside>
        <main className="main">
          <header className="topbar">
            <div />
            {can("trader") && (
              <button className="btn btn-danger btn-sm" disabled={kill.busy} onClick={stopAll} title="Аварийная остановка всех ботов">
                ■ Стоп всех ботов
              </button>
            )}
          </header>
          <div className="content">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/terminal" element={<TerminalPage />} />
              <Route path="/bots" element={<BotsPage />} />
              <Route path="/bots/:id" element={<BotDetail />} />
              <Route path="/accounts" element={<AccountsPage />} />
              <Route path="/audit" element={can("trader") ? <AuditPage /> : <Navigate to="/" />} />
              <Route path="/users" element={can("admin") ? <UsersPage /> : <Navigate to="/" />} />
              <Route path="/system" element={<SystemPage />} />
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          </div>
        </main>
      </div>
      <Toaster />
    </AccountsProvider>
  );
}
