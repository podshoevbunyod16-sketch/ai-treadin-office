import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Field } from "../components/ui";
import type { User } from "../types";

export default function LoginPage() {
  const { login } = useAuth();
  const [setup, setSetup] = useState<boolean | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ setup_required: boolean }>("/api/auth/state")
      .then((s) => setSetup(s.setup_required))
      .catch((e) => setError(e.message));
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (setup && password !== password2) {
      setError("Пароли не совпадают");
      return;
    }
    setBusy(true);
    try {
      const r = await api<{ access_token: string; user: User }>(setup ? "/api/auth/setup" : "/api/auth/login", {
        method: "POST",
        body: { username, password },
      });
      login(r.access_token, r.user);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="brand brand-center">
          <span className="brand-logo">◢</span>
          <div>
            <div className="brand-name">AI Trading Office</div>
            <div className="brand-sub">Торговый офис для MetaTrader 5</div>
          </div>
        </div>
        {setup === null && !error && <p className="muted">Проверка сервера…</p>}
        {setup && (
          <div className="alert alert-info">
            Первый запуск: создайте учётную запись администратора. Пароль — минимум 10 символов, буквы и цифры.
          </div>
        )}
        <ErrorBox error={error} />
        {setup !== null && (
          <>
            <Field label="Имя пользователя">
              <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required minLength={3} />
            </Field>
            <Field label="Пароль">
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={setup ? "new-password" : "current-password"}
                required
              />
            </Field>
            {setup && (
              <Field label="Повторите пароль">
                <input type="password" value={password2} onChange={(e) => setPassword2(e.target.value)} autoComplete="new-password" required />
              </Field>
            )}
            <button className="btn btn-primary btn-block" disabled={busy}>
              {busy ? "…" : setup ? "Создать администратора" : "Войти"}
            </button>
          </>
        )}
      </form>
    </div>
  );
}
