import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { useReview } from '../store/review';
import { S } from '../strings';
import { speechSupported, startRecognition } from '../lib/speech';
import styles from './Review.module.css';

export const IconCheck = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12l5 5L20 7" />
  </svg>
);

const IconMic = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
  </svg>
);

function VoiceButton({ editId, onLive, onFail }: { editId: string; onLive(t: string): void; onFail(msg: string | null): void }) {
  const recording = useReview((s) => s.recording);
  const { setRecording, setPending, log } = useReview.getState();
  const stopRef = useRef<(() => void) | null>(null);

  const start = () => {
    if (useReview.getState().recording) return;
    setPending(null);
    onLive('');
    onFail(null);
    const stop = startRecognition({
      onText: onLive,
      onEnd(text, error) {
        stopRef.current = null;
        setRecording(false);
        if (!text) {
          onFail(error === 'not-allowed' || error === 'service-not-allowed' ? S.micDenied : S.nothingHeard);
          log('correct_fail', editId, { modality: 'voice', error: error ?? 'empty' });
        } else {
          setPending({ editId, text });
        }
      },
    });
    if (!stop) return;
    stopRef.current = stop;
    setRecording(true);
    log('correct_start', editId, { modality: 'voice' });
  };
  const stop = () => stopRef.current?.();

  useEffect(() => () => stopRef.current?.(), []);

  const onPointerDown = (e: PointerEvent) => {
    e.preventDefault();
    start();
    document.addEventListener('pointerup', stop, { once: true });
    document.addEventListener('pointercancel', stop, { once: true });
  };
  const isTalkKey = (e: KeyboardEvent) => e.key === ' ' || e.key === 'Enter';

  return (
    <>
      <button
        className={`${styles.mic} ${recording ? styles.rec : ''}`}
        aria-label={S.hold}
        aria-pressed={recording}
        onPointerDown={onPointerDown}
        onKeyDown={(e) => {
          if (isTalkKey(e)) {
            e.preventDefault();
            if (!e.repeat) start();
          }
        }}
        onKeyUp={(e) => {
          if (isTalkKey(e)) {
            e.preventDefault();
            stop();
          }
        }}
        onContextMenu={(e) => e.preventDefault()}
      >
        {recording ? (
          <span className={styles.bars} aria-hidden="true"><i /><i /><i /></span>
        ) : (
          <IconMic />
        )}
      </button>
      <span className={styles.hint}>{recording ? S.listening : S.hold}</span>
    </>
  );
}

function TextCorrection({ editId }: { editId: string }) {
  const decide = useReview((s) => s.decide);
  const [value, setValue] = useState('');
  const [error, setError] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => ref.current?.focus(), []);

  const submit = () => {
    const text = value.trim();
    if (!text) {
      setError(true);
      ref.current?.focus();
      return;
    }
    decide({ editId, type: 'corrected', modality: 'text', text });
  };

  return (
    <div className={styles.mt}>
      <textarea
        ref={ref}
        value={value}
        placeholder={S.textPlaceholder}
        aria-label={S.textOpen}
        aria-invalid={error}
        aria-describedby={error ? 'txt-err' : undefined}
        onChange={(e) => {
          setValue(e.target.value);
          setError(false);
        }}
      />
      {error && <p className="err" id="txt-err" role="alert">{S.empty}</p>}
      <div className={styles.actions} style={{ marginTop: 8 }}>
        <button className="btn primary" onClick={submit}>{S.submit}</button>
      </div>
    </div>
  );
}

/** Undecided edit: confirm, or correct by voice (push-to-talk) or text. */
export function Actions({ editId }: { editId: string }) {
  const decide = useReview((s) => s.decide);
  const pending = useReview((s) => s.pending);
  const textOpen = useReview((s) => s.textOpen);
  const openText = useReview((s) => s.openText);
  const [live, setLive] = useState('');
  const [fail, setFail] = useState<string | null>(null);
  const myPending = pending?.editId === editId ? pending : null;

  return (
    <div>
      <div className={styles.actions}>
        <button className="btn" onClick={() => decide({ editId, type: 'confirmed' })}>
          <IconCheck /> {S.ok}
        </button>
        {speechSupported ? (
          <VoiceButton editId={editId} onLive={setLive} onFail={setFail} />
        ) : (
          !textOpen && <button className="btn" onClick={openText}>{S.textOpen}</button>
        )}
      </div>
      {!speechSupported && <p className={styles.note}>{S.noSpeech}</p>}

      {myPending ? (
        <div className={`${styles.result} ${styles.mt}`}>
          <p className="muted">{S.voiceLabel}</p>
          <p>“{myPending.text}”</p>
          <div className={styles.actions} style={{ marginTop: 10 }}>
            <button className="btn primary" onClick={() => decide({ editId, type: 'corrected', modality: 'voice', text: myPending.text })}>
              {S.confirm}
            </button>
            <button
              className="btn"
              onClick={() => {
                useReview.getState().setPending(null);
                setLive('');
                useReview.getState().log('correct_redo', editId);
              }}
            >
              {S.redo}
            </button>
          </div>
        </div>
      ) : textOpen ? (
        <TextCorrection editId={editId} />
      ) : fail ? (
        <p className="err" role="alert">{fail}</p>
      ) : (
        speechSupported && <p className={styles.live}>{live}</p>
      )}
    </div>
  );
}
