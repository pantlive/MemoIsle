/** 文件/文本中转的纯函数：大小校验、文案、倒计时。界面在 RelayPanel。 */

import { RELAY_MAX_FILE_BYTES, RELAY_MAX_TEXT_BYTES } from "./api";
import type { RelayDevice, RelayItem } from "./types";
import { t } from "./i18n";

const CLIPBOARD_IMAGE_EXTENSIONS: Record<string, string> = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/jpg": "jpg",
  "image/gif": "gif",
  "image/webp": "webp",
  "image/bmp": "bmp",
  "image/svg+xml": "svg",
  "image/heic": "heic",
  "image/heif": "heif",
};

export const relayDeviceLabels: Record<RelayDevice, string> = {
  get web() { return t("网页"); },
  get android() { return t("手机"); },
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
  if (!text.trim()) return t("请输入要发送的内容。");
  if (utf8ByteLength(text) > RELAY_MAX_TEXT_BYTES) {
    return t("文本不能超过 100 KB，请改用文件发送。");
  }
  return null;
}

export function relayFileError(file: Pick<File, "name" | "size">): string | null {
  if (file.size <= 0) return t("「{name}」是空文件。", { name: file.name });
  if (file.size > RELAY_MAX_FILE_BYTES) {
    return t("「{name}」有 {value}，单个文件不能超过 20 MB。", { name: file.name, value: formatBytes(file.size) });
  }
  return null;
}

/** 剩余有效时间，如「9:58」；到期返回「已过期」。 */
export function formatRemaining(seconds: number): string {
  if (seconds <= 0) return t("已过期");
  const whole = Math.ceil(seconds);
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

function normalizeMime(value: string): string {
  return value.split(";")[0].trim().toLowerCase();
}

/** 从 ClipboardItem.types 里挑第一个 image/*，有 png 时优先 png。 */
export function pickClipboardImageType(types: readonly string[]): string | null {
  const images = types.filter((type) => normalizeMime(type).startsWith("image/"));
  if (images.length === 0) return null;
  return images.find((type) => normalizeMime(type) === "image/png") ?? images[0];
}

/** 形如 clipboard-20261120-153000.png；未知 mime 一律用 png。 */
export function clipboardImageFilename(mime: string, date: Date): string {
  const ext = CLIPBOARD_IMAGE_EXTENSIONS[normalizeMime(mime)] ?? "png";
  const pad = (value: number) => String(value).padStart(2, "0");
  const stamp = `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-` +
    `${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
  return `clipboard-${stamp}.${ext}`;
}

export function isRelayImage(item: Pick<RelayItem, "kind" | "mime_type">): boolean {
  return item.kind === "file" && Boolean(item.mime_type && normalizeMime(item.mime_type).startsWith("image/"));
}
