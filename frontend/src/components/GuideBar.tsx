import { useNavigate } from 'react-router-dom';
import { useReview } from '../store/review';
import { S } from '../strings';
import { editOrder, nextUndecided } from '../lib/view';
import styles from './Review.module.css';

/** One-line instruction above the panes, plus a button that jumps to the next edit to review. */
export function GuideBar() {
  const session = useReview((s) => s.session)!;
  const active = useReview((s) => s.active);
  const goTo = useReview((s) => s.goTo);
  const navigate = useNavigate();
  const order = editOrder(session);
  const next = nextUndecided(session, active);
  const seq = session.sequence;
  const nextTask = seq?.next ?? null;
  const lastTask = !!seq && seq.total > 1 && seq.index === seq.total;

  const continueButton = nextTask && (
    <button
      className="btn small primary"
      onClick={() => {
        useReview.getState().log('next_task', undefined, { to: nextTask.id });
        navigate(`/session/${nextTask.id}?t=${encodeURIComponent(nextTask.token)}`);
      }}
    >
      {S.nextTask} →
    </button>
  );

  if (!order.length) {
    return (
      <div className={styles.guide}>
        <span className={`${styles.dot} ${styles.doneDot}`} aria-hidden="true" />
        <p>{nextTask ? S.guideNoEditsNext : lastTask ? `${S.guideNoEdits} ${S.studyDone}` : S.guideNoEdits}</p>
        {continueButton}
      </div>
    );
  }

  let text: string;
  if (!next) text = nextTask ? S.guideAllDoneNext(order.length) : lastTask ? S.studyDone : S.guideAllDone(order.length);
  else if (!active) text = Object.keys(session.decisions).length ? S.guideDecided : S.guideStart;
  else if (!session.decisions[active]) text = S.guideWorking(order.indexOf(active) + 1, order.length);
  else text = S.guideDecided;

  const target = next && next !== active ? next : null;
  const started = !!active || Object.keys(session.decisions).length > 0;
  return (
    <div className={styles.guide}>
      <span className={`${styles.dot} ${next ? '' : styles.doneDot}`} aria-hidden="true" />
      <p aria-live="polite">{text}</p>
      {target && (
        <button className="btn small" onClick={() => goTo(target, started ? 'guide_next' : 'guide_start')}>
          {started ? S.next : S.start} →
        </button>
      )}
      {!next && continueButton}
    </div>
  );
}
