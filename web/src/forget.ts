import { t } from "./i18n";
/**
 * 易忘事项的类型和纯函数。Android 端 `data/ForgetItem.kt` 按同一套上限实现。
 */

export const FORGET_TITLE_MAX = 100;
export const FORGET_CONTENT_MAX = 10_000;
export const FORGET_MAX_ATTACHMENTS = 20;
export const FORGET_MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024;

export type ForgetAttachmentKind = "image" | "file";

export interface ForgetAttachment {
  id: string;
  kind: ForgetAttachmentKind;
  original_name: string;
  mime: string;
  size: number;
  sha256: string;
  position: number;
  created_at: string;
}

export interface ForgetItemInput {
  title: string;
  content: string;
  pinned: boolean;
}

export interface ForgetItem extends ForgetItemInput {
  id: string;
  version: number;
  created_at: string;
  updated_at: string;
  attachments: ForgetAttachment[];
}

/** 与后端一样按 Unicode 码位计字数，一个汉字和一个 emoji 都算一个字。 */
export function forgetTextLength(value: string): number {
  return [...value].length;
}

/** 标题、正文超长时返回中文提示；都可以为空，用来只收藏附件。 */
export function forgetTextError(title: string, content: string): string | null {
  if (forgetTextLength(title.trim()) > FORGET_TITLE_MAX) {
    return t("标题最多 {FORGET_TITLE_MAX} 个字", { FORGET_TITLE_MAX });
  }
  if (forgetTextLength(content.trim()) > FORGET_CONTENT_MAX) {
    return t("正文最多 {FORGET_CONTENT_MAX} 个字", { FORGET_CONTENT_MAX });
  }
  return null;
}

/** 上传前在本地挡住空文件和超过 20 MB 的附件。 */
export function forgetFileError(file: { size: number }): string | null {
  if (file.size <= 0) return t("附件内容不能为空");
  if (file.size > FORGET_MAX_ATTACHMENT_BYTES) return t("附件不能超过 20 MB");
  return null;
}

export function formatForgetBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) {
    const text = (size / 1024).toFixed(size < 10 * 1024 ? 1 : 0);
    return `${text.endsWith(".0") ? text.slice(0, -2) : text} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export function forgetDisplayTitle(title: string): string {
  return title.trim() || t("未命名");
}

export function isForgetImage(attachment: Pick<ForgetAttachment, "kind">): boolean {
  return attachment.kind === "image";
}
