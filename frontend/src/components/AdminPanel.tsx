import { Link } from 'react-router-dom';
import { api } from '../api';
import { useReview } from '../store/review';
import type { AnyView } from '../types';
import styles from './Review.module.css';

const STAGE_LABEL = { writing: 'Writing draft', enhancing: 'AI revising', review: 'Reviewing edits' };

/** Right-hand "Study settings" column, rendered only when the backend says role = admin. */
export function AdminPanel({ view }: { view: AnyView }) {
  const eventCount = useReview((s) => s.eventCount);
  const logger = useReview((s) => s.logger);

  const reset = async () => {
    if (!confirm('Reset this session? Decisions and events are cleared; task sessions also go back to an empty draft.')) return;
    logger?.stop();
    await api.reset(view.id);
    location.reload();
  };

  return (
    <aside id="study-settings" className={styles.admin} aria-label="Study settings">
      <h2>Study settings</h2>
      <p className={styles.sub}>Admin only. Your actions here are logged as admin.</p>

      <div className={styles.group}>
        <h3>Session</h3>
        <div className={styles.l}>Participant {view.participantId}</div>
        <div className={styles.d}>{view.task?.title ?? 'Imported revision'} · {STAGE_LABEL[view.stage]}</div>
      </div>

      <div className={styles.group}>
        <h3>Data</h3>
        <p className={styles.d} style={{ margin: '0 0 8px' }}>{eventCount} {eventCount === 1 ? 'event' : 'events'} logged on this page</p>
        <div className={styles.actions}>
          <a className="btn small" href={api.exportUrl('json', view.id)}>Export JSON</a>
          <a className="btn small" href={api.exportUrl('csv', view.id)}>Export CSV</a>
          <button className="btn small danger" onClick={reset}>Reset session</button>
        </div>
      </div>

      <div className={styles.group}>
        <Link to="/admin" className="btn small">← All sessions</Link>
      </div>
    </aside>
  );
}
