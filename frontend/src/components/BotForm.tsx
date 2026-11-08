import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { useAccounts } from "../accounts";
import { useApi } from "../hooks";
import { defaultsOf, ParamForm } from "./ParamForm";
import { ErrorBox, Field } from "./ui";
import type { Bot, Catalog, SymbolBrief } from "../types";

export function BotForm({ bot, onSaved, disabled }: { bot: Bot | null; onSaved: (b: Bot) => void; disabled?: boolean }) {
  const { accounts } = useAccounts();
  const cat = useApi<Catalog>("/api/bots/strategies");
  const [name, setName] = useState(bot?.name ?? "");
  const [accountId, setAccountId] = useState<number | "">(bot?.account_id ?? "");
  const [strategy, setStrategy] = useState(bot?.strategy ?? "sma_cross");
  const [symbol, setSymbol] = useState(bot?.symbol ?? "");
  const [timeframe, setTimeframe] = useState(bot?.timeframe ?? "M15");
  const [tradeMode, setTradeMode] = useState<"live" | "signals">(bot?.trade_mode ?? "live");
  const [params, setParams] = useState<Record<string, number | boolean>>(bot?.params ?? {});
  const [risk, setRisk] = useState<Record<string, number | boolean>>(bot?.risk ?? {});
  const [symbols, setSymbols] = useState<SymbolBrief[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const strat = cat.data?.strategies.find((s) => s.key === strategy);
  const acc = accounts.find((a) => a.id === accountId);

  useEffect(() => {
    if (accountId === "" && accounts.length) setAccountId(accounts[0].id);
  }, [accounts, accountId]);

  useEffect(() => {
    if (!cat.data) return;
    if (!bot || bot.strategy !== strategy) setParams(defaultsOf(strat?.params ?? []));
    if (!bot) setRisk(defaultsOf(cat.data.risk));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cat.data, strategy]);

  useEffect(() => {
    if (!acc || acc.runtime.status !== "connected") {
      setSymbols([]);
      return;
    }
    api<SymbolBrief[]>(`/api/accounts/${acc.id}/symbols`).then(setSymbols).catch(() => setSymbols([]));
  }, [acc?.id, acc?.runtime.status]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body = { name, account_id: accountId, strategy, symbol, timeframe, trade_mode: tradeMode, params, risk };
    try {
      const b = bot ? await api<Bot>(`/api/bots/${bot.id}`, { method: "PATCH", body }) : await api<Bot>("/api/bots", { method: "POST", body });
      onSaved(b);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!cat.data) return <div className="muted">Загрузка каталога стратегий…</div>;
  return (
    <form className="form" onSubmit={submit}>
      <ErrorBox error={error} />
      {disabled && <div className="alert alert-info">Бот работает — остановите его, чтобы изменить настройки.</div>}
      <fieldset disabled={disabled} className="plain">
        <div className="grid-2">
          <Field label="Имя бота">
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </Field>
          <Field label="Счёт MT5">
            <select value={accountId} onChange={(e) => setAccountId(Number(e.target.value))} required>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} #{a.login}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Символ" hint={symbols.length ? `${symbols.length} символов у брокера` : "Подключите счёт, чтобы видеть список символов"}>
            <input list="bot-symbols" value={symbol} onChange={(e) => setSymbol(e.target.value.trim())} required placeholder="EURUSD" />
            <datalist id="bot-symbols">
              {symbols.slice(0, 3000).map((s) => (
                <option key={s.name} value={s.name}>
                  {s.description}
                </option>
              ))}
            </datalist>
          </Field>
          <Field label="Таймфрейм">
            <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              {cat.data.timeframes.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </Field>
          <Field label="Стратегия">
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              {cat.data.strategies.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.title}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Режим">
            <select value={tradeMode} onChange={(e) => setTradeMode(e.target.value as "live" | "signals")}>
              <option value="live">Торговля — отправлять ордера в MT5</option>
              <option value="signals">Только сигналы — без ордеров</option>
            </select>
          </Field>
        </div>
        {strat && <p className="muted small">{strat.description}</p>}
        <h4>Параметры стратегии</h4>
        <ParamForm defs={strat?.params ?? []} values={params} onChange={setParams} />
        <h4>Риск-менеджмент</h4>
        <ParamForm defs={cat.data.risk} values={risk} onChange={setRisk} />
        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy}>
            {bot ? "Сохранить настройки" : "Создать бота"}
          </button>
        </div>
      </fieldset>
    </form>
  );
}
