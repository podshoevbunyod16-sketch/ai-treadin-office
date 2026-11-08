import { Link } from "react-router-dom";
import { useAccounts } from "../accounts";
import { fmtNum, pnlClass, signalLabel } from "../format";
import { useApi, useTopic } from "../hooks";
import { Empty, ErrorBox, ModeBadge, Stat, StatusBadge } from "../components/ui";
import type { Bot, BotMetrics, SystemStatus } from "../types";

export default function Dashboard() {
  const { accounts, loaded, error } = useAccounts();
  const bots = useApi<Bot[]>("/api/bots");
  const sys = useApi<SystemStatus>("/api/system/status");

  useTopic("bots", (m) => {
    if (m.type !== "metrics") return;
    const mt = m.data as BotMetrics;
    bots.setData((xs) =>
      xs ? xs.map((b) => (b.id === mt.bot_id ? { ...b, metrics: mt, status: (mt.status as Bot["status"]) ?? b.status } : b)) : xs,
    );
  });

  const connected = accounts.filter((a) => a.runtime.status === "connected");
  const totalEquity = connected.reduce((s, a) => s + (a.runtime.account?.equity ?? 0), 0);
  const totalProfit = connected.reduce((s, a) => s + (a.runtime.account?.profit ?? 0), 0);
  const running = (bots.data ?? []).filter((b) => b.status === "running").length;
  const currencies = [...new Set(connected.map((a) => a.runtime.account?.currency))];

  return (
    <div className="page">
      <h1>Обзор</h1>
      {sys.data && !sys.data.mt5_package_installed && (
        <div className="alert alert-warn">
          <b>MetaTrader 5 на этом сервере недоступен.</b> {sys.data.local_mode_note} Сервер работает на{" "}
          <code>{sys.data.os}</code>. Подключите счёт через MT5-мост — инструкция на странице{" "}
          <Link to="/accounts">«Счета MT5»</Link>.
        </div>
      )}
      <ErrorBox error={error || bots.error} />

      <div className="stats-row">
        <Stat label="Подключено счетов" value={`${connected.length} / ${accounts.length}`} />
        <Stat label="Суммарное эквити" value={currencies.length === 1 ? `${fmtNum(totalEquity)} ${currencies[0]}` : connected.length ? "разные валюты" : "—"} />
        <Stat label="Плавающий P/L" value={currencies.length === 1 ? fmtNum(totalProfit) : "—"} cls={pnlClass(totalProfit)} />
        <Stat label="Боты в работе" value={`${running} / ${bots.data?.length ?? 0}`} />
      </div>

      <h2>Счета</h2>
      {loaded && accounts.length === 0 && (
        <Empty>
          Нет брокерских счетов. <Link to="/accounts">Добавьте MT5-счёт</Link>, чтобы получать котировки и торговать.
        </Empty>
      )}
      <div className="cards">
        {accounts.map((a) => {
          const info = a.runtime.account;
          return (
            <div key={a.id} className="card">
              <div className="card-head">
                <div>
                  <div className="card-title">{a.name}</div>
                  <div className="muted small">
                    #{a.login} · {a.server} · {a.connection_type === "bridge" ? "мост" : "локально"}
                  </div>
                </div>
                <div className="row gap-s">
                  <ModeBadge mode={info?.trade_mode_name ?? a.trade_mode_name} />
                  <StatusBadge status={a.runtime.status} title={a.runtime.error ?? undefined} />
                </div>
              </div>
              {a.runtime.status === "connected" && info ? (
                <div className="kv-grid">
                  <span>Баланс</span>
                  <b>
                    {fmtNum(info.balance)} {info.currency}
                  </b>
                  <span>Эквити</span>
                  <b>{fmtNum(info.equity)}</b>
                  <span>Прибыль</span>
                  <b className={pnlClass(info.profit)}>{fmtNum(info.profit)}</b>
                  <span>Маржа / свободно</span>
                  <b>
                    {fmtNum(info.margin)} / {fmtNum(info.margin_free)}
                  </b>
                  <span>Уровень маржи</span>
                  <b>{info.margin_level ? `${fmtNum(info.margin_level)}%` : "—"}</b>
                  <span>Позиции / ордера</span>
                  <b>
                    {a.runtime.positions_count ?? 0} / {a.runtime.orders_count ?? 0}
                  </b>
                  <span>Плечо</span>
                  <b>1:{info.leverage}</b>
                  <span>Автоторговля</span>
                  <b className={a.runtime.terminal?.trade_allowed ? "pos" : "neg"}>
                    {a.runtime.terminal?.trade_allowed ? "разрешена" : "запрещена в терминале"}
                  </b>
                </div>
              ) : (
                <div className="muted small">{a.runtime.error ?? "Счёт не подключён"}</div>
              )}
            </div>
          );
        })}
      </div>

      <h2>Боты</h2>
      {bots.data && bots.data.length === 0 && (
        <Empty>
          Ботов пока нет. <Link to="/bots">Создать бота</Link>
        </Empty>
      )}
      {bots.data && bots.data.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Бот</th>
              <th>Стратегия</th>
              <th>Инструмент</th>
              <th>Статус</th>
              <th>Последний сигнал</th>
              <th>Ордеров</th>
              <th>Ошибок</th>
            </tr>
          </thead>
          <tbody>
            {bots.data.map((b) => (
              <tr key={b.id}>
                <td>
                  <Link to={`/bots/${b.id}`}>{b.name}</Link>
                </td>
                <td>{b.strategy_title}</td>
                <td>
                  {b.symbol} {b.timeframe}
                </td>
                <td>
                  <StatusBadge status={b.status} title={b.last_error ?? undefined} />
                  {b.metrics?.waiting_reason && <div className="muted small">{b.metrics.waiting_reason}</div>}
                </td>
                <td>{signalLabel((b.metrics?.state ?? b.state)?.last_signal)}</td>
                <td>{b.metrics?.orders_sent ?? "—"}</td>
                <td>{b.metrics?.errors ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
