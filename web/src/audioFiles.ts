import type { Memo } from "./types";

export function audioFileExtension(mimeType: string | null): string {
  switch ((mimeType ?? "").split(";")[0].trim().toLowerCase()) {
    case "audio/mp4":
    case "audio/x-m4a":
    case "audio/m4a":
      return "m4a";
    case "audio/mpeg":
      return "mp3";
    case "audio/ogg":
      return "ogg";
    case "audio/webm":
      return "webm";
    case "audio/wav":
    case "audio/x-wav":
      return "wav";
    default:
      return "audio";
  }
}

export function isMeetingRecording(memo: Memo): boolean {
  // 会议模式创建时固定带上「会议」标签；普通语音也可能有转写文本，不能据 transcript 判断。
  return memo.tags.includes("会议");
}

export function audioDownloadFileName(memo: Memo): string {
  const fallback = isMeetingRecording(memo) ? "会议录音" : "语音灵感";
  const title = (memo.title || fallback)
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_")
    .trim()
    .slice(0, 80);
  const date = memo.created_at.slice(0, 10);
  return `${title || fallback}-${date}.${audioFileExtension(memo.audio_mime_type)}`;
}

export function triggerBlobDownload(url: string, filename: string): void {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}
