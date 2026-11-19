import type { SessionView } from '../types';

export type MarkKind = 'edit' | 'fixed';

/** Grammar-only edits are applied silently; everything else is highlighted for review. */
export function isReviewable(s: SessionView, editId: string): boolean {
  return s.edits[editId]?.kind !== 'grammar';
}

export function markKind(s: SessionView, editId: string): MarkKind {
  return s.decisions[editId]?.type === 'corrected' ? 'fixed' : 'edit';
}

/** Text shown in the revised pane: corrected edits revert to the original. */
export function revisedText(s: SessionView, editId: string): string {
  const e = s.edits[editId];
  return s.decisions[editId]?.type === 'corrected' ? e.original : e.revised;
}

/** Reviewable edits in reading order. */
export function editOrder(s: SessionView): string[] {
  return s.segments.flatMap((seg) => (seg.kind === 'edit' && isReviewable(s, seg.editId) ? [seg.editId] : []));
}

/** First undecided edit after `from` in reading order, wrapping around; null when all are decided. */
export function nextUndecided(s: SessionView, from: string | null): string | null {
  const order = editOrder(s);
  const start = from ? order.indexOf(from) + 1 : 0;
  for (let i = 0; i < order.length; i++) {
    const id = order[(start + i) % order.length];
    if (!s.decisions[id]) return id;
  }
  return null;
}

/** [leading whitespace, core, trailing whitespace]: highlights wrap only the core. */
export function splitWs(text: string): [string, string, string] {
  const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(text)!;
  return [m[1], m[2], m[3]];
}
