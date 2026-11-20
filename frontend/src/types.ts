export interface Task {
  id: string;
  title: string;
  scenario: string;
  assignment: string;
  minWords: number;
  placeholder?: string;
}

export interface Edit {
  id: string;
  original: string;
  revised: string;
  originalRange: [number, number];
  revisedRange: [number, number];
  /** 'grammar' edits are applied in the revision but not highlighted or reviewed. */
  kind: 'grammar' | 'content';
  explanation: { text: string; model?: string | null; promptVersion?: string | null; mode?: string } | null;
}

export type Segment = { kind: 'same'; text: string } | { kind: 'edit'; editId: string };

export interface Decision {
  editId: string;
  type: 'confirmed' | 'corrected';
  modality?: 'voice' | 'text' | null;
  text?: string | null;
  ts: string;
}

export type Role = 'admin' | 'participant';
export type Stage = 'writing' | 'enhancing' | 'review';

/** Where this session sits in the participant's task order; `next` appears once this task is in review. */
export interface Sequence {
  index: number;
  total: number;
  next: { id: string; token: string } | null;
}

interface ViewBase {
  id: string;
  participantId: string;
  task: Task | null;
  role: Role;
  sequence: Sequence | null;
}

export interface WritingView extends ViewBase {
  stage: 'writing' | 'enhancing';
  draft: string;
}

export interface SessionView extends ViewBase {
  stage: 'review';
  original: string;
  revised: string;
  segments: Segment[];
  edits: Record<string, Edit>;
  decisions: Record<string, Decision>;
}

export type AnyView = WritingView | SessionView;

export type EventType =
  | 'session_start' | 'writing_start' | 'paste' | 'view' | 'pin' | 'unpin' | 'confirm' | 'correct_start'
  | 'correct_submit' | 'correct_redo' | 'correct_fail' | 'undo' | 'next_task' | 'session_end';

export interface SessionSummary {
  id: string;
  participantId: string;
  taskId: string | null;
  source: 'task' | 'import';
  stage: Stage;
  sourceId: string | null;
  draftWords: number;
  editCount: number;
  grammarCount: number;
  decisionCount: number;
  eventCount: number;
  warnings: string[];
  token: string;
  createdAt: string;
  groupId: string | null;
  seq: number | null;
}
