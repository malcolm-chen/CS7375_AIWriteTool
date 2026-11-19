import { api, type ClientEvent } from '../api';
import type { EventType } from '../types';

/** Buffers interaction events and flushes them every 5 s or when the page is hidden. */
export class EventLogger {
  private queue: ClientEvent[] = [];
  private timer: number | undefined;
  private url: string;
  count = 0;

  constructor(sessionId: string, token: string | null, private onCount?: (n: number) => void) {
    this.url = api.eventsUrl(sessionId, token);
  }

  start() {
    this.timer = window.setInterval(() => this.flush(), 5000);
    document.addEventListener('visibilitychange', this.onVisibility);
    window.addEventListener('pagehide', this.onPageHide);
  }

  stop() {
    window.clearInterval(this.timer);
    document.removeEventListener('visibilitychange', this.onVisibility);
    window.removeEventListener('pagehide', this.onPageHide);
    this.flush(true);
  }

  log(type: EventType, editId?: string, payload?: Record<string, unknown>) {
    this.queue.push({ ts: new Date().toISOString(), type, editId, payload });
    this.count += 1;
    this.onCount?.(this.count);
  }

  flush(beacon = false): Promise<void> {
    if (!this.queue.length) return Promise.resolve();
    const events = this.queue;
    this.queue = [];
    const body = JSON.stringify({ events });
    if (beacon && navigator.sendBeacon?.(this.url, new Blob([body], { type: 'application/json' }))) return Promise.resolve();
    return fetch(this.url, { method: 'POST', body, headers: { 'Content-Type': 'application/json' }, keepalive: true })
      .then((r) => {
        if (!r.ok) throw new Error(String(r.status));
      })
      .catch(() => {
        this.queue = events.concat(this.queue);
      });
  }

  private onVisibility = () => {
    if (document.visibilityState === 'hidden') this.flush(true);
  };

  private onPageHide = () => {
    this.log('session_end');
    this.flush(true);
  };
}
