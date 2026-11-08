import { getToken } from "./api";

export interface WsMessage {
  topic: string;
  type: string;
  data: any;
  ts?: number;
}

type Handler = (msg: WsMessage) => void;
type StatusListener = (connected: boolean) => void;

class LiveSocket {
  private ws: WebSocket | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private statusListeners = new Set<StatusListener>();
  private retry = 0;
  private timer: number | null = null;
  private pingTimer: number | null = null;
  private stopped = true;
  connected = false;

  start(): void {
    this.stopped = false;
    if (!this.ws) this.open();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer) window.clearTimeout(this.timer);
    if (this.pingTimer) window.clearInterval(this.pingTimer);
    this.ws?.close();
    this.ws = null;
    this.setConnected(false);
  }

  private setConnected(v: boolean) {
    this.connected = v;
    this.statusListeners.forEach((l) => l(v));
  }

  private open() {
    const token = getToken();
    if (!token) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(token)}`);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.setConnected(true);
      const topics = [...this.handlers.keys()];
      if (topics.length) ws.send(JSON.stringify({ action: "subscribe", topics }));
      this.pingTimer = window.setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ action: "ping" }));
      }, 25000);
    };
    ws.onmessage = (ev) => {
      let msg: WsMessage;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      this.handlers.get(msg.topic)?.forEach((h) => h(msg));
    };
    ws.onclose = () => {
      if (this.pingTimer) window.clearInterval(this.pingTimer);
      this.ws = null;
      this.setConnected(false);
      if (this.stopped) return;
      const delay = Math.min(30000, 1000 * 2 ** this.retry++);
      this.timer = window.setTimeout(() => this.open(), delay);
    };
  }

  subscribe(topic: string, handler: Handler): () => void {
    let set = this.handlers.get(topic);
    if (!set) {
      set = new Set();
      this.handlers.set(topic, set);
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ action: "subscribe", topics: [topic] }));
      }
    }
    set.add(handler);
    return () => {
      const s = this.handlers.get(topic);
      if (!s) return;
      s.delete(handler);
      if (s.size === 0) {
        this.handlers.delete(topic);
        if (this.ws?.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ action: "unsubscribe", topics: [topic] }));
        }
      }
    };
  }

  onStatus(l: StatusListener): () => void {
    this.statusListeners.add(l);
    return () => this.statusListeners.delete(l);
  }
}

export const live = new LiveSocket();
