import { ReactNode, useEffect, useState } from "react";
import { TRADE_MODE_LABEL } from "../format";

export function Badge({ kind, children, title }: { kind: string; children: ReactNode; title?: string }) {
  return (
    <span className={`badge badge-${kind}`} title={title}>
      {children}
    </span>
  );
}

const STATUS: Record<string, [string, string]> = {
  connected: ["ok", "Подключён"],
  connecting: ["warn", "Подключение…"],
  disconnected: ["muted", "Отключён"],
  error: ["err", "Ошибка"],
  running: ["ok", "Работает"],
  starting: ["warn", "Запуск…"],
  stopped: ["muted", "Остановлен"],
};

export function StatusBadge({ status, title }: { status: string; title?: string }) {
  const [kind, label] = STATUS[status] ?? ["muted", status];
  return (
    <Badge kind={kind} title={title}>
      <span className="dot" /> {label}
    </Badge>
  );
}

export function ModeBadge({ mode }: { mode: string | null | undefined }) {
  if (!mode) return null;
  return <Badge kind={mode === "real" ? "err" : "info"}>{TRADE_MODE_LABEL[mode] ?? mode}</Badge>;
}

export function ErrorBox({ error }: { error: string | null | undefined }) {
  if (!error) return null;
  return <div className="alert alert-err">{error}</div>;
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className={`modal ${wide ? "modal-wide" : ""}`} onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="btn-icon" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Stat({ label, value, cls }: { label: string; value: ReactNode; cls?: string }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${cls ?? ""}`}>{value}</div>
    </div>
  );
}

// ---------------------------------------------------------------- toasts
type Toast = { id: number; kind: "ok" | "err" | "info"; text: string };
let nextId = 1;

export function notify(kind: Toast["kind"], text: string) {
  window.dispatchEvent(new CustomEvent("ato:toast", { detail: { id: nextId++, kind, text } }));
}

export function Toaster() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => {
    const h = (e: Event) => {
      const t = (e as CustomEvent<Toast>).detail;
      setItems((xs) => [...xs, t]);
      window.setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== t.id)), t.kind === "err" ? 9000 : 5000);
    };
    window.addEventListener("ato:toast", h);
    return () => window.removeEventListener("ato:toast", h);
  }, []);
  return (
    <div className="toasts">
      {items.map((t) => (
        <div key={t.id} className={`toast toast-${t.kind}`} onClick={() => setItems((xs) => xs.filter((x) => x.id !== t.id))}>
          {t.text}
        </div>
      ))}
    </div>
  );
}

/** Runs an async action, shows a toast for errors, tracks the busy flag. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  async function run<T>(fn: () => Promise<T>, okText?: string | ((r: T) => string)): Promise<T | undefined> {
    setBusy(true);
    try {
      const r = await fn();
      if (okText) notify("ok", typeof okText === "function" ? okText(r) : okText);
      return r;
    } catch (e) {
      notify("err", (e as Error).message);
      return undefined;
    } finally {
      setBusy(false);
    }
  }
  return { busy, run };
}
