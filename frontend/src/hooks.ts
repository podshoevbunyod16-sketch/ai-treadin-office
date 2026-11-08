import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { live, WsMessage } from "./ws";

export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const seq = useRef(0);

  const reload = useCallback(async () => {
    if (!path) return;
    const my = ++seq.current;
    setLoading(true);
    try {
      const d = await api<T>(path);
      if (my === seq.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (my === seq.current) setError((e as Error).message);
    } finally {
      if (my === seq.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);

  useEffect(() => {
    setData(null);
    reload();
  }, [reload]);

  return { data, setData, error, loading, reload };
}

export function useTopic(topic: string | null, handler: (m: WsMessage) => void) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    if (!topic) return;
    return live.subscribe(topic, (m) => ref.current(m));
  }, [topic]);
}

export function useWsStatus(): boolean {
  const [c, setC] = useState(live.connected);
  useEffect(() => live.onStatus(setC), []);
  return c;
}

export function useInterval(fn: () => void, ms: number | null) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    if (ms === null) return;
    const id = window.setInterval(() => ref.current(), ms);
    return () => window.clearInterval(id);
  }, [ms]);
}
