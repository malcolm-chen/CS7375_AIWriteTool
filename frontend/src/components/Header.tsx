import type { ReactNode } from 'react';
import { useReview } from '../store/review';
import { S } from '../strings';
import { editOrder } from '../lib/view';
import styles from './Review.module.css';

function Progress() {
  const session = useReview((s) => s.session)!;
  const order = editOrder(session);
  const done = order.filter((id) => session.decisions[id]).length;
  if (!order.length) return null;
  return (
    <span className={styles.progress}>
      <span className={styles.bar} aria-hidden="true"><span style={{ width: `${(100 * done) / order.length}%` }} /></span>
      {S.progress(done, order.length)}
    </span>
  );
}

export function ReviewHeaderExtras() {
  return (
    <>
      <span className={styles.legend}>
        <span>
          <span className={styles.src} aria-hidden="true">abc</span> {S.replaced}
        </span>
        <span>
          <span className={`${styles.mark} ${styles.edit} ${styles.legendMark}`} aria-hidden="true">abc</span> {S.aiEdit}
        </span>
      </span>
      <Progress />
    </>
  );
}

export function Header({ title, step, children, adminOpen, onToggleAdmin }: {
  title: string;
  step?: string;
  children?: ReactNode;
  adminOpen?: boolean;
  onToggleAdmin?: () => void;
}) {
  return (
    <header className={styles.header}>
      <h1>
        {title}
        {step && <span className={styles.step}>{step}</span>}
      </h1>
      {children}
      {onToggleAdmin && (
        <button className="btn" aria-expanded={adminOpen} aria-controls="study-settings" onClick={onToggleAdmin}>
          Study settings
        </button>
      )}
    </header>
  );
}
