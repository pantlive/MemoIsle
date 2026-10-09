export type OfflineDraftMemoType = "idea" | "resource" | "word";

export interface CaptureDraft {
  title: string;
  body: string;
  url: string;
  phonetic: string;
  example: string;
}

export interface CaptureDrafts {
  idea: CaptureDraft;
  resource: CaptureDraft;
  word: CaptureDraft;
}

export interface EditorDraft {
  title: string;
  body: string;
  phonetic: string;
  example: string;
  baseVersion: number;
  updatedAt: string;
}

interface DraftState {
  capture: CaptureDrafts;
  editors: Record<string, EditorDraft>;
}

const STORAGE_PREFIX = "memoisle_offline_drafts_v1:";

function emptyCaptureDraft(): CaptureDraft {
  return {
    title: "",
    body: "",
    url: "",
    phonetic: "",
    example: "",
  };
}

function emptyDraftState(): DraftState {
  return {
    capture: {
      idea: emptyCaptureDraft(),
      resource: emptyCaptureDraft(),
      word: emptyCaptureDraft(),
    },
    editors: {},
  };
}

function getStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    // 隐私模式或浏览器禁用存储时仍保留正常的在线编辑能力。
    return null;
  }
}

function storageKey(userId: string): string {
  return `${STORAGE_PREFIX}${userId}`;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function textValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function readCaptureDraft(value: unknown): CaptureDraft {
  const record = asRecord(value);
  return {
    title: textValue(record?.title),
    body: textValue(record?.body),
    url: textValue(record?.url),
    phonetic: textValue(record?.phonetic),
    example: textValue(record?.example),
  };
}

function readState(userId: string): DraftState {
  const storage = getStorage();
  if (!storage) {
    return emptyDraftState();
  }
  try {
    const parsed = JSON.parse(storage.getItem(storageKey(userId)) ?? "null") as unknown;
    const record = asRecord(parsed);
    const capture = asRecord(record?.capture);
    const editors = asRecord(record?.editors);
    const state = emptyDraftState();
    if (capture) {
      state.capture.idea = readCaptureDraft(capture.idea);
      state.capture.resource = readCaptureDraft(capture.resource);
      state.capture.word = readCaptureDraft(capture.word);
    }
    if (editors) {
      for (const [memoId, value] of Object.entries(editors)) {
        const editor = asRecord(value);
        if (
          editor &&
          typeof editor.baseVersion === "number" &&
          Number.isFinite(editor.baseVersion) &&
          editor.baseVersion >= 1
        ) {
          state.editors[memoId] = {
            title: textValue(editor.title),
            body: textValue(editor.body),
            phonetic: textValue(editor.phonetic),
            example: textValue(editor.example),
            baseVersion: Math.floor(editor.baseVersion),
            updatedAt: textValue(editor.updatedAt),
          };
        }
      }
    }
    return state;
  } catch {
    // 损坏或过期的草稿不应阻断应用启动。
    return emptyDraftState();
  }
}

function writeState(userId: string, state: DraftState): void {
  const storage = getStorage();
  if (!storage) {
    return;
  }
  try {
    storage.setItem(storageKey(userId), JSON.stringify(state));
  } catch {
    // localStorage 满或被禁用时静默降级，不影响服务端保存。
  }
}

export function loadCaptureDrafts(userId: string): CaptureDrafts {
  return readState(userId).capture;
}

export function saveCaptureDraft(
  userId: string,
  type: OfflineDraftMemoType,
  draft: CaptureDraft,
): void {
  const state = readState(userId);
  state.capture[type] = draft;
  writeState(userId, state);
}

export function clearCaptureDraft(
  userId: string,
  type: OfflineDraftMemoType,
): void {
  const state = readState(userId);
  state.capture[type] = emptyCaptureDraft();
  writeState(userId, state);
}

export function loadEditorDraft(userId: string, memoId: string): EditorDraft | null {
  return readState(userId).editors[memoId] ?? null;
}

export function saveEditorDraft(
  userId: string,
  memoId: string,
  draft: EditorDraft,
): void {
  const state = readState(userId);
  state.editors[memoId] = draft;
  writeState(userId, state);
}

export function clearEditorDraft(userId: string, memoId: string): void {
  const state = readState(userId);
  delete state.editors[memoId];
  writeState(userId, state);
}
