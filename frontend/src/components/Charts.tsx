import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  IChartApi,
  ISeriesApi,
  LineSeries,
  UTCTimestamp,
} from "lightweight-charts";
import type { Rate } from "../types";

const THEME = {
  layout: { background: { type: ColorType.Solid, color: "#0e1626" }, textColor: "#9fb0c8", fontSize: 11 },
  grid: { vertLines: { color: "#18233a" }, horzLines: { color: "#18233a" } },
  rightPriceScale: { borderColor: "#24324d" },
  timeScale: { borderColor: "#24324d", timeVisible: true, secondsVisible: false },
  autoSize: true,
};

export interface LivePrice {
  time: number;
  price: number;
}

export function CandleChart({ rates, digits, tfSeconds, live }: { rates: Rate[]; digits: number; tfSeconds: number; live: LivePrice | null }) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const last = useRef<{ time: number; open: number; high: number; low: number; close: number } | null>(null);

  useEffect(() => {
    if (!el.current) return;
    const c = createChart(el.current, THEME);
    series.current = c.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });
    chart.current = c;
    return () => {
      c.remove();
      chart.current = null;
      series.current = null;
    };
  }, []);

  useEffect(() => {
    if (!series.current) return;
    series.current.applyOptions({ priceFormat: { type: "price", precision: digits, minMove: 1 / 10 ** digits } });
    const data = rates.map((r) => ({ time: r.time as UTCTimestamp, open: r.open, high: r.high, low: r.low, close: r.close }));
    series.current.setData(data);
    last.current = rates.length ? { ...rates[rates.length - 1] } : null;
    chart.current?.timeScale().scrollToRealTime();
  }, [rates, digits]);

  useEffect(() => {
    if (!live || !series.current || !last.current) return;
    const b = last.current;
    const barTime = Math.floor(live.time / tfSeconds) * tfSeconds;
    if (barTime > b.time) {
      last.current = { time: barTime, open: live.price, high: live.price, low: live.price, close: live.price };
    } else {
      b.close = live.price;
      b.high = Math.max(b.high, live.price);
      b.low = Math.min(b.low, live.price);
    }
    const n = last.current;
    series.current.update({ time: n.time as UTCTimestamp, open: n.open, high: n.high, low: n.low, close: n.close });
  }, [live, tfSeconds]);

  return <div ref={el} className="chart" />;
}

export function LineChart({ points, height = 220 }: { points: { time: number; value: number }[]; height?: number }) {
  const el = useRef<HTMLDivElement>(null);
  const series = useRef<ISeriesApi<"Line"> | null>(null);
  useEffect(() => {
    if (!el.current) return;
    const c = createChart(el.current, THEME);
    series.current = c.addSeries(LineSeries, { color: "#22d3a6", lineWidth: 2 });
    return () => c.remove();
  }, []);
  useEffect(() => {
    // lightweight-charts requires strictly increasing unique times
    const seen = new Map<number, number>();
    for (const p of points) seen.set(p.time, p.value);
    const data = [...seen.entries()].sort((a, b) => a[0] - b[0]).map(([t, v]) => ({ time: t as UTCTimestamp, value: v }));
    series.current?.setData(data);
  }, [points]);
  return <div ref={el} className="chart" style={{ height }} />;
}
