import { FormEvent, useState } from "react";
import { api } from "../api";
import { useAccounts } from "../accounts";
import { useAuth } from "../auth";
import { fmtIso, fmtNum } from "../format";
import { useApi } from "../hooks";
import { Empty, ErrorBox, Field, Modal, ModeBadge, StatusBadge, useAction } from "../components/ui";
import type { Account, Diagnostics, Runtime, SystemStatus } from "../types";

interface FormState {
  name: string;
  connection_type: "local" | "bridge";
  login: string;
  server: string;
  password: string;
  clear_password: boolean;
  terminal_path: string;
  bridge_url: string;
  bridge_token: string;
  auto_connect: boolean;
}

const EMPTY: FormState = {
  name: "",
  connection_type: "local",
  login: "",
  server: "",
  password: "",
  clear_password: false,
  terminal_path: "",
  bridge_url: "",
  bridge_token: "",
  auto_connect: true,
};

function AccountForm({ initial, onDone, sys }: { initial: Account | null; onDone: () => void; sys: SystemStatus | null }) {
  const [f, setF] = useState<FormState>(
    initial
      ? {
          ...EMPTY,
          name: initial.name,
          connection_type: initial.connection_type,
          login: String(initial.login),
          server: initial.server,
          terminal_path: initial.terminal_path ?? "",
          bridge_url: initial.bridge_url ?? "",
          auto_connect: initial.auto_connect,
        }
      : { ...EMPTY, connection_type: sys && !sys.mt5_package_installed ? "bridge" : "local" },
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof FormState, v: string | boolean) => setF((x) => ({ ...x, [k]: v }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = {
      name: f.name,
      connection_type: f.connection_type,
      login: Number(f.login),
      server: f.server,
      terminal_path: f.terminal_path || null,
      bridge_url: f.connection_type === "bridge" ? f.bridge_url || null : null,
      auto_connect: f.auto_connect,
    };
    if (f.password) body.password = f.password;
    if (f.bridge_token) body.bridge_token = f.bridge_token;
    if (initial && f.clear_password) body.clear_password = true;
    try {
      if (initial) await api(`/api/accounts/${initial.id}`, { method: "PATCH", body });
      else await api("/api/accounts", { method: "POST", body });
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="form">
      <ErrorBox error={error} />
      <Field label="Название">
        <input value={f.name} onChange={(e) => set("name", e.target.value)} required placeholder="Например: Demo MetaQuotes" />
      </Field>
      <Field label="Тип подключения">
        <select value={f.connection_type} onChange={(e) => set("connection_type", e.target.value)}>
          <option value="local" disabled={!!sys && !sys.mt5_package_installed}>
            Напрямую: библиотека MetaTrader5 (рекомендуется)
            {sys && !sys.mt5_package_installed ? " — пакет не установлен на этом сервере" : ""}
          </option>
          <option value="bridge">Через MT5-мост (терминал на другой Windows-машине / VPS)</option>
        </select>
      </Field>
      <div className="grid-2">
        <Field label="Номер счёта (логин)">
          <input type="number" value={f.login} onChange={(e) => set("login", e.target.value)} required min={1} />
        </Field>
        <Field label="Торговый сервер">
          <input value={f.server} onChange={(e) => set("server", e.target.value)} required placeholder="MetaQuotes-Demo" />
        </Field>
      </div>
      <Field
        label="Пароль счёта"
        hint={
          initial?.has_password
            ? "Пароль сохранён (зашифрован). Оставьте пустым, чтобы не менять."
            : "Можно не указывать, если терминал уже авторизован под этим счётом."
        }
      >
        <input type="password" value={f.password} onChange={(e) => set("password", e.target.value)} autoComplete="new-password" />
      </Field>
      {initial?.has_password && (
        <label className="check">
          <input type="checkbox" checked={f.clear_password} onChange={(e) => set("clear_password", e.target.checked)} /> Удалить сохранённый
          пароль
        </label>
      )}
      <Field
        label="Путь к terminal64.exe (необязательно)"
        hint="Нужен, если установлено несколько терминалов MT5. Для одновременной работы нескольких счетов у каждого должен быть свой терминал (своя папка установки)."
      >
        <input
          value={f.terminal_path}
          onChange={(e) => set("terminal_path", e.target.value)}
          placeholder="C:\Program Files\MetaTrader 5\terminal64.exe"
        />
      </Field>
      {f.connection_type === "bridge" && (
        <div className="grid-2">
          <Field label="URL моста">
            <input value={f.bridge_url} onChange={(e) => set("bridge_url", e.target.value)} placeholder="https://10.0.0.5:8765" required />
          </Field>
          <Field label="Токен моста" hint={initial?.has_bridge_token ? "Токен сохранён. Пусто — не менять." : "Значение ATO_BRIDGE_TOKEN"}>
            <input
              type="password"
              value={f.bridge_token}
              onChange={(e) => set("bridge_token", e.target.value)}
              required={!initial?.has_bridge_token}
              autoComplete="off"
            />
          </Field>
        </div>
      )}
      <label className="check">
        <input type="checkbox" checked={f.auto_connect} onChange={(e) => set("auto_connect", e.target.checked)} /> Подключать автоматически
        при старте сервера и переподключать при обрыве
      </label>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={busy}>
          {initial ? "Сохранить" : "Добавить счёт"}
        </button>
      </div>
    </form>
  );
}

function fmtOffset(s: number): string {
  const h = s / 3600;
  return `${h >= 0 ? "+" : ""}${Number.isInteger(h) ? h : h.toFixed(1)}`;
}

function DiagnosticsView({ account }: { account: Account }) {
  const d = useApi<Diagnostics>(`/api/accounts/${account.id}/diagnostics`);
  return (
    <div>
      <ErrorBox error={d.error} />
      {d.loading && !d.data && <p className="muted">Опрос терминала…</p>}
      {d.data && (
        <>
          <div className={`diag-summary ${d.data.ready ? "ok" : "bad"}`}>
            {d.data.ready
              ? "Терминал готов к торговле через Python API"
              : "Торговля через Python API сейчас невозможна — исправьте отмеченные пункты"}
            {d.data.version && (
              <div className="muted small">
                MetaTrader 5 build {d.data.version.build} ({d.data.version.date})
              </div>
            )}
          </div>
          <ul className="diag-list">
            {d.data.checks.map((c) => (
              <li key={c.key} className={`diag-${c.level}`}>
                <span className="diag-icon">{c.ok ? "✓" : c.level === "error" ? "✕" : "!"}</span>
                <div>
                  <b>{c.title}</b>
                  <div className="muted small">{c.detail}</div>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      <div className="form-actions">
        <button className="btn" onClick={() => d.reload()} disabled={d.loading}>
          Проверить снова
        </button>
      </div>
    </div>
  );
}

export default function AccountsPage() {
  const { accounts, reload, error } = useAccounts();
  const { can } = useAuth();
  const sys = useApi<SystemStatus>("/api/system/status");
  const [edit, setEdit] = useState<Account | null | "new">(null);
  const [diag, setDiag] = useState<Account | null>(null);
  const act = useAction();

  async function connect(a: Account) {
    await act.run(
      () => api<Runtime>(`/api/accounts/${a.id}/connect`, { method: "POST" }),
      (r) => `Подключено: ${r.account?.name ?? ""} #${r.account?.login}`,
    );
    reload();
  }
  async function disconnect(a: Account) {
    await act.run(() => api(`/api/accounts/${a.id}/disconnect`, { method: "POST" }), "Счёт отключён");
    reload();
  }
  async function remove(a: Account) {
    if (!confirm(`Удалить счёт «${a.name}»? Сохранённые учётные данные будут стёрты.`)) return;
    await act.run(() => api(`/api/accounts/${a.id}`, { method: "DELETE" }), "Счёт удалён");
    reload();
  }

  return (
    <div className="page">
      <div className="page-head">
        <h1>Счета MetaTrader 5</h1>
        {can("trader") && (
          <button className="btn btn-primary" onClick={() => setEdit("new")}>
            + Добавить счёт
          </button>
        )}
      </div>
      <ErrorBox error={error} />
      {accounts.length === 0 && <Empty>Счета ещё не добавлены.</Empty>}
      {accounts.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Название</th>
              <th>Логин / сервер</th>
              <th>Подключение</th>
              <th>Тип счёта</th>
              <th>Статус</th>
              <th>Баланс</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {accounts.map((a) => (
              <tr key={a.id}>
                <td>
                  <b>{a.name}</b>
                  <div className="muted small">{a.company ?? ""}</div>
                </td>
                <td>
                  #{a.login}
                  <div className="muted small">{a.server}</div>
                </td>
                <td>
                  {a.connection_type === "bridge" ? `Мост ${a.bridge_url ?? ""}` : "MetaTrader5 (напрямую)"}
                  {a.runtime.version && <div className="muted small">MT5 build {a.runtime.version.build}</div>}
                  {a.runtime.server_offset_s != null && (
                    <div className="muted small">время сервера UTC{fmtOffset(a.runtime.server_offset_s)}</div>
                  )}
                  {a.auto_connect && <div className="muted small">автоподключение</div>}
                </td>
                <td>
                  <ModeBadge mode={a.runtime.account?.trade_mode_name ?? a.trade_mode_name} />
                </td>
                <td style={{ maxWidth: 320 }}>
                  <StatusBadge status={a.runtime.status} />
                  {a.runtime.error && <div className="error-text small">{a.runtime.error}</div>}
                  {a.last_connected_at && <div className="muted small">последнее: {fmtIso(a.last_connected_at)}</div>}
                </td>
                <td>{a.runtime.account ? `${fmtNum(a.runtime.account.balance)} ${a.runtime.account.currency}` : "—"}</td>
                <td className="actions">
                  {a.runtime.status === "connected" && (
                    <button className="btn btn-sm btn-ghost" onClick={() => setDiag(a)}>
                      Диагностика
                    </button>
                  )}
                  {can("trader") && (
                    <>
                      {a.runtime.status === "connected" || a.runtime.status === "connecting" ? (
                        <button className="btn btn-sm" disabled={act.busy} onClick={() => disconnect(a)}>
                          Отключить
                        </button>
                      ) : (
                        <button className="btn btn-sm btn-primary" disabled={act.busy} onClick={() => connect(a)}>
                          Подключить
                        </button>
                      )}
                      <button className="btn btn-sm btn-ghost" onClick={() => setEdit(a)}>
                        Изменить
                      </button>
                    </>
                  )}
                  {can("admin") && (
                    <button className="btn btn-sm btn-ghost danger" onClick={() => remove(a)}>
                      Удалить
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="card info-card">
        <h3>Подключение к MetaTrader 5 через библиотеку MetaTrader5</h3>
        <p className="muted">
          Приложение работает с терминалом напрямую через официальный Python-пакет MetaQuotes <code>MetaTrader5</code>. Пакет выпускается
          только для Windows x64 и подключается к терминалу, запущенному на той же машине.
          {sys.data && (
            <>
              {" "}
              Этот сервер: <code>{sys.data.os}</code>, пакет MetaTrader5{" "}
              {sys.data.mt5_package_installed ? "установлен" : <b>не установлен — прямое подключение здесь недоступно</b>}.
            </>
          )}
        </p>
        <ol className="steps">
          <li>Установите MetaTrader 5 (с сайта брокера или metatrader5.com), откройте демо-счёт и войдите в него.</li>
          <li>
            Включите кнопку <b>«Алго-трейдинг»</b> на панели терминала; в <i>Сервис → Настройки → Советники</i> не должна стоять галочка
            запрета торговли через внешний Python API.
          </li>
          <li>
            Запустите приложение на этой же Windows-машине: <code>start.bat</code> в корне проекта (сам установит зависимости, включая
            MetaTrader5).
          </li>
          <li>
            Добавьте счёт с типом «Напрямую: библиотека MetaTrader5», нажмите «Подключить», затем «Диагностика» — проверка покажет, что ещё
            нужно включить.
          </li>
        </ol>
        <p className="muted small">
          Проверка без веб-интерфейса: <code>scripts\check_mt5.bat --trade</code> (тестовая сделка минимальным лотом выполняется только на
          DEMO). Если сервер приложения работает не на Windows, используйте тип «MT5-мост»: на Windows-машине с терминалом запустите{" "}
          <code>scripts\start_bridge.ps1</code>.
        </p>
      </div>

      {diag && (
        <Modal title={`Диагностика: ${diag.name} #${diag.login}`} onClose={() => setDiag(null)}>
          <DiagnosticsView account={diag} />
        </Modal>
      )}

      {edit && (
        <Modal title={edit === "new" ? "Новый счёт MT5" : `Счёт «${edit.name}»`} onClose={() => setEdit(null)}>
          <AccountForm
            initial={edit === "new" ? null : edit}
            sys={sys.data}
            onDone={() => {
              setEdit(null);
              reload();
            }}
          />
        </Modal>
      )}
    </div>
  );
}
