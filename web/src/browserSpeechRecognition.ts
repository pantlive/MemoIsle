/** 浏览器原生语音识别的最小类型封装。 */

interface BrowserSpeechRecognitionAlternative {
  transcript: string;
  confidence: number;
}

interface BrowserSpeechRecognitionResult {
  readonly isFinal: boolean;
  readonly length: number;
  [index: number]: BrowserSpeechRecognitionAlternative;
}

interface BrowserSpeechRecognitionResultList {
  readonly length: number;
  [index: number]: BrowserSpeechRecognitionResult;
}

export interface BrowserSpeechRecognitionResultEvent extends Event {
  readonly resultIndex: number;
  readonly results: BrowserSpeechRecognitionResultList;
}

export interface BrowserSpeechRecognitionErrorEvent extends Event {
  readonly error: string;
  readonly message: string;
}

export interface BrowserSpeechRecognitionController extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onend: (() => void) | null;
  onerror: ((event: BrowserSpeechRecognitionErrorEvent) => void) | null;
  onresult: ((event: BrowserSpeechRecognitionResultEvent) => void) | null;
  abort(): void;
  start(): void;
  stop(): void;
}

interface BrowserSpeechRecognitionConstructor {
  new (): BrowserSpeechRecognitionController;
}

interface SpeechRecognitionWindow extends Window {
  SpeechRecognition?: BrowserSpeechRecognitionConstructor;
  webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
}

/** 创建可选的浏览器语音识别器；不支持时返回 null。 */
export function createBrowserSpeechRecognition():
  | BrowserSpeechRecognitionController
  | null {
  if (typeof window === "undefined") {
    return null;
  }
  const speechWindow = window as SpeechRecognitionWindow;
  const Constructor =
    speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
  if (!Constructor) {
    return null;
  }
  const recognition = new Constructor();
  recognition.continuous = true;
  recognition.interimResults = true;
  // 语音灵感以中文为主，浏览器会对其中的英文词句做有限识别。
  recognition.lang = "zh-CN";
  return recognition;
}
