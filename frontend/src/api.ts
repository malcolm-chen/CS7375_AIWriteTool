import type { AnyView, BalanceReport, Decision, EventType, SessionSummary } from './types';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    credentials: 'same-origin',
    ...init,
    headers: init.body ? { 'Content-Type': 'application/json', ...init.headers } : init.headers,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

const withToken = (path: string, token: string | null) => (token ? `${path}?t=${encodeURIComponent(token)}` : path);

export interface ClientEvent {
  ts: string;
  type: EventType;
  editId?: string;
  payload?: Record<string, unknown>;
}

export const api = {
  me: () => request<{ role: 'admin' | null }>('/api/auth/me'),
  login: (password: string) => request('/api/auth/login', { method: 'POST', body: JSON.stringify({ password }) }),
  logout: () => request('/api/auth/logout', { method: 'POST' }),

  startDemo: () => request<{ id: string; token: string }>('/api/demo', { method: 'POST' }),
  session: (id: string, token: string | null) => request<AnyView>(withToken(`/api/sessions/${id}`, token)),
  saveDraft: (id: string, token: string | null, text: string) =>
    request(withToken(`/api/sessions/${id}/draft`, token), { method: 'PUT', body: JSON.stringify({ text }) }),
  enhance: (id: string, token: string | null, text: string) =>
    request<AnyView>(withToken(`/api/sessions/${id}/enhance`, token), { method: 'POST', body: JSON.stringify({ text }) }),
  eventsUrl: (id: string, token: string | null) => withToken(`/api/sessions/${id}/events`, token),
  decide: (id: string, token: string | null, d: Decision) =>
    request(withToken(`/api/sessions/${id}/decisions`, token), { method: 'POST', body: JSON.stringify(d) }),
  undo: (id: string, token: string | null, editId: string) =>
    request(withToken(`/api/sessions/${id}/decisions/${editId}`, token), { method: 'DELETE' }),

  sessions: () =>
    request<{
      sessions: SessionSummary[];
      tasks: Record<string, string>;
      studyTasks: string[];
      studyConditions: string[];
      balance: BalanceReport;
      aiConfigured: boolean;
      aiModel: string;
    }>(
      '/api/admin/sessions',
    ),
  /** taskId null: every study task, in a random order per participant. */
  createSessions: (participantIds: string[], taskId: string | null, condition: string | null = null) =>
    request<{ created: SessionSummary[] }>('/api/admin/sessions', {
      method: 'POST',
      body: JSON.stringify({ participantIds, taskId, condition }),
    }),
  importData: (data: unknown) =>
    request<{ created: SessionSummary[]; failed: { index: number; sourceId: string | null; error: string }[] }>(
      '/api/admin/import',
      { method: 'POST', body: JSON.stringify({ data }) },
    ),
  reset: (id: string) => request(`/api/admin/sessions/${id}/reset`, { method: 'POST' }),
  regenerateLink: (id: string) => request<{ token: string }>(`/api/admin/sessions/${id}/link`, { method: 'POST' }),
  remove: (id: string) => request(`/api/admin/sessions/${id}`, { method: 'DELETE' }),
  exportUrl: (format: 'json' | 'csv', sessionId?: string) =>
    `/api/admin/export?format=${format}${sessionId ? `&sessionId=${sessionId}` : ''}`,
};

export const participantLink = (s: Pick<SessionSummary, 'id' | 'token'>) =>
  `${location.origin}/session/${s.id}?t=${encodeURIComponent(s.token)}`;
