type SseEvent = "status" | "alert" | "metric";

type Callback = (data: unknown) => void;

class SseManager {
  private es: EventSource | null = null;
  private callbacks: Map<SseEvent, Set<Callback>> = new Map();
  private _connected = false;
  private backoff = 1000;
  constructor() {
    this.callbacks.set("status", new Set());
    this.callbacks.set("alert", new Set());
    this.callbacks.set("metric", new Set());
  }

  get connected(): boolean {
    return this._connected;
  }

  connect(token: string): void {
    this.disconnect();
    const url = `/api/stream?token=${encodeURIComponent(token)}`;
    this.es = new EventSource(url);
    this.es.onopen = () => {
      this._connected = true;
      this.backoff = 1000;
    };
    this.es.onerror = () => {
      this._connected = false;
      if (this.es) this.es.close();
      const delay = this.backoff;
      this.backoff = Math.min(this.backoff * 2, 30000);
      setTimeout(() => {
        if (token) this.connect(token);
      }, delay);
    };
    this.es.addEventListener("status", (ev) => this.dispatch("status", this.parse(ev)));
    this.es.addEventListener("metric", (ev) => this.dispatch("metric", this.parse(ev)));
    this.es.addEventListener("alert", (ev) => this.dispatch("alert", this.parse(ev)));
  }

  private parse(ev: MessageEvent): unknown {
    try {
      return JSON.parse(ev.data);
    } catch {
      return null;
    }
  }

  disconnect(): void {
    if (this.es) {
      this.es.close();
      this.es = null;
    }
    this._connected = false;
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
