// 与服务端 backend/app/service.py 的图片限制保持一致。
// 只有当图片会被服务端拒绝时才在浏览器里压缩，避免无谓的画质损失。
export const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
export const MAX_IMAGE_DIMENSION = 12_000;
export const MAX_IMAGE_PIXELS = 50_000_000;

const MAX_COMPRESSION_ATTEMPTS = 12;
const INITIAL_QUALITY = 0.9;
const MIN_QUALITY = 0.55;

export interface ImageDimensions {
  width: number;
  height: number;
}

export interface ImageCompressionResult {
  /** 实际上传的字节；未压缩时就是原文件。 */
  blob: Blob;
  compressed: boolean;
  originalBytes: number;
  newBytes: number;
  originalWidth: number;
  originalHeight: number;
  newWidth: number;
  newHeight: number;
  originalType: string;
  newType: string;
  /** GIF 被压缩后只剩第一帧，需要提醒用户动图已变成静态图。 */
  animationDropped: boolean;
}

/** 是否需要压缩：超过字节、单边或总像素任一服务端限制。 */
export function imageExceedsServerLimits(
  sizeBytes: number,
  width: number,
  height: number,
): boolean {
  return (
    sizeBytes > MAX_IMAGE_BYTES ||
    width > MAX_IMAGE_DIMENSION ||
    height > MAX_IMAGE_DIMENSION ||
    width * height > MAX_IMAGE_PIXELS
  );
}

export function formatImageBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (bytes >= 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }
  return `${bytes} B`;
}

function mimeLabel(mimeType: string): string {
  switch (mimeType) {
    case "image/png":
      return "PNG";
    case "image/jpeg":
    case "image/jpg":
      return "JPEG";
    case "image/webp":
      return "WebP";
    case "image/gif":
      return "GIF";
    default:
      return mimeType || "未知格式";
  }
}

let webpEncodingSupport: boolean | null = null;

function canEncodeWebp(): boolean {
  if (webpEncodingSupport === null) {
    try {
      const canvas = document.createElement("canvas");
      canvas.width = 1;
      canvas.height = 1;
      webpEncodingSupport = canvas
        .toDataURL("image/webp")
        .startsWith("data:image/webp");
    } catch {
      webpEncodingSupport = false;
    }
  }
  return webpEncodingSupport;
}

/** 压缩输出格式：优先 WebP（支持透明且体积小），否则按源格式回退。 */
export function pickCompressedMimeType(sourceMimeType: string): string {
  if (canEncodeWebp()) {
    return "image/webp";
  }
  return sourceMimeType === "image/png" || sourceMimeType === "image/gif"
    ? "image/png"
    : "image/jpeg";
}

/** 读取图片真实像素尺寸，优先使用 createImageBitmap。 */
export async function readImageDimensions(blob: Blob): Promise<ImageDimensions> {
  if (typeof createImageBitmap === "function") {
    try {
      const bitmap = await createImageBitmap(blob);
      const dimensions = { width: bitmap.width, height: bitmap.height };
      bitmap.close?.();
      return dimensions;
    } catch {
      // 回退到 <img> 解码。
    }
  }
  return await new Promise<ImageDimensions>((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.onload = () => {
      const dimensions = {
        width: image.naturalWidth,
        height: image.naturalHeight,
      };
      URL.revokeObjectURL(url);
      resolve(dimensions);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("图片无法解码，可能已损坏"));
    };
    image.src = url;
  });
}

function initialTargetSize(dimensions: ImageDimensions): ImageDimensions {
  const scale = Math.min(
    1,
    MAX_IMAGE_DIMENSION / dimensions.width,
    MAX_IMAGE_DIMENSION / dimensions.height,
    Math.sqrt(MAX_IMAGE_PIXELS / (dimensions.width * dimensions.height)),
  );
  return {
    width: Math.max(1, Math.floor(dimensions.width * scale)),
    height: Math.max(1, Math.floor(dimensions.height * scale)),
  };
}

async function loadDrawable(
  source: Blob,
  width: number,
  height: number,
): Promise<CanvasImageSource> {
  if (typeof createImageBitmap === "function") {
    try {
      return await createImageBitmap(source, {
        resizeWidth: width,
        resizeHeight: height,
        resizeQuality: "high",
      });
    } catch {
      return await createImageBitmap(source);
    }
  }
  return await new Promise<HTMLImageElement>((resolve, reject) => {
    const url = URL.createObjectURL(source);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("图片无法解码，可能已损坏"));
    };
    image.src = url;
  });
}

async function renderScaled(
  source: Blob,
  width: number,
  height: number,
): Promise<HTMLCanvasElement> {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("当前浏览器不支持图片压缩");
  }
  const drawable = await loadDrawable(source, width, height);
  try {
    context.drawImage(drawable, 0, 0, width, height);
  } finally {
    if (typeof ImageBitmap !== "undefined" && drawable instanceof ImageBitmap) {
      drawable.close();
    }
  }
  return canvas;
}

function canvasToBlob(
  canvas: HTMLCanvasElement,
  mimeType: string,
  quality: number,
): Promise<Blob> {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          reject(new Error("图片压缩失败"));
          return;
        }
        // 部分浏览器会忽略不支持的输出格式，这里强制标注为目标类型。
        resolve(blob.type === mimeType ? blob : blob.slice(0, blob.size, mimeType));
      },
      mimeType,
      quality,
    );
  });
}

/**
 * 仅在图片超过服务端限制时压缩：先按尺寸/像素约束缩放，再逐步降低质量，
 * 必要时继续缩小尺寸，直到字节数降到 20 MB 以内。
 */
export async function compressImageIfNeeded(
  file: File | Blob,
  declaredMimeType: string,
): Promise<ImageCompressionResult> {
  const originalType = declaredMimeType || file.type || "";
  const dimensions = await readImageDimensions(file);
  const untouched: ImageCompressionResult = {
    blob: file,
    compressed: false,
    originalBytes: file.size,
    newBytes: file.size,
    originalWidth: dimensions.width,
    originalHeight: dimensions.height,
    newWidth: dimensions.width,
    newHeight: dimensions.height,
    originalType,
    newType: originalType,
    animationDropped: false,
  };
  if (!imageExceedsServerLimits(file.size, dimensions.width, dimensions.height)) {
    return untouched;
  }

  const outputType = pickCompressedMimeType(originalType);
  let target = initialTargetSize(dimensions);
  let quality = INITIAL_QUALITY;
  let best: { blob: Blob; width: number; height: number } | null = null;
  let lastError: Error | null = null;
  for (let attempt = 0; attempt < MAX_COMPRESSION_ATTEMPTS; attempt += 1) {
    try {
      const canvas = await renderScaled(file, target.width, target.height);
      const blob = await canvasToBlob(canvas, outputType, quality);
      if (!best || blob.size < best.blob.size) {
        best = { blob, width: target.width, height: target.height };
      }
      if (blob.size <= MAX_IMAGE_BYTES) {
        break;
      }
      if (quality > MIN_QUALITY) {
        quality = Math.max(MIN_QUALITY, quality - 0.12);
        continue;
      }
    } catch (error) {
      // 单次解码/编码失败（例如画布过大）时继续缩小后重试。
      lastError = error instanceof Error ? error : new Error("图片压缩失败");
    }
    target = {
      width: Math.max(1, Math.round(target.width * 0.75)),
      height: Math.max(1, Math.round(target.height * 0.75)),
    };
    quality = 0.8;
  }
  if (!best) {
    throw lastError ?? new Error("图片压缩失败");
  }
  if (best.blob.size > MAX_IMAGE_BYTES) {
    throw new Error("图片过大，自动压缩后仍超过 20 MB，请先裁剪后再上传");
  }
  return {
    ...untouched,
    blob: best.blob,
    compressed: true,
    newBytes: best.blob.size,
    newWidth: best.width,
    newHeight: best.height,
    newType: outputType,
    animationDropped: originalType === "image/gif",
  };
}

/** 生成给用户看的压缩说明，包含原大小、新大小、尺寸与格式变化。 */
export function describeImageCompression(
  result: ImageCompressionResult,
): string {
  const parts = [
    `图片超过服务端限制，已自动压缩后上传：${formatImageBytes(
      result.originalBytes,
    )} → ${formatImageBytes(result.newBytes)}`,
  ];
  if (
    result.newWidth !== result.originalWidth ||
    result.newHeight !== result.originalHeight
  ) {
    parts.push(
      `尺寸 ${result.originalWidth}×${result.originalHeight} → ${result.newWidth}×${result.newHeight}`,
    );
  }
  if (
    result.originalType &&
    result.newType &&
    result.originalType !== result.newType
  ) {
    parts.push(
      `格式 ${mimeLabel(result.originalType)} → ${mimeLabel(result.newType)}`,
    );
  }
  if (result.animationDropped) {
    parts.push("动图已转为静态图片");
  }
  return parts.join("；");
}
