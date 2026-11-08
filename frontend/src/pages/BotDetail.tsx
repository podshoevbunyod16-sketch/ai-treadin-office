import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useAccounts } from "../accounts";
import { useAuth } from "../auth";
import { BotForm } from "../components/BotForm";
import { LineChart } from "../components/Charts";
import { Badge, Empty, ErrorBox, Stat, StatusBadge, notify, useAction } from "../components/ui";
import { fmtDuration, fmtIso, fmtNum, fmtServerTime, pnlClass, signalLabel } from "../format";
import { useApi, useInterval, useTopic } from "../hooks";
import type { Bot, BotLog, BotMetrics, BotOrderRow, Performance } from "../types";
import { DealsTable } from "./Terminal";

type Tab = "monitor" | "settings" | "orders" | "performance";

export default function BotDetail() {
  const id = Number(useParams().id);
  const { data: bot, setData: setBot, error, reload } = useApi<Bot>(`/api/bots/${id}`);
  const { accounts } = useAccounts();
  const { can } = useAuth();
  const [tab, setTab] = useState<Tab>("monitor");
  const act = useAction();
  const nav = useNavigate();

  useTopic(`bot:${id}`, (m) => {
    if (m.type === "metrics") {
      const mt = m.data as BotMetrics;
      setBot((b) => (b ? { ...b, metrics: mt, state: mt.state ?? b.state, status: (mt.status as Bot["status"]) ?? b.status } : b));
      if (mt.status && mt.status !== "running") reload();
    }
  });

  if (error) return <ErrorBox error={error} />;
  if (!bot) return <div className="muted">Загрузка…</div>;
  const running = bot.status === "running" || bot.status === "starting";
  const acc = accounts.find((a) => a.id === bot.account_id);
  const m = bot.metrics;
  const st = (m?.state ?? bot.state) as Record<string, any>;

  async function toggle() {
    await act.run(() => api<Bot>(`/api/bots/${id}/${running ? "stop" : "start"}`, { method: "POST" }), running ? "Бот остановлен" : "Бот запущен");
    reload();
  }
  async function closeAll() {
    if (!confirm("Закрыть все позиции этого бота в MT5?")) return;
    await act.run(() => api<{ closed: number }>(`/api/bots/${id}/close-positions`, { method: "POST" }), (r) => `Закрыто позиций: ${r.closed}`);
  }
  async function resetState() {
    if (!confirm("Сбросить сохранённое состояние стратегии?")) return;
    await act.run(() => api(`/api/bots/${id}/reset-state`, { method: "POST" }), "Состояние сброшено");
    reload();
  }
  async function remove() {
    if (!confirm(`Удалить бота «${bot!.name}» вместе с журналом? Позиции в MT5 не будут затронуты.`)) return;
    const r = await act.run(() => api(`/api/bots/${id}`, { method: "DELETE" }), "Бот удалён");
    if (r) nav("/bots");
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="muted small">
            <Link to="/bots">← Боты</Link>
          </div>
          <h1>
            {bot.name} <StatusBadge status={bot.status} /> {bot.trade_mode === "live" ? <Badge kind="ok">Торговля</Badge> : <Badge kind="info">Только сигналы</Badge>}
          </h1>
          <div className="muted">
            {bot.strategy_title} · {bot.symbol} {bot.timeframe} · счёт {acc ? `${acc.name} #${acc.login}` : bot.account_id} · magic {bot.magic}
          </div>
        </div>
        {can("trader") && (
          <div className="row gap-s">
            <button className={`btn ${running ? "" : "btn-primary"}`} disabled={act.busy} onClick={toggle}>
              {running ? "■ Остановить" : "▶ Запустить"}
            </button>
            <button className="btn btn-ghost" disabled={act.busy} onClick={closeAll}>
              Закрыть позиции бота
            </button>
            <button className="btn btn-ghost" disabled={act.busy || running} onClick={resetState}>
              Сбросить состояние
            </button>
            <button className="btn btn-ghost danger" disabled={act.busy || running} onClick={remove}>
              Удалить
            </button>
          </div>
        )}
      </div>
      {bot.status === "error" && bot.last_error && <div className="alert alert-err">Бот остановлен из-за ошибки: {bot.last_error}</div>}
      {running && m?.waiting_reason && <div className="alert alert-warn">{m.waiting_reason}</div>}

      <div className="tabs">
        {(
          [
            ["monitor", "Мониторинг"],
            ["settings", "Настройки"],
            ["orders", "Ордера бота"],
            ["performance", "Позиции и результаты"],
          ] as [Tab, string][]
        ).map(([k, l]) => (
          <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>
            {l}
          </button>
        ))}
      </div>

      {tab === "monitor" && (
        <>
          <div className="stats-row">
            <Stat label="Аптайм" value={m?.running ? fmtDuration(m.uptime_s) : "—"} />
            <Stat label="Циклов" value={m?.cycles ?? "—"} />
            <Stat label="Ордеров отправлено" value={m?.orders_sent ?? "—"} />
            <Stat label="Ошибок (подряд)" value={m ? `${m.errors} (${m.consecutive_errors})` : "—"} cls={m?.errors ? "neg" : ""} />
            <Stat label="Последний цикл" value={m?.last_cycle ? new Date(m.last_cycle * 1000).toLocaleTimeString("ru-RU") : "—"} />
            <Stat label="Heartbeat" value={fmtIso(bot.last_heartbeat)} />
          </div>
          <div className="grid-2 gap">
            <div className="card">
              <h3>Состояние стратегии</h3>
              <div className="kv-grid">
                <span>Последний сигнал</span>
                <b>{signalLabel(st?.last_signal)}</b>
                <span>Причина</span>
                <b>{st?.last_reason ?? "—"}</b>
                <span>Закрытый бар</span>
                <b>{st?.last_bar_time ? fmtServerTime(st.last_bar_time) : "—"}</b>
                <span>Экспозиция</span>
                <b>{signalLabel(st?.exposure)}</b>
                {st?.last_values &&
                  Object.entries(st.last_values as Record<string, unknown>).map(([k, v]) => (
                    <FragmentKV key={k} k={k} v={String(v)} />
                  ))}
              </div>
            </div>
            <LiveLogs botId={id} />
          </div>
        </>
      )}
      {tab === "settings" && (
        <div className="card">
          <BotForm
            bot={bot}
            disabled={running || !can("trader")}
            onSaved={(b) => {
              setBot(b);
              notify("ok", "Настройки сохранены");
            }}
          />
        </div>
      )}
      {tab === "orders" && <BotOrders botId={id} />}
      {tab === "performance" && <BotPerformance botId={id} />}
    </div>
  );
}

function FragmentKV({ k, v }: { k: string; v: string }) {
  return (
    <>
      <span>{k}</span>
      <b>{v}</b>
    </>
  );
}

const LEVEL_KIND: Record<string, string> = { error: "err", warning: "warn", trade: "ok", signal: "info", info: "muted" };

function LiveLogs({ botId }: { botId: number }) {
  const [logs, setLogs] = useState<BotLog[]>([]);
  const [level, setLevel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { can } = useAuth();

  useEffect(() => {
    api<BotLog[]>(`/api/bots/${botId}/logs`, { query: { limit: 300, level } })
      .then((l) => {
        setLogs(l);
        setError(null);
      })
      .catch((e) => setError(e.message));
  }, [botId, level]);

  useTopic(`bot:${botId}`, (m) => {
    if (m.type !== "log") return;
    const l = m.data as BotLog;
    if (level && l.level !== level) return;
    setLogs((xs) => [l, ...xs].slice(0, 1000));
  });

  async function clear() {
    if (!confirm("Очистить журнал бота?")) return;
    await api(`/api/bots/${botId}/logs`, { method: "DELETE" });
    setLogs([]);
  }

  return (
    <div className="card">
      <div className="row between">
        <h3>Журнал (в реальном времени)</h3>
        <div className="row gap-s">
          <select value={level} onChange={(e) => setLevel(e.target.value)}>
            <option value="">Все</option>
            <option value="signal">Сигналы</option>
            <option value="trade">Сделки</option>
            <option value="warning">Предупреждения</option>
            <option value="error">Ошибки</option>
            <option value="info">Инфо</option>
          </select>
          {can("trader") && (
            <button className="btn btn-sm btn-ghost" onClick={clear}>
              Очистить
            </button>
          )}
        </div>
      </div>
      <ErrorBox error={error} />
      <div className="logs">
        {logs.length === 0 && <div className="muted small">Записей нет</div>}
        {logs.map((l) => (
          <div key={l.id} className="log-line">
            <span className="muted">{new Date(l.ts).toLocaleString("ru-RU")}</span> <Badge kind={LEVEL_KIND[l.level] ?? "muted"}>{l.level}</Badge> {l.message}
          </div>
        ))}
      </div>
    </div>
  );
}

function BotOrders({ botId }: { botId: number }) {
  const { data, error, reload } = useApi<BotOrderRow[]>(`/api/bots/${botId}/orders`);
  useInterval(reload, 10000);
  return (
    <div className="card">
      <h3>Торговые запросы бота к MT5 и ответы брокера</h3>
      <ErrorBox error={error} />
      {data && data.length === 0 && <Empty>Бот ещё не отправлял ордеров</Empty>}
      {data && data.length > 0 && (
        <table className="table compact">
          <thead>
            <tr>
              <th>Время</th>
              <th>Действие</th>
              <th>Символ</th>
              <th>Сторона</th>
              <th>Объём</th>
              <th>Цена</th>
              <th>Результат</th>
              <th>Ордер / сделка</th>
            </tr>
          </thead>
          <tbody>
            {data.map((o) => (
              <tr key={o.id}>
                <td>{fmtIso(o.ts)}</td>
                <td>{o.action}</td>
                <td>{o.symbol}</td>
                <td>{o.side}</td>
                <td>{o.volume}</td>
                <td>{o.price || "—"}</td>
                <td className={o.ok ? "pos" : "neg"}>
                  {o.comment} ({o.retcode ?? "—"})
                </td>
                <td>
                  {o.order || "—"} / {o.deal || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function BotPerformance({ botId }: { botId: number }) {
  const [days, setDays] = useState(30);
  const { data, error, reload, loading } = useApi<Performance>(`/api/bots/${botId}/performance?days=${days}`, [days]);
  useInterval(reload, 15000);
  return (
    <>
      <div className="row gap-s filter-row">
        <span className="muted">Период:</span>
        {[1, 7, 30, 90, 365].map((d) => (
          <button key={d} className={`btn btn-sm ${d === days ? "btn-primary" : "btn-ghost"}`} onClick={() => setDays(d)}>
            {d} дн.
          </button>
        ))}
        {loading && <span className="muted small">обновление…</span>}
      </div>
      <ErrorBox error={error} />
      {data && (
        <>
          <p className="muted small">Данные получены из истории сделок MT5 по magic-номеру бота.</p>
          <div className="stats-row">
            <Stat label="Закрытых сделок" value={data.trades} />
            <Stat label="Win rate" value={data.win_rate === null ? "—" : `${fmtNum(data.win_rate * 100, 1)}%`} />
            <Stat label="Реализованный P/L" value={fmtNum(data.realized_pnl)} cls={pnlClass(data.realized_pnl)} />
            <Stat label="Плавающий P/L" value={fmtNum(data.floating_pnl)} cls={pnlClass(data.floating_pnl)} />
            <Stat label="Profit factor" value={data.profit_factor === null ? "—" : fmtNum(data.profit_factor)} />
            <Stat label="Макс. просадка" value={fmtNum(data.max_drawdown)} />
          </div>
          {data.equity_curve.length > 1 && (
            <div className="card">
              <h3>Кривая доходности</h3>
              <LineChart points={data.equity_curve.map((p) => ({ time: p.time, value: p.pnl }))} />
            </div>
          )}
          <div className="card">
            <h3>Открытые позиции бота ({data.positions.length})</h3>
            {data.positions.length === 0 ? (
              <Empty>Нет</Empty>
            ) : (
              <table className="table compact">
                <thead>
                  <tr>
                    <th>Тикет</th>
                    <th>Время</th>
                    <th>Тип</th>
                    <th>Объём</th>
                    <th>Цена</th>
                    <th>S/L</th>
                    <th>T/P</th>
                    <th>Прибыль</th>
                  </tr>
                </thead>
                <tbody>
                  {data.positions.map((p) => (
                    <tr key={p.ticket}>
                      <td>{p.ticket}</td>
                      <td>{fmtServerTime(p.time)}</td>
                      <td className={p.side === "buy" ? "pos" : "neg"}>{p.side.toUpperCase()}</td>
                      <td>{p.volume}</td>
                      <td>{p.price_open}</td>
                      <td>{p.sl || "—"}</td>
                      <td>{p.tp || "—"}</td>
                      <td className={pnlClass(p.profit)}>{fmtNum(p.profit)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="card">
            <h3>Сделки ({data.deals.length})</h3>
            {data.deals.length === 0 ? <Empty>Сделок за период нет</Empty> : <DealsTable deals={data.deals} />}
          </div>
        </>
      )}
    </>
  );
}
