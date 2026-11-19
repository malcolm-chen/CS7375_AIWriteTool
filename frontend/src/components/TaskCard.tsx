import { S } from '../strings';
import type { Task } from '../types';
import styles from './Writing.module.css';

export function TaskCard({ task }: { task: Task }) {
  return (
    <section className={styles.task} aria-labelledby="task-title">
      <p className={styles.eyebrow}>{S.yourTask}</p>
      <h2 id="task-title">{task.title}</h2>
      <h3>{S.scenario}</h3>
      <p>{task.scenario}</p>
      <h3>{S.assignment}</h3>
      <p>{task.assignment}</p>
      <p className={styles.own}>{S.ownWords}</p>
    </section>
  );
}

/** Collapsed task reminder shown on the review step. */
export function TaskReminder({ task }: { task: Task }) {
  return (
    <details className={styles.reminder}>
      <summary>
        <span className={styles.eyebrow}>{S.yourTask}</span> {task.title}
      </summary>
      <p>{task.scenario}</p>
      <p>{task.assignment}</p>
    </details>
  );
}
