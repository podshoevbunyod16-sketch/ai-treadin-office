import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAccounts } from "../accounts";
import { useAuth } from "../auth";
import { CandleChart, LivePrice } from "../components/Charts";
import { Empty, ErrorBox, Field, Modal, ModeBadge, StatusBadge, notify, useAction } from "../components/ui";
import { fmtNum, fmtPrice, fmtServerTime, ORDER_TYPE_LABEL, pnlClass } from "../format";
import { useInterval, useTopic } from "../hooks";
import type { AccountInfo, Deal, Order, Position, Rate, SymbolBrief, Tick, TradeResult } from "../types";

const TF_SEC: Record<string, number> = { M1: 60, M5: 300, M15: 900, M30: 1800, H1: 3600, H4: 14400, D1: 86400, W1: 604800 };

function resultText(r: TradeResult): string {
  return `${r.retcode_text} (retcode ${r.retcode ?? "—"}${r.order ? `, ордер #${r.order}` : ""}${r.deal ? `, сделка #${r.deal}` : ""}${
    r.price ? `, цена ${r.price}` : ""
  })`;
}

export default function TerminalPage() {
  const { accounts } = useAccounts();
  const { can } = useAuth();
  const [accountId, setAccountId] = useState<number | null>(null);
  const account = accounts.find((a) => a.id === accountId) ?? null;
  const connected = account?.runtime.status === "connected";

  const [info, setInfo] = useState<AccountInfo | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [ticks, setTicks] = useState<Record<string, Tick | null>>({});
  const [watch, setWatch] = useState<string[]>([]);
  const [symbols, setSymbols] = useState<SymbolBrief[]>([]);
  const [symbol, setSymbol] = useState<string>("");
  const [tf, setTf] = useState("M15");
  const [rates, setRates] = useState<Rate[]>([]);
  const [ratesErr, setRatesErr] = useState<string | null>(null);
  const [tab, setTab] = useState<"positions" | "orders" | "history">("positions");
  const [newSym, setNewSym] = useState("");

  useEffect(() => {
    if (accountId === null && accounts.length) {
      const c = accounts.find((a) => a.runtime.status === "connected") ?? accounts[0];
      setAccountId(c.id);
    }
  }, [accounts, accountId]);

  // reset & load per account
  useEffect(() => {
    setInfo(null);
    setPositions([]);
    setOrders([]);
    setTicks({});
    setSymbols([]);
    if (!accountId) return;
    api<{ symbols: string[] }>(`/api/accounts/${accountId}/watchlist`).then((w) => {
      setWatch(w.symbols);
      setSymbol((s) => (s && w.symbols.includes(s) ? s : w.symbols[0] ?? ""));
    });
  }, [accountId]);

  useEffect(() => {
    if (!accountId || !connected) return;
    api<SymbolBrief[]>(`/api/accounts/${accountId}/symbols`)
      .then(setSymbols)
      .catch((e) => notify("err", e.message));
  }, [accountId, connected]);

  useTopic(accountId ? `account:${accountId}` : null, (m) => {
    if (m.type === "snapshot") {
      setInfo(m.data.account);
      setPositions(m.data.positions);
      setOrders(m.data.orders);
    } else if (m.type === "ticks") {
      setTicks((t) => ({ ...t, ...m.data }));
    }
  });

  const loadRates = async () => {
    if (!accountId || !connected || !symbol) return;
    try {
      setRates(await api<Rate[]>(`/api/accounts/${accountId}/rates`, { query: { symbol, timeframe: tf, count: 500 } }));
      setRatesErr(null);
    } catch (e) {
      setRatesErr((e as Error).message);
      setRates([]);
    }
  };
  useEffect(() => {
    loadRates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, connected, symbol, tf]);
  useInterval(loadRates, connected && symbol ? 60000 : null);

  async function saveWatch(list: string[]) {
    if (!accountId) return;
    try {
      const r = await api<{ symbols: string[] }>(`/api/accounts/${accountId}/watchlist`, { method: "PUT", body: { symbols: list } });
      setWatch(r.symbols);
    } catch (e) {
      notify("err", (e as Error).message);
    }
  }

  function addSymbol(e: FormEvent) {
    e.preventDefault();
    const s = newSym.trim();
    if (!s) return;
    if (symbols.length && !symbols.some((x) => x.name === s)) {
      notify("err", `Символ ${s} не найден у брокера`);
      return;
    }
    saveWatch([...watch, s]);
    setSymbol(s);
    setNewSym("");
  }

  const tick = symbol ? ticks[symbol] : null;
  const digits = tick?.digits ?? symbols.find((s) => s.name === symbol)?.digits ?? 5;
  const livePrice: LivePrice | null = useMemo(() => (tick ? { time: tick.time, price: tick.bid } : null), [tick]);

  if (!accounts.length) return <Empty>Добавьте и подключите счёт MT5 на странице «Счета MT5».</Empty>;

  return (
    <div className="page terminal">
      <div className="page-head">
        <h1>Терминал</h1>
        <div className="row gap-s">
          <select value={accountId ?? ""} onChange={(e) => setAccountId(Number(e.target.value))}>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} #{a.login} ({a.runtime.status})
              </option>
            ))}
          </select>
          {account && <StatusBadge status={account.runtime.status} />}
          <ModeBadge mode={info?.trade_mode_name ?? account?.trade_mode_name} />
        </div>
      </div>

      {account && !connected && (
        <div className="alert alert-warn">
          Счёт не подключён к MT5{account.runtime.error ? `: ${account.runtime.error}` : ""}. Подключите его на странице «Счета MT5».
        </div>
      )}

      {connected && (
        <div className="account-bar">
          <span>
            Баланс <b>{fmtNum(info?.balance)}</b> {info?.currency}
          </span>
          <span>
            Эквити <b>{fmtNum(info?.equity)}</b>
          </span>
          <span>
            Маржа <b>{fmtNum(info?.margin)}</b>
          </span>
          <span>
            Свободно <b>{fmtNum(info?.margin_free)}</b>
          </span>
          <span>
            Уровень <b>{info?.margin_level ? `${fmtNum(info.margin_level)}%` : "—"}</b>
          </span>
          <span>
            Прибыль <b className={pnlClass(info?.profit)}>{fmtNum(info?.profit)}</b>
          </span>
        </div>
      )}

      <div className="terminal-grid">
        <section className="panel watch">
          <div className="panel-head">Обзор рынка</div>
          <form className="row gap-s" onSubmit={addSymbol}>
            <input list="symbols-list" placeholder="Добавить символ" value={newSym} onChange={(e) => setNewSym(e.target.value)} disabled={!connected} />
            <datalist id="symbols-list">
              {symbols.slice(0, 3000).map((s) => (
                <option key={s.name} value={s.name}>
                  {s.description}
                </option>
              ))}
            </datalist>
            <button className="btn btn-sm" disabled={!connected}>
              +
            </button>
          </form>
          <table className="table compact">
            <thead>
              <tr>
                <th>Символ</th>
                <th>Bid</th>
                <th>Ask</th>
                <th>Спред</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {watch.map((s) => {
                const t = ticks[s];
                return (
                  <tr key={s} className={s === symbol ? "selected" : ""} onClick={() => setSymbol(s)}>
                    <td>{s}</td>
                    <td>{t ? fmtPrice(t.bid, t.digits) : "—"}</td>
                    <td>{t ? fmtPrice(t.ask, t.digits) : "—"}</td>
                    <td>{t?.spread_points ?? "—"}</td>
                    <td>
                      <button
                        className="btn-icon"
                        title="Убрать"
                        onClick={(e) => {
                          e.stopPropagation();
                          saveWatch(watch.filter((x) => x !== s));
                        }}
                      >
                        ×
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {watch.length === 0 && <div className="muted small">Добавьте символы, например EURUSD.</div>}
        </section>

        <section className="panel chart-panel">
          <div className="panel-head row between">
            <span>
              {symbol || "—"} {tick && <span className="muted">· {fmtServerTime(tick.time)} (время сервера)</span>}
            </span>
            <div className="tf-switch">
              {Object.keys(TF_SEC).map((t) => (
                <button key={t} className={t === tf ? "active" : ""} onClick={() => setTf(t)}>
                  {t}
                </button>
              ))}
            </div>
          </div>
          <ErrorBox error={ratesErr} />
          {symbol && connected ? (
            <CandleChart rates={rates} digits={digits} tfSeconds={TF_SEC[tf]} live={livePrice} />
          ) : (
            <Empty>Выберите символ из списка</Empty>
          )}
        </section>

        <section className="panel ticket">
          <div className="panel-head">Новый ордер</div>
          {can("trader") ? (
            <OrderTicket accountId={accountId} symbol={symbol} tick={tick ?? null} enabled={connected} brief={symbols.find((s) => s.name === symbol)} />
          ) : (
            <div className="muted small">Роль «viewer» — только просмотр.</div>
          )}
        </section>
      </div>

      <section className="panel">
        <div className="tabs">
          <button className={tab === "positions" ? "active" : ""} onClick={() => setTab("positions")}>
            Позиции ({positions.length})
          </button>
          <button className={tab === "orders" ? "active" : ""} onClick={() => setTab("orders")}>
            Отложенные ордера ({orders.length})
          </button>
          <button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>
            История сделок
          </button>
        </div>
        {tab === "positions" && <PositionsTable accountId={accountId!} positions={positions} canTrade={can("trader") && connected} />}
        {tab === "orders" && <OrdersTable accountId={accountId!} orders={orders} canTrade={can("trader") && connected} />}
        {tab === "history" && accountId && <History accountId={accountId} enabled={connected} />}
      </section>
    </div>
  );
}

function OrderTicket({
  accountId,
  symbol,
  tick,
  enabled,
  brief,
}: {
  accountId: number | null;
  symbol: string;
  tick: Tick | null;
  enabled: boolean;
  brief?: SymbolBrief;
}) {
  const [mode, setMode] = useState<"market" | "pending">("market");
  const [volume, setVolume] = useState("0.01");
  const [sl, setSl] = useState("");
  const [tp, setTp] = useState("");
  const [deviation, setDeviation] = useState("20");
  const [ptype, setPtype] = useState("buy_limit");
  const [price, setPrice] = useState("");
  const [check, setCheck] = useState<TradeResult | null>(null);
  const act = useAction();
  const num = (s: string) => (s.trim() === "" ? null : Number(s));
  const disabled = !enabled || !symbol || act.busy;

  async function market(side: "buy" | "sell") {
    if (!accountId) return;
    const px = side === "buy" ? tick?.ask : tick?.bid;
    if (!confirm(`${side.toUpperCase()} ${volume} ${symbol} по рынку (~${px ?? "?"})?`)) return;
    const r = await act.run(() =>
      api<TradeResult>(`/api/accounts/${accountId}/orders/market`, {
        method: "POST",
        body: { symbol, side, volume: Number(volume), sl: num(sl), tp: num(tp), deviation: Number(deviation) },
      }),
    );
    if (r) notify(r.ok ? "ok" : "err", resultText(r));
  }

  async function pending(e: FormEvent) {
    e.preventDefault();
    if (!accountId) return;
    if (!confirm(`${ORDER_TYPE_LABEL[ptype]} ${volume} ${symbol} @ ${price}?`)) return;
    const r = await act.run(() =>
      api<TradeResult>(`/api/accounts/${accountId}/orders/pending`, {
        method: "POST",
        body: { symbol, order_type: ptype, volume: Number(volume), price: Number(price), sl: num(sl), tp: num(tp) },
      }),
    );
    if (r) notify(r.ok ? "ok" : "err", resultText(r));
  }

  async function doCheck() {
    if (!accountId) return;
    const r = await act.run(() =>
      api<TradeResult>(`/api/accounts/${accountId}/orders/check`, {
        method: "POST",
        body: { symbol, side: "buy", volume: Number(volume), sl: num(sl), tp: num(tp) },
      }),
    );
    setCheck(r ?? null);
  }

  return (
    <div className="form">
      <div className="tabs small-tabs">
        <button className={mode === "market" ? "active" : ""} onClick={() => setMode("market")}>
          Рыночный
        </button>
        <button className={mode === "pending" ? "active" : ""} onClick={() => setMode("pending")}>
          Отложенный
        </button>
      </div>
      <div className="muted small">
        {symbol || "символ не выбран"}
        {brief && ` · лот ${brief.volume_min}–${brief.volume_max}, шаг ${brief.volume_step}`}
      </div>
      <Field label="Объём (лот)">
        <input type="number" step={brief?.volume_step ?? 0.01} min={brief?.volume_min ?? 0.01} value={volume} onChange={(e) => setVolume(e.target.value)} />
      </Field>
      {mode === "pending" && (
        <>
          <Field label="Тип">
            <select value={ptype} onChange={(e) => setPtype(e.target.value)}>
              {["buy_limit", "sell_limit", "buy_stop", "sell_stop"].map((t) => (
                <option key={t} value={t}>
                  {ORDER_TYPE_LABEL[t]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Цена">
            <input type="number" step="any" value={price} onChange={(e) => setPrice(e.target.value)} placeholder={tick ? String(tick.bid) : ""} />
          </Field>
        </>
      )}
      <div className="grid-2">
        <Field label="Stop Loss">
          <input type="number" step="any" value={sl} onChange={(e) => setSl(e.target.value)} placeholder="нет" />
        </Field>
        <Field label="Take Profit">
          <input type="number" step="any" value={tp} onChange={(e) => setTp(e.target.value)} placeholder="нет" />
        </Field>
      </div>
      {mode === "market" ? (
        <>
          <Field label="Отклонение (пунктов)">
            <input type="number" value={deviation} onChange={(e) => setDeviation(e.target.value)} />
          </Field>
          <div className="grid-2">
            <button className="btn btn-sell" disabled={disabled || !tick} onClick={() => market("sell")}>
              SELL
              <br />
              <small>{tick ? fmtPrice(tick.bid, tick.digits) : "—"}</small>
            </button>
            <button className="btn btn-buy" disabled={disabled || !tick} onClick={() => market("buy")}>
              BUY
              <br />
              <small>{tick ? fmtPrice(tick.ask, tick.digits) : "—"}</small>
            </button>
          </div>
          <button className="btn btn-ghost btn-sm" disabled={disabled} onClick={doCheck}>
            Проверить маржу (order_check)
          </button>
          {check && (
            <div className="muted small">
              {check.retcode_text}: маржа {fmtNum(check.margin)}, свободно после {fmtNum(check.margin_free)}
            </div>
          )}
        </>
      ) : (
        <button className="btn btn-primary" disabled={disabled || !price} onClick={pending}>
          Разместить ордер
        </button>
      )}
    </div>
  );
}

function PositionsTable({ accountId, positions, canTrade }: { accountId: number; positions: Position[]; canTrade: boolean }) {
  const [edit, setEdit] = useState<Position | null>(null);
  const act = useAction();

  async function close(p: Position, volume?: number) {
    if (!confirm(`Закрыть ${volume ?? p.volume} лот позиции #${p.ticket} ${p.symbol}?`)) return;
    const r = await act.run(() =>
      api<TradeResult>(`/api/accounts/${accountId}/positions/${p.ticket}/close`, { method: "POST", body: { volume: volume ?? null } }),
    );
    if (r) notify(r.ok ? "ok" : "err", resultText(r));
  }

  async function closeAll() {
    if (!confirm(`Закрыть ВСЕ позиции (${positions.length}) на счёте?`)) return;
    await act.run(
      () => api<{ closed: number }>(`/api/accounts/${accountId}/positions/close-all`, { method: "POST" }),
      (r) => `Закрыто позиций: ${r.closed}`,
    );
  }

  if (!positions.length) return <Empty>Открытых позиций нет</Empty>;
  return (
    <>
      <table className="table compact">
        <thead>
          <tr>
            <th>Тикет</th>
            <th>Время</th>
            <th>Символ</th>
            <th>Тип</th>
            <th>Объём</th>
            <th>Цена откр.</th>
            <th>Текущая</th>
            <th>S/L</th>
            <th>T/P</th>
            <th>Своп</th>
            <th>Прибыль</th>
            <th>Magic / комментарий</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr key={p.ticket}>
              <td>{p.ticket}</td>
              <td>{fmtServerTime(p.time)}</td>
              <td>{p.symbol}</td>
              <td className={p.side === "buy" ? "pos" : "neg"}>{p.side.toUpperCase()}</td>
              <td>{p.volume}</td>
              <td>{p.price_open}</td>
              <td>{p.price_current}</td>
              <td>{p.sl || "—"}</td>
              <td>{p.tp || "—"}</td>
              <td>{fmtNum(p.swap)}</td>
              <td className={pnlClass(p.profit)}>{fmtNum(p.profit)}</td>
              <td className="muted small">
                {p.magic || "ручная"} {p.comment}
              </td>
              <td className="actions">
                {canTrade && (
                  <>
                    <button className="btn btn-sm btn-ghost" onClick={() => setEdit(p)}>
                      SL/TP
                    </button>
                    <button className="btn btn-sm" disabled={act.busy} onClick={() => close(p)}>
                      Закрыть
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {canTrade && (
        <div className="table-foot">
          <span className="muted">
            Итого: <b className={pnlClass(positions.reduce((s, p) => s + p.profit, 0))}>{fmtNum(positions.reduce((s, p) => s + p.profit, 0))}</b>
          </span>
          <button className="btn btn-sm btn-danger" disabled={act.busy} onClick={closeAll}>
            Закрыть все
          </button>
        </div>
      )}
      {edit && <ModifyPosition accountId={accountId} p={edit} onClose={() => setEdit(null)} onPartial={(v) => close(edit, v)} />}
    </>
  );
}

function ModifyPosition({ accountId, p, onClose, onPartial }: { accountId: number; p: Position; onClose: () => void; onPartial: (v: number) => void }) {
  const [sl, setSl] = useState(p.sl ? String(p.sl) : "");
  const [tp, setTp] = useState(p.tp ? String(p.tp) : "");
  const [partial, setPartial] = useState("");
  const act = useAction();
  async function save(e: FormEvent) {
    e.preventDefault();
    const r = await act.run(() =>
      api<TradeResult>(`/api/accounts/${accountId}/positions/${p.ticket}`, {
        method: "PATCH",
        body: { sl: sl ? Number(sl) : 0, tp: tp ? Number(tp) : 0 },
      }),
    );
    if (r) {
      notify(r.ok ? "ok" : "err", resultText(r));
      if (r.ok) onClose();
    }
  }
  return (
    <Modal title={`Позиция #${p.ticket} ${p.symbol} ${p.side.toUpperCase()} ${p.volume}`} onClose={onClose}>
      <form className="form" onSubmit={save}>
        <div className="grid-2">
          <Field label="Stop Loss (пусто = убрать)">
            <input type="number" step="any" value={sl} onChange={(e) => setSl(e.target.value)} />
          </Field>
          <Field label="Take Profit (пусто = убрать)">
            <input type="number" step="any" value={tp} onChange={(e) => setTp(e.target.value)} />
          </Field>
        </div>
        <button className="btn btn-primary" disabled={act.busy}>
          Изменить SL/TP
        </button>
      </form>
      <hr />
      <div className="row gap-s">
        <input type="number" step="any" placeholder="Объём частичного закрытия" value={partial} onChange={(e) => setPartial(e.target.value)} />
        <button
          className="btn"
          disabled={!partial}
          onClick={() => {
            onPartial(Number(partial));
            onClose();
          }}
        >
          Закрыть частично
        </button>
      </div>
    </Modal>
  );
}

function OrdersTable({ accountId, orders, canTrade }: { accountId: number; orders: Order[]; canTrade: boolean }) {
  const [edit, setEdit] = useState<Order | null>(null);
  const [price, setPrice] = useState("");
  const [sl, setSl] = useState("");
  const [tp, setTp] = useState("");
  const act = useAction();

  async function cancel(o: Order) {
    if (!confirm(`Удалить ордер #${o.ticket}?`)) return;
    const r = await act.run(() => api<TradeResult>(`/api/accounts/${accountId}/orders/${o.ticket}`, { method: "DELETE" }));
    if (r) notify(r.ok ? "ok" : "err", resultText(r));
  }
  async function save(e: FormEvent) {
    e.preventDefault();
    if (!edit) return;
    const r = await act.run(() =>
      api<TradeResult>(`/api/accounts/${accountId}/orders/${edit.ticket}`, {
        method: "PATCH",
        body: { price: Number(price), sl: sl ? Number(sl) : 0, tp: tp ? Number(tp) : 0 },
      }),
    );
    if (r) {
      notify(r.ok ? "ok" : "err", resultText(r));
      if (r.ok) setEdit(null);
    }
  }

  if (!orders.length) return <Empty>Отложенных ордеров нет</Empty>;
  return (
    <>
      <table className="table compact">
        <thead>
          <tr>
            <th>Тикет</th>
            <th>Время</th>
            <th>Символ</th>
            <th>Тип</th>
            <th>Объём</th>
            <th>Цена</th>
            <th>S/L</th>
            <th>T/P</th>
            <th>Текущая</th>
            <th>Magic / комментарий</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.ticket}>
              <td>{o.ticket}</td>
              <td>{fmtServerTime(o.time_setup)}</td>
              <td>{o.symbol}</td>
              <td>{ORDER_TYPE_LABEL[o.order_type] ?? o.order_type}</td>
              <td>{o.volume_current}</td>
              <td>{o.price_open}</td>
              <td>{o.sl || "—"}</td>
              <td>{o.tp || "—"}</td>
              <td>{o.price_current}</td>
              <td className="muted small">
                {o.magic || "ручной"} {o.comment}
              </td>
              <td className="actions">
                {canTrade && (
                  <>
                    <button
                      className="btn btn-sm btn-ghost"
                      onClick={() => {
                        setEdit(o);
                        setPrice(String(o.price_open));
                        setSl(o.sl ? String(o.sl) : "");
                        setTp(o.tp ? String(o.tp) : "");
                      }}
                    >
                      Изменить
                    </button>
                    <button className="btn btn-sm" disabled={act.busy} onClick={() => cancel(o)}>
                      Удалить
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {edit && (
        <Modal title={`Ордер #${edit.ticket}`} onClose={() => setEdit(null)}>
          <form className="form" onSubmit={save}>
            <Field label="Цена">
              <input type="number" step="any" value={price} onChange={(e) => setPrice(e.target.value)} required />
            </Field>
            <div className="grid-2">
              <Field label="Stop Loss">
                <input type="number" step="any" value={sl} onChange={(e) => setSl(e.target.value)} />
              </Field>
              <Field label="Take Profit">
                <input type="number" step="any" value={tp} onChange={(e) => setTp(e.target.value)} />
              </Field>
            </div>
            <button className="btn btn-primary" disabled={act.busy}>
              Сохранить
            </button>
          </form>
        </Modal>
      )}
    </>
  );
}

function toDateInput(d: Date) {
  return d.toISOString().slice(0, 10);
}

function History({ accountId, enabled }: { accountId: number; enabled: boolean }) {
  const [from, setFrom] = useState(toDateInput(new Date(Date.now() - 7 * 86400000)));
  const [to, setTo] = useState(toDateInput(new Date()));
  const [deals, setDeals] = useState<Deal[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setBusy(true);
    try {
      const f = Date.parse(from + "T00:00:00Z") / 1000;
      const t = Date.parse(to + "T23:59:59Z") / 1000 + 86400; // server time may be ahead of UTC
      setDeals(await api<Deal[]>(`/api/accounts/${accountId}/history/deals`, { query: { date_from: f, date_to: t } }));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (enabled) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accountId, enabled]);

  const total = (deals ?? []).reduce((s, d) => s + d.profit + d.commission + d.swap + d.fee, 0);
  return (
    <div>
      <div className="row gap-s filter-row">
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        <span>—</span>
        <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        <button className="btn btn-sm" disabled={!enabled || busy} onClick={load}>
          Показать
        </button>
        {deals && (
          <span className="muted">
            Сделок: {deals.length}, итог: <b className={pnlClass(total)}>{fmtNum(total)}</b>
          </span>
        )}
      </div>
      <ErrorBox error={error} />
      {deals && deals.length === 0 && <Empty>Сделок за период нет</Empty>}
      {deals && deals.length > 0 && <DealsTable deals={deals} />}
    </div>
  );
}

export function DealsTable({ deals }: { deals: Deal[] }) {
  return (
    <table className="table compact">
      <thead>
        <tr>
          <th>Сделка</th>
          <th>Время</th>
          <th>Символ</th>
          <th>Тип</th>
          <th>Вход/выход</th>
          <th>Объём</th>
          <th>Цена</th>
          <th>Комиссия</th>
          <th>Своп</th>
          <th>Прибыль</th>
          <th>Позиция</th>
          <th>Magic / комментарий</th>
        </tr>
      </thead>
      <tbody>
        {[...deals]
          .sort((a, b) => b.time - a.time)
          .map((d) => (
            <tr key={d.ticket}>
              <td>{d.ticket}</td>
              <td>{fmtServerTime(d.time)}</td>
              <td>{d.symbol || "—"}</td>
              <td>{d.deal_type}</td>
              <td>{d.deal_entry}</td>
              <td>{d.volume || "—"}</td>
              <td>{d.price || "—"}</td>
              <td>{fmtNum(d.commission)}</td>
              <td>{fmtNum(d.swap)}</td>
              <td className={pnlClass(d.profit)}>{fmtNum(d.profit)}</td>
              <td>{d.position_id || "—"}</td>
              <td className="muted small">
                {d.magic || ""} {d.comment}
              </td>
            </tr>
          ))}
      </tbody>
    </table>
  );
}
