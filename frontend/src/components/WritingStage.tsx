import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { EventLogger } from '../lib/logger';
import { S } from '../strings';
import type { AnyView, WritingView } from '../types';
import { TaskCard } from './TaskCard';
import styles from './Writing.module.css';

const SAVE_DELAY_MS = 1500;
const POLL_MS = 3000;
const countWords = (t: string) => (t.trim() ? t.trim().split(/\s+/).length : 0);

type SaveState = 'idle' | 'saving' | 'saved' | 'error';

/** Step 1: the participant writes their own draft, then asks the AI to revise it. */
export function WritingStage({ view, token, logger, onChange }: {
  view: WritingView;
  token: string | null;
  logger: EventLogger | null;
  onChange(v: AnyView): void;
}) {
  const task = view.task!;
  const [text, setText] = useState(view.draft);
  const [save, setSave] = useState<SaveState>('idle');
  const [busy, setBusy] = useState(view.stage === 'enhancing');
  const [error, setError] = useState<string | null>(null);
  const started = useRef(view.draft.length > 0);
  const saveTimer = useRef<number>();
  const latest = useRef(text);
  latest.current = text;

  const words = countWords(text);
  const canSubmit = words >= task.minWords && !busy;

  const saveNow = async () => {
    window.clearTimeout(saveTimer.current);
    setSave('saving');
    try {
      await api.saveDraft(view.id, token, latest.current);
      setSave('saved');
    } catch {
      setSave('error');
      saveTimer.current = window.setTimeout(saveNow, SAVE_DELAY_MS * 2);
    }
  };

  useEffect(() => () => window.clearTimeout(saveTimer.current), []);

  // After a reload mid-revision, wait for the server to finish.
  useEffect(() => {
    if (view.stage !== 'enhancing') return;
    const timer = window.setInterval(async () => {
      try {
        const v = await api.session(view.id, token);
        if (v.stage !== 'enhancing') onChange(v);
      } catch {
        /* keep polling */
      }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [view.stage, view.id, token, onChange]);

  const submit = async () => {
    window.clearTimeout(saveTimer.current);
    setBusy(true);
    setError(null);
    logger?.flush();
    try {
      onChange(await api.enhance(view.id, token, text));
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className={styles.layout}>
      <TaskCard task={task} />
      <section className={styles.editor}>
        {busy ? (
          <div className={styles.waiting} role="status">
            <span className={styles.spinner} aria-hidden="true" />
            <p className={styles.waitTitle}>{S.enhancing}</p>
            <p className="muted">{S.enhancingNote}</p>
          </div>
        ) : (
          <>
            <label htmlFor="draft" className={styles.label}>{S.draftLabel}</label>
            <textarea
              id="draft"
              className={styles.draft}
              value={text}
              placeholder={task.placeholder}
              spellCheck={false}
              autoCorrect="off"
              autoCapitalize="off"
              autoComplete="off"
              onChange={(e) => {
                if (!started.current) {
                  started.current = true;
                  logger?.log('writing_start');
                }
                setText(e.target.value);
                setSave('idle');
                window.clearTimeout(saveTimer.current);
                saveTimer.current = window.setTimeout(saveNow, SAVE_DELAY_MS);
              }}
              onPaste={(e) => logger?.log('paste', undefined, { chars: e.clipboardData.getData('text').length })}
            />
            <div className={styles.meta}>
              <span>
                {S.words(words)}
                {words < task.minWords && <span className="faint"> · {S.minWords(task.minWords)}</span>}
              </span>
              <span className="faint" aria-live="polite">
                {save === 'saving' ? S.saving : save === 'saved' ? S.saved : save === 'error' ? S.saveError : ''}
              </span>
            </div>
            <div className={styles.submitRow}>
              <button className="btn primary" disabled={!canSubmit} onClick={submit}>{S.enhance} →</button>
              <p className="faint">{S.enhanceNote}</p>
            </div>
            {error && (
              <p className="err" role="alert">
                {S.enhanceFailed} {error}
              </p>
            )}
          </>
        )}
      </section>
    </div>
  );
}
