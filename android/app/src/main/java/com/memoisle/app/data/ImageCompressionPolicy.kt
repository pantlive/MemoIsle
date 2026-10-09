package com.memoisle.app.data

import java.util.Locale
import kotlin.math.floor
import kotlin.math.min
import kotlin.math.sqrt

/**
 * 图片上传的压缩策略。
 *
 * 这里只做纯计算，不引用任何 `android.graphics` 类型，因此可以在 JVM 单元测试里直接验证。
 * 各项限制与后端 `backend/app/service.py` 保持一致：
 * - 单张图片字节数 ≤ 20 MB；
 * - 最长边 ≤ 12000 像素；
 * - 总像素 ≤ 50_000_000。
 */
object ImageCompressionPolicy {
    /** 服务端允许的图片字节数上限（20 MB）。 */
    const val MAX_UPLOAD_BYTES: Long = MAX_IMAGE_UPLOAD_BYTES.toLong()

    /** 服务端允许的最长边（像素）。 */
    const val MAX_DIMENSION: Int = 12_000

    /** 服务端允许的总像素数。 */
    const val MAX_PIXELS: Long = 50_000_000L

    /** 质量已经降到下限后继续缩小的比例。 */
    const val SHRINK_FACTOR: Double = 0.7

    /**
     * 判断图片是否会被服务端拒绝：只要超过字节数、最长边或总像素中的任意一项，就需要压缩。
     * 尺寸未知（≤ 0）时只按字节数判断。
     */
    fun needsCompression(byteCount: Long, width: Int, height: Int): Boolean {
        if (byteCount > MAX_UPLOAD_BYTES) {
            return true
        }
        if (width > MAX_DIMENSION || height > MAX_DIMENSION) {
            return true
        }
        return width > 0 && height > 0 && width.toLong() * height.toLong() > MAX_PIXELS
    }

    /**
     * 计算压缩后的目标尺寸：同时满足最长边和总像素限制，且从不放大。
     * 尺寸非法时返回至少 1，保证调用方不会拿到 0。
     */
    fun targetSize(
        width: Int,
        height: Int,
        maxDimension: Int = MAX_DIMENSION,
        maxPixels: Long = MAX_PIXELS,
    ): Pair<Int, Int> {
        if (width <= 0 || height <= 0) {
            return width.coerceAtLeast(1) to height.coerceAtLeast(1)
        }
        var scale = 1.0
        val longestSide = maxOf(width, height)
        if (maxDimension > 0 && longestSide > maxDimension) {
            scale = min(scale, maxDimension.toDouble() / longestSide.toDouble())
        }
        val pixels = width.toLong() * height.toLong()
        if (maxPixels > 0 && pixels > maxPixels) {
            scale = min(scale, sqrt(maxPixels.toDouble() / pixels.toDouble()))
        }
        if (scale >= 1.0) {
            return width to height
        }
        return floor(width * scale).toInt().coerceAtLeast(1) to
            floor(height * scale).toInt().coerceAtLeast(1)
    }

    /** 在目标尺寸基础上再按比例缩小，用于字节数仍然超限时的兜底。 */
    fun shrinkSize(
        width: Int,
        height: Int,
        factor: Double = SHRINK_FACTOR,
    ): Pair<Int, Int> {
        if (width <= 0 || height <= 0) {
            return width.coerceAtLeast(1) to height.coerceAtLeast(1)
        }
        val safeFactor = factor.coerceIn(0.05, 0.95)
        return floor(width * safeFactor).toInt().coerceAtLeast(1) to
            floor(height * safeFactor).toInt().coerceAtLeast(1)
    }

    /**
     * 计算 `BitmapFactory.Options.inSampleSize`：取满足解码后仍不小于目标尺寸的最大 2 的幂，
     * 这样大图不会被整块解码进内存，后续再缩放到目标尺寸时也不会放大。
     */
    fun sampleSizeFor(
        width: Int,
        height: Int,
        targetWidth: Int,
        targetHeight: Int,
    ): Int {
        if (width <= 0 || height <= 0 || targetWidth <= 0 || targetHeight <= 0) {
            return 1
        }
        var sampleSize = 1
        while (width / (sampleSize * 2) >= targetWidth &&
            height / (sampleSize * 2) >= targetHeight
        ) {
            sampleSize *= 2
        }
        return sampleSize
    }

    /**
     * 有透明通道的图片必须输出 PNG，其余统一输出体积更小的 JPEG。
     * [sourceMimeType] 只用于说明来源格式（例如 GIF 需要提示动图信息丢失），不改变判定结果。
     */
    @Suppress("UNUSED_PARAMETER")
    fun chooseOutputFormat(hasAlpha: Boolean, sourceMimeType: String?): ImageOutputFormat {
        return if (hasAlpha) ImageOutputFormat.PNG else ImageOutputFormat.JPEG
    }

    /** 把 MIME 转成用户可读的格式名。 */
    fun formatLabel(mimeType: String?): String {
        return when (normalizeImageMimeType(mimeType)) {
            "image/png" -> "PNG"
            "image/jpeg" -> "JPEG"
            "image/webp" -> "WebP"
            "image/gif" -> "GIF"
            else -> "图片"
        }
    }

    /**
     * 生成压缩后的中文提醒文案，例如：
     * `图片已自动压缩后收藏：12.0 MB → 2.4 MB；尺寸 14400 × 9000 → 12000 × 7500；格式 PNG → JPEG`
     *
     * 尺寸或格式没有变化时对应片段会省略；来源是 GIF 时额外提示动图变成静态图。
     */
    fun describeCompression(
        originalByteCount: Int,
        newByteCount: Int,
        originalWidth: Int,
        originalHeight: Int,
        newWidth: Int,
        newHeight: Int,
        sourceMimeType: String?,
        outputFormat: ImageOutputFormat,
        animationDropped: Boolean,
    ): String {
        val details = mutableListOf<String>()
        details += "${sizeLabel(originalByteCount)} → ${sizeLabel(newByteCount)}"
        val dimensionsChanged = originalWidth > 0 &&
            originalHeight > 0 &&
            (originalWidth != newWidth || originalHeight != newHeight)
        if (dimensionsChanged) {
            details += "尺寸 $originalWidth × $originalHeight → $newWidth × $newHeight"
        }
        val sourceLabel = formatLabel(sourceMimeType)
        if (sourceLabel != outputFormat.label) {
            details += "格式 $sourceLabel → ${outputFormat.label}"
        }
        if (animationDropped) {
            details += "动图已转为静态图，仅保留第一帧"
        }
        return "图片已自动压缩后收藏：" + details.joinToString("；")
    }

    private fun sizeLabel(bytes: Int): String {
        return formatFileSize(bytes) ?: String.format(Locale.ROOT, "%d B", bytes)
    }
}

/** 自动压缩后的输出格式；服务端只接受这里产出的 PNG/JPEG。 */
enum class ImageOutputFormat(val mimeType: String, val label: String) {
    JPEG("image/jpeg", "JPEG"),
    PNG("image/png", "PNG"),
}
