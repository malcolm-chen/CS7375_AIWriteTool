import { create } from 'zustand';
import { api } from '../api';
import type { EventLogger } from '../lib/logger';
import type { Decision, EventType, SessionView } from '../types';

interface ReviewState {
  session: SessionView | null;
  token: string | null;
  logger: EventLogger | null;
  eventCount: number;
  active: string | null;
  locked: string | null;
  textOpen: boolean;
  recording: boolean;
  /** Transcript awaiting "Confirm correction" / "Record again". */
  pending: { editId: string; text: string } | null;
  error: string | null;

  init(session: SessionView, token: string | null, logger: EventLogger): void;
  replaceSession(session: SessionView): void;
  log(type: EventType, editId?: string, payload?: Record<string, unknown>): void;
  preview(id: string): void;
  togglePin(id: string): void;
  /** Jump to an edit (guide bar / "Next edit"), pinning it so the card stays put. */
  goTo(id: string, via: string): void;
  /** Pointer left the active edit and its card: close the card soon unless it is pinned or in use. */
  hoverOut(): void;
  hoverIn(): void;
  close(via: string): void;
  openText(): void;
  setRecording(on: boolean): void;
  setPending(p: ReviewState['pending']): void;
  decide(d: Omit<Decision, 'ts'>): Promise<boolean>;
  undo(id: string): Promise<void>;
  setError(msg: string | null): void;
}

const CLOSE_DELAY_MS = 350;
let closeTimer: number | undefined;

export const useReview = create<ReviewState>((set, get) => ({
  session: null,
  token: null,
  logger: null,
  eventCount: 0,
  active: null,
  locked: null,
  textOpen: false,
  recording: false,
  pending: null,
  error: null,

  init(session, token, logger) {
    set({ session, token, logger, active: null, locked: null, textOpen: false, recording: false, pending: null, error: null });
  },

  replaceSession(session) {
    set({ session });
  },

  log(type, editId, payload) {
    get().logger?.log(type, editId, payload);
  },

  preview(id) {
    const { recording, locked, active } = get();
    if (recording || locked || active === id) return;
    set({ active: id, textOpen: false, error: null });
    get().log('view', id);
  },

  togglePin(id) {
    if (get().recording) return;
    if (get().locked === id) {
      set({ locked: null });
      get().log('unpin', id);
    } else {
      const changed = get().active !== id;
      set({ locked: id, active: id, textOpen: changed ? false : get().textOpen, error: null });
      if (changed) get().log('view', id);
      get().log('pin', id);
    }
  },

  goTo(id, via) {
    if (get().recording) return;
    set({ active: id, locked: id, textOpen: false, error: null });
    get().log('view', id, { via });
    get().log('pin', id, { via });
  },

  hoverOut() {
    window.clearTimeout(closeTimer);
    closeTimer = window.setTimeout(() => {
      const { locked, textOpen, recording, pending } = get();
      if (!locked && !textOpen && !recording && !pending) set({ active: null });
    }, CLOSE_DELAY_MS);
  },

  hoverIn() {
    window.clearTimeout(closeTimer);
  },

  close(via) {
    const { active, locked, recording } = get();
    if (recording || !active) return;
    set({ active: null, locked: null, textOpen: false });
    if (locked) get().log('unpin', locked, { via });
  },

  openText() {
    const id = get().active;
    if (!id || get().recording) return;
    set({ textOpen: true, pending: null }); // typing replaces an unconfirmed voice transcript
    get().log('correct_start', id, { modality: 'text' });
  },

  setRecording(recording) {
    set({ recording });
  },

  setPending(pending) {
    set({ pending });
  },

  async decide(d) {
    const { session, token } = get();
    if (!session) return false;
    const decision: Decision = { ...d, ts: new Date().toISOString() };
    const before = session.decisions;
    const wasPinned = get().locked === d.editId;
    set({
      session: { ...session, decisions: { ...before, [d.editId]: decision } },
      // Unpin after deciding so hovering the next edit works right away.
      locked: wasPinned ? null : get().locked,
      pending: null,
      textOpen: false,
      error: null,
    });
    get().log(d.type === 'confirmed' ? 'confirm' : 'correct_submit', d.editId,
      d.type === 'corrected' ? { modality: d.modality, text: d.text } : undefined);
    if (wasPinned) get().log('unpin', d.editId, { via: 'decision' });
    try {
      await api.decide(session.id, token, decision);
      return true;
    } catch {
      const s = get().session!;
      set({ session: { ...s, decisions: before }, error: 'save' });
      return false;
    }
  },

  async undo(id) {
    const { session, token } = get();
    if (!session) return;
    const before = session.decisions;
    const rest = { ...before };
    delete rest[id];
    set({ session: { ...session, decisions: rest }, error: null });
    get().log('undo', id, { previous: before[id]?.type });
    try {
      await api.undo(session.id, token, id);
    } catch {
      set({ session: { ...get().session!, decisions: before }, error: 'save' });
    }
  },

  setError(error) {
    set({ error });
  },
}));
