import { FormEvent, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, Field, StatusBadge, notify } from "../components/ui";
import { useApi, useInterval } from "../hooks";
import type { SystemStatus, User } from "../types";

export default function SystemPage() {
  const { data, error, reload } = useApi<SystemStatus>("/api/system/status");
  const { login } = useAuth();
  useInterval(reload, 10000);
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [pwErr, setPwErr] = useState<string | null>(null);

  async function changePw(e: FormEvent) {
    e.preventDefault();
    setPwErr(null);
    try {
      const r = await api<{ access_token: string; user: User }>("/api/auth/change-password", {
        method: "POST",
        body: { current_password: cur, password: pw },
      });
      login(r.access_token, r.user);
      setCur("");
      setPw("");
      notify("ok", "Пароль изменён. Остальные сессии завершены.");
    } catch (err) {
      setPwErr((err as Error).message);
    }
  }

  return (
    <div className="page">
      <h1>Система</h1>
      <ErrorBox error={error} />
      {data && (
        <div className="grid-2 gap">
          <div className="card">
            <h3>Сервер</h3>
            <div className="kv-grid">
              <span>Версия</span>
              <b>{data.version}</b>
              <span>Окружение</span>
              <b>{data.environment}</b>
              <span>ОС сервера</span>
              <b>{data.platform}</b>
              <span>Python</span>
              <b>{data.python}</b>
              <span>Время сервера (UTC)</span>
              <b>{new Date(data.server_time * 1000).toISOString().replace("T", " ").slice(0, 19)}</b>
              <span>Клиентов WebSocket</span>
              <b>{data.ws_clients}</b>
              <span>Боты в работе</span>
              <b>{data.bots_running.length ? data.bots_running.map((b) => `#${b}`).join(", ") : "нет"}</b>
              <span>Торговля на реальных счетах</span>
              <b className={data.allow_real_trading ? "neg" : "pos"}>{data.allow_real_trading ? "РАЗРЕШЕНА" : "запрещена (только demo/contest)"}</b>
            </div>
          </div>
          <div className="card">
            <h3>Интеграция MetaTrader 5</h3>
            <div className="kv-grid">
              <span>Пакет MetaTrader5 на сервере</span>
              <b className={data.mt5_package_installed ? "pos" : "neg"}>{data.mt5_package_installed ? "установлен" : "не установлен"}</b>
              <span>Режим «local»</span>
              <b className={data.local_mode_available ? "pos" : "neg"}>{data.local_mode_available ? "доступен" : "недоступен"}</b>
              <span>Режим «bridge»</span>
              <b className="pos">доступен (нужен агент на Windows рядом с терминалом)</b>
            </div>
            {data.local_mode_note && <div className="alert alert-warn">{data.local_mode_note}</div>}
            <h4>Подключения</h4>
            {data.accounts.length === 0 && <div className="muted small">Нет активных подключений</div>}
            {data.accounts.map((a) => (
              <div key={a.account_id} className="row gap-s small">
                Счёт #{a.account_id}: <StatusBadge status={a.status} /> {a.error && <span className="error-text">{a.error}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="card narrow">
        <h3>Смена пароля</h3>
        <form className="form" onSubmit={changePw}>
          <ErrorBox error={pwErr} />
          <Field label="Текущий пароль">
            <input type="password" value={cur} onChange={(e) => setCur(e.target.value)} required autoComplete="current-password" />
          </Field>
          <Field label="Новый пароль">
            <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} required autoComplete="new-password" />
          </Field>
          <button className="btn btn-primary">Сменить пароль</button>
        </form>
      </div>
    </div>
  );
}
