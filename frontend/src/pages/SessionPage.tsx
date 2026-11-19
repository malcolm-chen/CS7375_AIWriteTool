import { useCallback, useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../api';
import { EventLogger } from '../lib/logger';
import { useReview } from '../store/review';
import { S } from '../strings';
import type { AnyView } from '../types';
import { Header, ReviewHeaderExtras } from '../components/Header';
import { ComparePanes } from '../components/ComparePanes';
import { GuideBar } from '../components/GuideBar';
import { AdminPanel } from '../components/AdminPanel';
import { TaskReminder } from '../components/TaskCard';
import { WritingStage } from '../components/WritingStage';
import styles from '../components/Review.module.css';

export function SessionPage() {
  const { id = '' } = useParams();
  const [params] = useSearchParams();
  const token = params.get('t');
  const [view, setView] = useState<AnyView | null>(null);
  const [logger, setLogger] = useState<EventLogger | null>(null);
  const reviewSession = useReview((s) => s.session);
  const [error, setError] = useState<string | null>(null);
  const [adminOpen, setAdminOpen] = useState(true);

  useEffect(() => {
    let lg: EventLogger | null = null;
    let cancelled = false;
    api
      .session(id, token)
      .then((v) => {
        if (cancelled) return;
        lg = new EventLogger(id, token, (n) => useReview.setState({ eventCount: n }));
        lg.start();
        lg.log('session_start', undefined, { stage: v.stage, userAgent: navigator.userAgent });
        useReview.setState({ logger: lg });
        setLogger(lg);
        setView(v);
      })
      .catch((e) =>
        setError(
          e instanceof ApiError && e.status === 403
            ? 'This link is not valid. Ask the researcher for a new one.'
            : e instanceof ApiError && e.status === 404
              ? 'Session not found.'
              : 'Could not load the session.',
        ),
      );
    return () => {
      cancelled = true;
      lg?.stop();
      useReview.setState({ session: null, logger: null });
    };
  }, [id, token]);

  // Hand the review data to the store once, when the session reaches review.
  useEffect(() => {
    if (view?.stage === 'review' && logger && useReview.getState().session?.id !== view.id) {
      useReview.getState().init(view, token, logger);
    }
  }, [view, logger, token]);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') useReview.getState().close('escape');
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  const onChange = useCallback((v: AnyView) => setView(v), []);

  if (error) return <p className="center-msg">{error}</p>;
  if (!view) return <p className="center-msg">Loading…</p>;

  const isAdmin = view.role === 'admin';
  const showAdmin = isAdmin && adminOpen;
  const toggleAdmin = isAdmin ? () => setAdminOpen((o) => !o) : undefined;

  if (view.stage !== 'review') {
    return (
      <>
        <Header title={S.writeTitle} step={view.task ? S.stepWrite : undefined} adminOpen={showAdmin} onToggleAdmin={toggleAdmin} />
        <div className={`${styles.layout} ${showAdmin ? styles.adminOpen : ''}`}>
          <main>
            {view.task ? (
              <WritingStage view={view} token={token} logger={logger} onChange={onChange} />
            ) : (
              <p className="center-msg">This session has no writing task.</p>
            )}
          </main>
          {showAdmin && <AdminPanel view={view} />}
        </div>
      </>
    );
  }

  if (!reviewSession || reviewSession.id !== id) return <p className="center-msg">Loading…</p>;
  return (
    <>
      <Header title={S.title} step={view.task ? S.stepReview : undefined} adminOpen={showAdmin} onToggleAdmin={toggleAdmin}>
        <ReviewHeaderExtras />
      </Header>
      <div className={`${styles.layout} ${showAdmin ? styles.adminOpen : ''}`}>
        <main>
          {view.task && <TaskReminder task={view.task} />}
          <GuideBar />
          <ComparePanes />
          <p className={styles.footnote}>{S.grammarNote}</p>
        </main>
        {showAdmin && <AdminPanel view={view} />}
      </div>
    </>
  );
}
