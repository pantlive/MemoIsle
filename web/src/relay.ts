/** 文件/文本中转的纯函数：大小校验、文案、倒计时。界面在 RelayPanel。 */

import { RELAY_MAX_FILE_BYTES, RELAY_MAX_TEXT_BYTES } from "./api";
import type { RelayDevice } from "./types";

export const relayDeviceLabels: Record<RelayDevice, string> = {
  web: "网页",
  android: "手机",
};

export function utf8ByteLength(value: string): number {
  return new TextEncoder().encode(value).length;
}

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(size < 10 * 1024 ? 1 : 0)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

/** 发送前在本地挡住超限内容，返回中文提示；可以发送时返回 null。 */
export function relayTextError(text: string): string | null {
  if (!text.trim()) return "请输入要发送的内容。";
  if (utf8ByteLength(text) > RELAY_MAX_TEXT_BYTES) {
    return "文本不能超过 100 KB，请改用文件发送。";
  }
  return null;
}

export function relayFileError(file: Pick<File, "name" | "size">): string | null {
  if (file.size <= 0) return `「${file.name}」是空文件。`;
  if (file.size > RELAY_MAX_FILE_BYTES) {
    return `「${file.name}」有 ${formatBytes(file.size)}，单个文件不能超过 20 MB。`;
  }
  return null;
}

/** 剩余有效时间，如「9:58」；到期返回「已过期」。 */
export function formatRemaining(seconds: number): string {
  if (seconds <= 0) return "已过期";
  const whole = Math.ceil(seconds);
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}
