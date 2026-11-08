export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtPrice(v: number | null | undefined, digits = 5): string {
  if (v === null || v === undefined || v === 0) return "—";
  return v.toFixed(digits);
}

/** MT5 returns times as seconds in the trade-server timezone. We show them "as is". */
export function fmtServerTime(sec: number | null | undefined): string {
  if (!sec) return "—";
  const d = new Date(sec * 1000);
  return d.toISOString().replace("T", " ").slice(0, 19);
}

export function fmtIso(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("ru-RU");
}

export function fmtDuration(s: number): string {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (d) return `${d}д ${h}ч ${m}м`;
  if (h) return `${h}ч ${m}м`;
  if (m) return `${m}м ${sec}с`;
  return `${sec}с`;
}

export function pnlClass(v: number | null | undefined): string {
  if (!v) return "";
  return v > 0 ? "pos" : "neg";
}

export const ORDER_TYPE_LABEL: Record<string, string> = {
  buy: "Buy",
  sell: "Sell",
  buy_limit: "Buy Limit",
  sell_limit: "Sell Limit",
  buy_stop: "Buy Stop",
  sell_stop: "Sell Stop",
  buy_stop_limit: "Buy Stop Limit",
  sell_stop_limit: "Sell Stop Limit",
};

export const TRADE_MODE_LABEL: Record<string, string> = { demo: "DEMO", contest: "CONTEST", real: "REAL" };

export function signalLabel(v: unknown): string {
  if (v === 1) return "ЛОНГ";
  if (v === -1) return "ШОРТ";
  if (v === 0) return "ВНЕ РЫНКА";
  return "—";
}
