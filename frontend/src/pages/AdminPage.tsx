import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError, participantLink } from '../api';
import type { GroupStatus, SessionSummary } from '../types';
import styles from './Admin.module.css';

const CONDITION = { reasons: 'With AI explanations', noReasons: 'No explanations' } as const;
const conditionLabel = (c: string) => CONDITION[c as keyof typeof CONDITION] ?? c;
const GROUP_STATUS: Record<GroupStatus, string> = {
  unassigned: 'Link not opened yet',
  in_progress: 'In progress',
  completed: 'Completed',
  abandoned: 'Abandoned, not counted',
};

/** How many participants are in each assignment, so the researcher can see the study stays balanced. */
function BalanceCard({ data }: { data: AdminData }) {
  const b = data.balance;
  const title = (id: string) => data.tasks[id] ?? id;
  return (
    <section className="card">
      <h2>Balance</h2>
      <p className={styles.sub}>
        Each participant is assigned when they first open their link, to the order used least among participants
        still in the study: completed, or started less than {b.abandonHours} h ago. Anyone who started earlier and
        hasn’t finished counts as abandoned, and their slot goes to the next participant. Demo sessions don’t count.
        {b.unopened > 0 && <> {b.unopened} link{b.unopened === 1 ? '' : 's'} not opened yet.</>}
      </p>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr><th>Task 1</th><th>Task 2</th><th>Completed</th><th>In progress</th><th>Abandoned</th></tr>
          </thead>
          <tbody>
            {b.cells.map((cell, i) => (
              <tr key={i}>
                {cell.assignment.map((a, j) => (
                  <td key={j}>{title(a.taskId)}<div className="faint">{conditionLabel(a.condition)}</div></td>
                ))}
                <td className={styles.num}>{cell.completed}</td>
                <td className={styles.num}>{cell.in_progress}</td>
                <td className={`${styles.num} faint`}>{cell.abandoned}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className={styles.tableWrap}>
        <table className={styles.table} style={{ marginTop: 16 }}>
          <thead>
            <tr><th>Task</th><th>Condition</th><th>Completed</th><th>In progress</th></tr>
          </thead>
          <tbody>
            {b.byTaskCondition.map((x) => (
              <tr key={`${x.taskId}-${x.condition}`}>
                <td>{title(x.taskId)}</td>
                <td>{conditionLabel(x.condition)}</td>
                <td className={styles.num}>{x.completed}</td>
                <td className={styles.num}>{x.in_progress}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

type AdminData = Awaited<ReturnType<typeof api.sessions>>;

function Login({ onDone }: { onDone(): void }) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.login(password);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    }
  };
  return (
    <div className={`card ${styles.login}`}>
      <form onSubmit={submit}>
        <h1 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>Researcher login</h1>
        <input type="password" aria-label="Password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus />
        {error && <p className="err">{error}</p>}
        <button className="btn primary" type="submit">Log in</button>
      </form>
    </div>
  );
}

function CreateCard({ data, onCreated }: { data: AdminData; onCreated(): void }) {
  const [ids, setIds] = useState('');
  // '' = every study task in a random order per participant; a task id = that task alone (piloting).
  const [taskId, setTaskId] = useState('');
  const [condition, setCondition] = useState('reasons');
  const [created, setCreated] = useState<SessionSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const list = ids.split(/[\s,]+/).filter(Boolean);

  const run = async () => {
    setError(null);
    try {
      const res = await api.createSessions(list, taskId || null, taskId ? condition : null);
      setCreated(res.created.filter((s) => (s.seq ?? 1) === 1));
      setIds('');
      onCreated();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <section className="card">
      <h2>Create sessions</h2>
      <p className={styles.sub}>
        Each participant writes their own draft for each task, the AI revises it, and they review the changes. With
        all tasks, one link leads through every task. The task order and which task shows the AI’s explanations are
        assigned when the participant first opens the link, balanced across participants (see Balance below).{' '}
        {data.aiConfigured ? (
          <span className="ok">AI model: {data.aiModel} (falls back left to right)</span>
        ) : (
          <span className="err" style={{ display: 'inline' }}>No AI provider is configured in backend/.env (LLM_PROVIDERS and an API key), so revisions will fail.</span>
        )}
      </p>
      <div className={styles.row}>
        <input
          type="text"
          className={styles.grow}
          aria-label="Participant IDs"
          placeholder="Participant IDs, separated by commas or spaces (e.g. P01, P02)"
          value={ids}
          onChange={(e) => setIds(e.target.value)}
        />
        <select value={taskId} onChange={(e) => setTaskId(e.target.value)} aria-label="Task">
          <option value="">All {data.studyTasks.length} tasks, random order</option>
          {Object.entries(data.tasks).map(([k, title]) => <option key={k} value={k}>Only: {title}</option>)}
        </select>
        {taskId && (
          <select value={condition} onChange={(e) => setCondition(e.target.value)} aria-label="Explanation condition">
            {data.studyConditions.map((c) => <option key={c} value={c}>{conditionLabel(c)}</option>)}
          </select>
        )}
        <button className="btn primary" onClick={run} disabled={!list.length}>Create for {list.length > 1 ? `${list.length} participants` : 'participant'}</button>
      </div>
      {error && <p className="err">{error}</p>}
      {created.length > 0 && (
        <div className={styles.result}>
          <p className="ok" style={{ margin: '0 0 4px' }}>Created {created.length}. Send each participant their link:</p>
          <ul>
            {created.map((s) => <li key={s.id}><b>{s.participantId}</b> <span className={styles.mono}>{participantLink(s)}</span></li>)}
          </ul>
        </div>
      )}
    </section>
  );
}

type ImportResult = Awaited<ReturnType<typeof api.importData>>;

function ImportCard({ onImported }: { onImported(): void }) {
  const [text, setText] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setError(null);
    setResult(null);
    let data: unknown;
    try {
      data = JSON.parse(text);
    } catch {
      setError('Not valid JSON.');
      return;
    }
    try {
      setResult(await api.importData(data));
      onImported();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <details className={`card ${styles.importCard}`}>
      <summary>Import pre-generated revisions (JSON)</summary>
      <p className={styles.sub} style={{ marginTop: 10 }}>
        Skips the writing step: each record with <code>original</code>, <code>revised</code>, and optional <code>edits</code>{' '}
        (<code>explanation</code>, <code>kind: "grammar"</code>) becomes a review session. See <code>sample_data/sample_revisions.json</code>.
      </p>
      <div className={styles.row}>
        <label className="btn">
          Choose file…
          <input
            type="file"
            accept="application/json,.json"
            hidden
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (!f) return;
              setFileName(f.name);
              setText(await f.text());
            }}
          />
        </label>
        <span className="faint">{fileName ?? 'or paste JSON below'}</span>
      </div>
      <textarea className={styles.paste} value={text} onChange={(e) => setText(e.target.value)} placeholder='[{"participantId": "P01", "original": "…", "revised": "…"}]' aria-label="JSON to import" />
      <button className="btn" onClick={run} disabled={!text.trim()}>Import</button>
      {error && <p className="err">{error}</p>}
      {result && (
        <div className={styles.result}>
          <p className="ok" style={{ margin: 0 }}>Created {result.created.length} session(s).</p>
          {result.failed.length > 0 && (
            <ul className="err">
              {result.failed.map((f) => <li key={f.index}>Record {f.index}{f.sourceId ? ` (${f.sourceId})` : ''}: {f.error}</li>)}
            </ul>
          )}
        </div>
      )}
    </details>
  );
}

const STAGE = { writing: 'Writing', enhancing: 'AI revising', review: 'Reviewing' };

function SessionRow({ s, tasks, status, onChange }: {
  s: SessionSummary;
  tasks: Record<string, string>;
  status?: GroupStatus;
  onChange(): void;
}) {
  const [copied, setCopied] = useState(false);
  const act = async (fn: () => Promise<unknown>, question?: string) => {
    if (question && !confirm(question)) return;
    await fn();
    onChange();
  };
  const copy = async () => {
    await navigator.clipboard.writeText(participantLink(s));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <tr>
      <td>
        <div>{s.participantId}</div>
        <div className={`faint ${styles.mono}`}>{s.id}{s.sourceId ? ` · ${s.sourceId}` : ''}</div>
        {s.seq === 1 && status && <div className="faint">{GROUP_STATUS[status]}{s.demo ? ' · demo' : ''}</div>}
        {s.warnings.map((w, i) => <p key={i} className={styles.warn}>⚠ {w}</p>)}
      </td>
      <td>
        {s.taskId ? (
          tasks[s.taskId] ?? s.taskId
        ) : s.groupId ? (
          <span className="faint">Assigned when opened</span>
        ) : (
          <span className="faint">Imported</span>
        )}
        {s.seq != null && <div className="faint">Task {s.seq}{s.seq === 1 ? ' · send this link' : ''}</div>}
        {s.condition && <div className="faint">{conditionLabel(s.condition)}</div>}
      </td>
      <td>{STAGE[s.stage]}</td>
      <td className={styles.num}>{s.draftWords || '—'}</td>
      <td className={styles.num}>{s.stage === 'review' ? <>{s.editCount}<span className="faint"> (+{s.grammarCount} grammar)</span></> : '—'}</td>
      <td className={styles.num}>{s.stage === 'review' ? `${s.decisionCount} / ${s.editCount}` : '—'}</td>
      <td className={styles.num}>{s.eventCount}</td>
      <td>
        <div className={styles.acts}>
          <button className="btn small" onClick={copy}>{copied ? 'Copied' : 'Copy link'}</button>
          <Link className="btn small" to={`/session/${s.id}`}>Open</Link>
          <a className="btn small" href={api.exportUrl('json', s.id)}>JSON</a>
          <a className="btn small" href={api.exportUrl('csv', s.id)}>CSV</a>
          <button className="btn small" onClick={() => act(() => api.regenerateLink(s.id), 'Create a new participant link? The old link stops working.')}>New link</button>
          <button className="btn small" onClick={() => act(() => api.reset(s.id), 'Reset this session? Decisions and events are cleared; task sessions also go back to an empty draft.')}>Reset</button>
          <button className="btn small danger" onClick={() => act(() => api.remove(s.id), 'Delete this session and all its data?')}>Delete</button>
        </div>
      </td>
    </tr>
  );
}

export function AdminPage() {
  const [role, setRole] = useState<'admin' | null | undefined>(undefined);
  const [data, setData] = useState<AdminData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.sessions());
      setRole('admin');
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) setRole(null);
      else setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <p className="center-msg">{error}</p>;
  if (role === undefined) return <p className="center-msg">Loading…</p>;
  if (role === null || !data) return <Login onDone={load} />;

  return (
    <div className={styles.page}>
      <div className={styles.top}>
        <h1>CoWrite · Sessions</h1>
        <a className="btn" href={api.exportUrl('json')}>Export all JSON</a>
        <a className="btn" href={api.exportUrl('csv')}>Export all CSV</a>
        <button className="btn" onClick={async () => { await api.logout(); setRole(null); }}>Log out</button>
      </div>
      <CreateCard data={data} onCreated={load} />
      <BalanceCard data={data} />
      <section className="card">
        <div className={styles.row} style={{ justifyContent: 'space-between' }}>
          <h2>Sessions</h2>
          <button className="btn small" onClick={load}>Refresh</button>
        </div>
        <p className={styles.sub}>“Open” views a session as admin, with the study settings panel.</p>
        {data.sessions.length === 0 ? (
          <p className="faint">No sessions yet.</p>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr><th>Participant</th><th>Task</th><th>Stage</th><th>Draft words</th><th>Edits</th><th>Reviewed</th><th>Events</th><th>Actions</th></tr>
              </thead>
              <tbody>
                {data.sessions.map((s) => (
                  <SessionRow key={s.id} s={s} tasks={data.tasks} status={s.groupId ? data.balance.groups[s.groupId] : undefined} onChange={load} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <ImportCard onImported={load} />
    </div>
  );
}
