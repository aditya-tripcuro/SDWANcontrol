import { apiFetch } from "./client";

type SseEvent = "status" | "alert" | "metric";

type Callback = (data: unknown) => void;

class SseManager {
  private es: EventSource | null = null;
  private callbacks: Map<SseEvent, Set<Callback>> = new Map();
  private _connected = false;
  private backoff = 1000;
  private _retryId = 0;

  constructor() {
    this.callbacks.set("status", new Set());
    this.callbacks.set("alert", new Set());
    this.callbacks.set("metric", new Set());
  }

  get connected(): boolean {
    return this._connected;
  }

  connect(): void {
    this.disconnect();
    const retryId = this._retryId;
    // A browser EventSource cannot send auth headers, so we first mint a
    // short-lived, single-use ticket via apiFetch (which carries whatever auth
    // the rest of the app uses) and pass it in the query string. Each (re)connect
    // fetches a FRESH ticket because tickets are single-use and expire quickly.
    apiFetch<{ ticket: string }>("/api/stream/ticket", { method: "POST" })
      .then(({ ticket }) => {
        if (this._retryId !== retryId) return; // superseded by disconnect()/connect()
        this.openStream(ticket, retryId);
      })
      .catch(() => {
        if (this._retryId !== retryId) return;
        this.scheduleReconnect(retryId);
      });
  }

  private openStream(ticket: string, retryId: number): void {
    this.es = new EventSource(`/api/stream?ticket=${encodeURIComponent(ticket)}`);
    this.es.onopen = () => {
      this._connected = true;
      this.backoff = 1000;
    };
    this.es.onerror = () => {
      this._connected = false;
      // Close to stop native auto-reconnect (which would replay the now-consumed
      // ticket); our manual reconnect fetches a new one.
      if (this.es) this.es.close();
      this.scheduleReconnect(retryId);
    };
    this.es.addEventListener("status", (ev) => this.dispatch("status", this.parse(ev as MessageEvent)));
    this.es.addEventListener("metric", (ev) => this.dispatch("metric", this.parse(ev as MessageEvent)));
    this.es.addEventListener("alert", (ev) => this.dispatch("alert", this.parse(ev as MessageEvent)));
  }

  private scheduleReconnect(retryId: number): void {
    const delay = this.backoff;
    this.backoff = Math.min(this.backoff * 2, 30000);
    setTimeout(() => {
      if (this._retryId === retryId) this.connect(); // re-fetches a fresh ticket
    }, delay);
  }

  private parse(ev: MessageEvent): unknown {
    try {
      return JSON.parse(ev.data);
    } catch {
      return null;
    }
  }

  disconnect(): void {
    this._retryId++;
    if (this.es) {
      this.es.close();
      this.es = null;
    }
    this._connected = false;
    this.backoff = 1000;
  }

  on(event: SseEvent, cb: Callback): void {
    this.callbacks.get(event)?.add(cb);
  }

  off(event: SseEvent, cb: Callback): void {
    this.callbacks.get(event)?.delete(cb);
  }

  private dispatch(event: SseEvent, data: unknown) {
    for (const cb of this.callbacks.get(event) || []) cb(data);
  }
}

export const sseManager = new SseManager();
