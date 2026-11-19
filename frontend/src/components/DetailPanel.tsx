import type { CSSProperties } from 'react';
import { useReview } from '../store/review';
import { S } from '../strings';
import { nextUndecided } from '../lib/view';
import type { Decision, Edit } from '../types';
import { Actions, IconCheck } from './Actions';
import styles from './Review.module.css';

/** What the AI removed (red, struck through) and what it put in (same highlight as the revised text). */
function DiffLine({ edit: e }: { edit: Edit }) {
  const removed = e.original.trim();
  const added = e.revised.trim();
  return (
    <div className={styles.diff}>
      {removed && (
        <span className={styles.del}>
          <span className="sr-only">{S.removedLabel}: </span>
          {removed}
        </span>
      )}
      {removed && added && <span className={styles.arrow} aria-hidden="true">→</span>}
      {added && (
        <span className={styles.ins}>
          <span className="sr-only">{S.addedLabel}: </span>
          {added}
        </span>
      )}
      {!removed && <span className={styles.diffNote}>{S.addedNote}</span>}
      {!added && <span className={styles.diffNote}>{S.removedNote}</span>}
    </div>
  );
}

function NextButton({ from }: { from: string }) {
  const session = useReview((s) => s.session)!;
  const goTo = useReview((s) => s.goTo);
  const next = nextUndecided(session, from);
  if (!next) return null;
  return <button className="btn primary" onClick={() => goTo(next, 'card_next')}>{S.next} →</button>;
}

function Result({ edit, decision }: { edit: Edit; decision: Decision }) {
  const undo = useReview((s) => s.undo);
  if (decision.type === 'confirmed') {
    return (
      <div className={styles.actions}>
        <span className="ok"><IconCheck /> {S.confirmed}</span>
        <button className="btn" onClick={() => undo(edit.id)}>{S.undo}</button>
        <span className={styles.spacer} />
        <NextButton from={edit.id} />
      </div>
    );
  }
  return (
    <>
      <div className={styles.result}>
        <p className="muted">{decision.modality === 'voice' ? S.voiceLabel : S.textLabel}</p>
        <p>“{decision.text}”</p>
        <p className="muted">
          {S.revertedTo} <span style={{ color: 'var(--ink)' }}>{edit.original || S.removed}</span>
        </p>
      </div>
      <div className={styles.actions} style={{ marginTop: 10 }}>
        <button className="btn" onClick={() => undo(edit.id)}>{S.undo}</button>
        <span className={styles.spacer} />
        <NextButton from={edit.id} />
      </div>
    </>
  );
}

/** Details and actions for the active edit, floating directly under it in the revised pane. */
export function DetailPanel({ pos }: { pos: { top: number; left: number; width: number; arrow: number } }) {
  const session = useReview((s) => s.session)!;
  const active = useReview((s) => s.active)!;
  const locked = useReview((s) => s.locked);
  const error = useReview((s) => s.error);
  const edit = session.edits[active];
  const decision = session.decisions[edit.id];
  const style = { top: pos.top, left: pos.left, width: pos.width, '--arrow': `${pos.arrow}px` } as CSSProperties;

  return (
    <div
      className={styles.card}
      style={style}
      aria-live="polite"
      role="group"
      aria-label="Edit details"
      onMouseEnter={() => useReview.getState().hoverIn()}
      onMouseLeave={() => useReview.getState().hoverOut()}
    >
      {locked === edit.id && <p className={styles.lockhint}>{S.pinned}</p>}
      <DiffLine edit={edit} />
      <p className={styles.reason}>{edit.explanation?.text ?? S.noReason}</p>
      {decision ? <Result edit={edit} decision={decision} /> : <Actions key={edit.id} editId={edit.id} />}
      {error === 'save' && <p className="err" role="alert">{S.saveFailed}</p>}
    </div>
  );
}
