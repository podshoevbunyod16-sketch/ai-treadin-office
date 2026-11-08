import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAccounts } from "../accounts";
import { useAuth } from "../auth";
import { BotForm } from "../components/BotForm";
import { Badge, Empty, ErrorBox, Modal, StatusBadge, useAction } from "../components/ui";
import { fmtDuration, signalLabel } from "../format";
import { useApi, useTopic } from "../hooks";
import type { Bot, BotMetrics } from "../types";

export default function BotsPage() {
  const { data, setData, error, reload } = useApi<Bot[]>("/api/bots");
  const { accounts } = useAccounts();
  const { can } = useAuth();
  const [creating, setCreating] = useState(false);
  const nav = useNavigate();
  const act = useAction();

  useTopic("bots", (m) => {
    if (m.type !== "metrics") return;
    const mt = m.data as BotMetrics;
    setData((xs) => (xs ? xs.map((b) => (b.id === mt.bot_id ? { ...b, metrics: mt, status: (mt.status as Bot["status"]) ?? b.status } : b)) : xs));
  });

  async function toggle(b: Bot) {
    const running = b.status === "running" || b.status === "starting";
    await act.run(() => api(`/api/bots/${b.id}/${running ? "stop" : "start"}`, { method: "POST" }), running ? "Бот остановлен" : "Бот запущен");
    reload();
  }

  return (
    <div className="page">
      <div className="page-head">
        <h1>Торговые боты</h1>
        {can("trader") && (
          <button className="btn btn-primary" disabled={!accounts.length} onClick={() => setCreating(true)} title={accounts.length ? "" : "Сначала добавьте счёт"}>
            + Новый бот
          </button>
        )}
      </div>
      <p className="muted">
        Каждый бот работает в собственной изолированной среде исполнения: отдельная задача, собственное состояние, журнал, риск-лимиты и уникальный
        magic-номер, по которому его ордера, позиции и сделки отделяются в MT5 от других ботов и ручной торговли.
      </p>
      <ErrorBox error={error} />
      {data && data.length === 0 && <Empty>Ботов пока нет.</Empty>}
      {data && data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Бот</th>
              <th>Счёт</th>
              <th>Стратегия</th>
              <th>Инструмент</th>
              <th>Режим</th>
              <th>Статус</th>
              <th>Сигнал</th>
              <th>Аптайм / циклы</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.map((b) => {
              const acc = accounts.find((a) => a.id === b.account_id);
              const st = b.metrics?.state ?? b.state;
              return (
                <tr key={b.id}>
                  <td>
                    <Link to={`/bots/${b.id}`}>
                      <b>{b.name}</b>
                    </Link>
                    <div className="muted small">magic {b.magic}</div>
                  </td>
                  <td>{acc ? `${acc.name} #${acc.login}` : b.account_id}</td>
                  <td>{b.strategy_title}</td>
                  <td>
                    {b.symbol} · {b.timeframe}
                  </td>
                  <td>{b.trade_mode === "live" ? <Badge kind="ok">Торговля</Badge> : <Badge kind="info">Сигналы</Badge>}</td>
                  <td style={{ maxWidth: 260 }}>
                    <StatusBadge status={b.status} />
                    {b.metrics?.waiting_reason && <div className="muted small">{b.metrics.waiting_reason}</div>}
                    {b.status === "error" && b.last_error && <div className="error-text small">{b.last_error}</div>}
                  </td>
                  <td>{signalLabel(st?.last_signal)}</td>
                  <td>{b.metrics ? `${fmtDuration(b.metrics.uptime_s)} / ${b.metrics.cycles}` : "—"}</td>
                  <td className="actions">
                    {can("trader") && (
                      <button className={`btn btn-sm ${b.status === "running" ? "" : "btn-primary"}`} disabled={act.busy} onClick={() => toggle(b)}>
                        {b.status === "running" || b.status === "starting" ? "Стоп" : "Старт"}
                      </button>
                    )}
                    <Link className="btn btn-sm btn-ghost" to={`/bots/${b.id}`}>
                      Открыть
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {creating && (
        <Modal title="Новый торговый бот" onClose={() => setCreating(false)} wide>
          <BotForm
            bot={null}
            onSaved={(b) => {
              setCreating(false);
              nav(`/bots/${b.id}`);
            }}
          />
        </Modal>
      )}
    </div>
  );
}
