import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useReview } from '../store/review';
import { S } from '../strings';
import { isReviewable, markKind, nextUndecided, revisedText, splitWs } from '../lib/view';
import { DetailPanel } from './DetailPanel';
import styles from './Review.module.css';

/** Hover must rest this long before switching edits, so moving to the card doesn't hijack it. */
const HOVER_INTENT_MS = 150;

/** The edit the guide outlines: the next undecided one, unless the active edit still needs a decision. */
export function useGuideId(): string | null {
  const session = useReview((s) => s.session)!;
  const active = useReview((s) => s.active);
  if (active && !session.decisions[active]) return null;
  return nextUndecided(session, active);
}

/** Original text the AI replaced or removed, in the "removed" color; mirrors the decision state of its edit. */
function SourceSpan({ text, lit, decision }: { text: string; lit: boolean; decision?: 'confirmed' | 'corrected' }) {
  const [lead, core, trail] = splitWs(text);
  if (!core) return <>{text}</>;
  const cls = [
    styles.src,
    lit && styles.lit,
    decision === 'confirmed' && styles.done,
    decision === 'corrected' && styles.kept,
  ].filter(Boolean).join(' ');
  return (
    <>
      {lead}
      <span className={cls}>{core}</span>
      {trail}
    </>
  );
}

function OriginalPane() {
  const session = useReview((s) => s.session)!;
  const active = useReview((s) => s.active);
  return (
    <section className={styles.pane}>
      <h2>{S.original}</h2>
      <p className={styles.text}>
        {session.segments.map((seg, i) =>
          seg.kind === 'same' ? (
            seg.text
          ) : !isReviewable(session, seg.editId) ? (
            session.edits[seg.editId].original
          ) : (
            <SourceSpan
              key={i}
              text={session.edits[seg.editId].original}
              lit={active === seg.editId}
              decision={session.decisions[seg.editId]?.type}
            />
          ),
        )}
      </p>
    </section>
  );
}

function EditMark({ editId, guided }: { editId: string; guided: boolean }) {
  const session = useReview((s) => s.session)!;
  const active = useReview((s) => s.active);
  const locked = useReview((s) => s.locked);
  const preview = useReview((s) => s.preview);
  const togglePin = useReview((s) => s.togglePin);
  const timer = useRef<number>();
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const [lead, text, trail] = splitWs(revisedText(session, editId));
  const cls = [
    styles.mark,
    styles[markKind(session, editId)],
    active === editId && styles.active,
    guided && styles.next,
    session.decisions[editId]?.type === 'confirmed' && styles.done,
    !text && styles.empty,
  ].filter(Boolean).join(' ');

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      togglePin(editId);
    }
  };

  return (
    <>
    {lead}
    <span
      className={cls}
      data-edit-id={editId}
      role="button"
      tabIndex={0}
      aria-pressed={locked === editId}
      aria-label={text ? undefined : `${S.removed} ${session.edits[editId].original}`}
      onMouseEnter={() => {
        useReview.getState().hoverIn();
        if (!useReview.getState().active) preview(editId);
        else timer.current = window.setTimeout(() => preview(editId), HOVER_INTENT_MS);
      }}
      onMouseLeave={() => {
        window.clearTimeout(timer.current);
        useReview.getState().hoverOut();
      }}
      onFocus={() => preview(editId)}
      onClick={() => {
        window.clearTimeout(timer.current);
        togglePin(editId);
      }}
      onKeyDown={onKeyDown}
    >
      {text || '​'}
    </span>
    {trail}
    </>
  );
}

interface CardPos {
  top: number;
  left: number;
  width: number;
  arrow: number;
}

function RevisedPane() {
  const session = useReview((s) => s.session)!;
  const active = useReview((s) => s.active);
  const guideId = useGuideId();
  const wrapRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<CardPos | null>(null);

  // Place the card just below the last line box of the active edit.
  useLayoutEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap || !active) {
      setPos(null);
      return;
    }
    const place = () => {
      const mark = wrap.querySelector<HTMLElement>(`[data-edit-id="${active}"]`);
      if (!mark) return setPos(null);
      const w = wrap.getBoundingClientRect();
      const rects = mark.getClientRects();
      const r = rects[rects.length - 1] ?? mark.getBoundingClientRect();
      const width = Math.min(440, w.width);
      const markLeft = r.left - w.left;
      const left = Math.max(0, Math.min(markLeft - 16, w.width - width));
      const arrow = Math.max(12, Math.min(markLeft - left + Math.min(r.width / 2, 20) - 6, width - 24));
      setPos({ top: r.bottom - w.top + 10, left, width, arrow });
    };
    place();
    const ro = new ResizeObserver(place);
    ro.observe(wrap);
    document.fonts?.ready.then(place);
    return () => ro.disconnect();
  }, [active, session.decisions]);

  return (
    <section className={`${styles.pane} ${styles.revisedPane}`}>
      <h2>{S.revised}</h2>
      <div className={styles.anchor} ref={wrapRef}>
        <p className={styles.text}>
          {session.segments.map((seg, i) =>
            seg.kind === 'same' ? (
              seg.text
            ) : !isReviewable(session, seg.editId) ? (
              session.edits[seg.editId].revised
            ) : (
              <EditMark key={i} editId={seg.editId} guided={seg.editId === guideId} />
            ),
          )}
        </p>
        {active && pos && <DetailPanel pos={pos} />}
      </div>
    </section>
  );
}

export function ComparePanes() {
  return (
    <div className={styles.panes}>
      <OriginalPane />
      <RevisedPane />
    </div>
  );
}
