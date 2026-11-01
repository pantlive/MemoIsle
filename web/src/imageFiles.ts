import type { ImageOcrSource, Memo } from "./types";

/** 图片条目的文件信息与上传前的类型推断。 */

export function formatImageBytes(bytes: number | null): string {
  if (!bytes || bytes <= 0) {
    return "";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function imageDimensionLabel(memo: Memo): string {
  if (memo.image_width && memo.image_height) {
    return `${memo.image_width} × ${memo.image_height}`;
  }
  return "尺寸未知";
}

export function imageInfoLabel(memo: Memo): string {
  if (!memo.image_mime_type) {
    return "尚未上传图片文件";
  }
  const parts = [
    imageDimensionLabel(memo),
    formatImageBytes(memo.image_size_bytes),
    memo.image_mime_type.replace("image/", "").toUpperCase(),
  ].filter((part) => part.length > 0);
  return parts.join(" · ");
}

export function imageOcrSourceLabel(source: ImageOcrSource | null): string {
  if (source === "local") {
    return "本地识别";
  }
  if (source === "llm") {
    return "视觉模型";
  }
  return "";
}

export function imageFileTitle(file: File | Blob): string {
  const rawName = file instanceof File ? file.name : "";
  const base = rawName.replace(/\.[^.]+$/, "").trim();
  return base || "粘贴的图片";
}

export function imageMimeFromFile(file: File): string {
  if (file.type.startsWith("image/")) {
    return file.type;
  }
  const extension = file.name.toLowerCase().split(".").pop() ?? "";
  switch (extension) {
    case "png":
      return "image/png";
    case "jpg":
    case "jpeg":
      return "image/jpeg";
    case "webp":
      return "image/webp";
    case "gif":
      return "image/gif";
    default:
      return "";
  }
}

export function imageFileExtension(mimeType: string | null): string {
  switch (mimeType) {
    case "image/png":
      return "png";
    case "image/jpeg":
      return "jpg";
    case "image/webp":
      return "webp";
    case "image/gif":
      return "gif";
    default:
      return "image";
  }
}

export function isImageFile(file: File): boolean {
  return file.type.startsWith("image/") || imageMimeFromFile(file) !== "";
}
