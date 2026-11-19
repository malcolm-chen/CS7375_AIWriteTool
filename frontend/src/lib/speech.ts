// Minimal typings for the Web Speech API (not in lib.dom).
interface RecognitionResultList {
  length: number;
  [i: number]: { 0: { transcript: string } };
}
export interface Recognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: { results: RecognitionResultList }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}
type RecognitionCtor = new () => Recognition;

const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
export const SpeechRecognitionImpl: RecognitionCtor | undefined = w.SpeechRecognition ?? w.webkitSpeechRecognition;
export const speechSupported = !!SpeechRecognitionImpl;
export const SPEECH_LANG = 'en-US';

export interface RecordingHandlers {
  onText(text: string): void;
  onEnd(text: string, error: string | null): void;
}

/** Starts push-to-talk recognition; call the returned function to stop. */
export function startRecognition(h: RecordingHandlers): (() => void) | null {
  if (!SpeechRecognitionImpl) return null;
  const rec = new SpeechRecognitionImpl();
  rec.lang = SPEECH_LANG;
  rec.interimResults = true;
  rec.continuous = true;
  let text = '';
  let error: string | null = null;
  rec.onresult = (e) => {
    let s = '';
    for (let i = 0; i < e.results.length; i++) s += e.results[i][0].transcript;
    text = s;
    h.onText(s);
  };
  rec.onerror = (e) => {
    error = e.error;
  };
  rec.onend = () => h.onEnd(text.trim(), error);
  try {
    rec.start();
  } catch {
    return null;
  }
  return () => {
    try {
      rec.stop();
    } catch {
      /* already stopped */
    }
  };
}
