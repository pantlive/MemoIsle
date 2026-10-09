package com.memoisle.app.data

import android.content.ContentResolver
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.provider.OpenableColumns
import java.io.ByteArrayOutputStream

/**
 * 必须压缩但压缩失败时抛出。继承 [IllegalArgumentException]，让 ViewModel 直接把原因展示给用户，
 * 而不是当成“已保存到本机、稍后重试”的网络错误。
 */
class ImageCompressionException(message: String) : IllegalArgumentException(message)

/**
 * 一次图片上传前的准备结果。
 *
 * [compressed] 为 false 时 [bytes] 就是原图字节，[mimeType] 是来源 MIME；为 true 时
 * [mimeType] 一定是 [ImageOutputFormat.JPEG] 或 [ImageOutputFormat.PNG] 对应的值。
 */
data class ImageCompressionResult(
    val bytes: ByteArray,
    val mimeType: String,
    val compressed: Boolean,
    val animationDropped: Boolean,
    val originalByteCount: Int,
    val originalWidth: Int,
    val originalHeight: Int,
    val width: Int,
    val height: Int,
    val sourceMimeType: String,
    val outputFormat: ImageOutputFormat?,
) {
    val newByteCount: Int get() = bytes.size

    /** 压缩后展示给用户的中文提醒；未压缩时返回空串。 */
    fun reminderMessage(): String {
        val format = outputFormat ?: return ""
        if (!compressed) {
            return ""
        }
        return ImageCompressionPolicy.describeCompression(
            originalByteCount = originalByteCount,
            newByteCount = newByteCount,
            originalWidth = originalWidth,
            originalHeight = originalHeight,
            newWidth = width,
            newHeight = height,
            sourceMimeType = sourceMimeType,
            outputFormat = format,
            animationDropped = animationDropped,
        )
    }
}

/**
 * Android 端图片压缩器：只在图片会被服务端拒绝时才动手。
 *
 * 流程：先用 `inJustDecodeBounds` 读尺寸判断是否需要压缩；需要压缩时再按 `inSampleSize`
 * 解码、缩放到策略目标尺寸，并用 JPEG 质量循环 + 逐步缩小保证结果 ≤ 20 MB。
 * 已经在限制内的图片原样返回，不做任何重编码。
 */
object ImageCompressor {
    /** JPEG 质量尝试顺序，先保证画质，再逐步降低。 */
    private val JPEG_QUALITIES = intArrayOf(85, 70, 55, 40, 25, 15, 8)
    private const val PNG_QUALITY = 100

    /** 质量降到下限后继续缩小的轮数上限。 */
    private const val MAX_SHRINK_ROUNDS = 4

    /** 编码尝试次数上限（质量循环 + 缩小轮次共享该预算）。 */
    private const val MAX_ENCODE_ATTEMPTS = 18

    /** 解码失败/OOM 时用更大的 inSampleSize 重试的次数上限。 */
    private const val MAX_DECODE_ATTEMPTS = 3

    /**
     * 读取并准备图片字节：
     * 1. 已在限制内 → 返回原图；
     * 2. 超出限制 → 压缩到 20 MB 以内、最长边 ≤ 12000、总像素 ≤ 50M；
     * 3. 必须压缩但解码/编码失败 → 抛出 [ImageCompressionException]。
     */
    fun compress(
        contentResolver: ContentResolver,
        uri: Uri,
        sourceMimeType: String,
    ): ImageCompressionResult {
        val bounds = readBounds(contentResolver, uri)
        val sourceWidth = bounds?.first ?: 0
        val sourceHeight = bounds?.second ?: 0
        val hasDimensions = sourceWidth > 0 && sourceHeight > 0
        val declaredSize = queryDeclaredSize(contentResolver, uri)

        if (hasDimensions && declaredSize != null &&
            ImageCompressionPolicy.needsCompression(declaredSize, sourceWidth, sourceHeight)
        ) {
            // 已经确定超限：直接压缩，不把原图整体读进内存。
            return compressBitmap(
                contentResolver = contentResolver,
                uri = uri,
                originalBytes = null,
                originalByteCount = declaredSize,
                sourceWidth = sourceWidth,
                sourceHeight = sourceHeight,
                sourceMimeType = sourceMimeType,
            )
        }

        val originalBytes = readBytes(contentResolver, uri)
        if (originalBytes.isEmpty()) {
            throw IllegalArgumentException("图片内容不能为空")
        }
        val originalByteCount = originalBytes.size.toLong()
        if (!ImageCompressionPolicy.needsCompression(
                originalByteCount,
                sourceWidth,
                sourceHeight,
            )
        ) {
            return unchangedResult(originalBytes, sourceMimeType, sourceWidth, sourceHeight)
        }
        if (!hasDimensions) {
            throw ImageCompressionException("无法解析图片尺寸，且图片超过 20 MB，请换一张图片")
        }
        return compressBitmap(
            contentResolver = contentResolver,
            uri = uri,
            originalBytes = originalBytes,
            originalByteCount = originalByteCount,
            sourceWidth = sourceWidth,
            sourceHeight = sourceHeight,
            sourceMimeType = sourceMimeType,
        )
    }

    private fun compressBitmap(
        contentResolver: ContentResolver,
        uri: Uri,
        originalBytes: ByteArray?,
        originalByteCount: Long,
        sourceWidth: Int,
        sourceHeight: Int,
        sourceMimeType: String,
    ): ImageCompressionResult {
        val target = ImageCompressionPolicy.targetSize(sourceWidth, sourceHeight)
        val sampleSize = ImageCompressionPolicy.sampleSizeFor(
            sourceWidth,
            sourceHeight,
            target.first,
            target.second,
        )
        var bitmap = decodeBitmap(contentResolver, uri, originalBytes, sampleSize)
        try {
            // 先确定输出格式：透明通道信息必须从解码结果读取，缩放后再读不可靠。
            val outputFormat = ImageCompressionPolicy.chooseOutputFormat(
                bitmap.hasAlpha(),
                sourceMimeType,
            )
            val animationDropped = normalizeImageMimeType(sourceMimeType) == "image/gif"

            // 只缩小、不放大；解码尺寸已经小于目标时保持原样。
            val scaledWidth = minOf(bitmap.width, target.first)
            val scaledHeight = minOf(bitmap.height, target.second)
            if (scaledWidth != bitmap.width || scaledHeight != bitmap.height) {
                val scaled = Bitmap.createScaledBitmap(bitmap, scaledWidth, scaledHeight, true)
                if (scaled !== bitmap) {
                    bitmap.recycle()
                }
                bitmap = scaled
            }

            var bestBytes: ByteArray? = null
            var attempts = 0
            var shrinkRounds = 0
            var qualityIndex = 0
            while (attempts < MAX_ENCODE_ATTEMPTS) {
                attempts += 1
                val quality = if (outputFormat == ImageOutputFormat.JPEG) {
                    JPEG_QUALITIES[minOf(qualityIndex, JPEG_QUALITIES.lastIndex)]
                } else {
                    PNG_QUALITY
                }
                val encoded = encodeBitmap(bitmap, outputFormat, quality)
                if (encoded != null) {
                    if (bestBytes == null || encoded.size < bestBytes.size) {
                        bestBytes = encoded
                    }
                    if (encoded.size <= ImageCompressionPolicy.MAX_UPLOAD_BYTES) {
                        return compressedResult(
                            bytes = encoded,
                            outputFormat = outputFormat,
                            animationDropped = animationDropped,
                            originalByteCount = originalByteCount,
                            sourceWidth = sourceWidth,
                            sourceHeight = sourceHeight,
                            width = bitmap.width,
                            height = bitmap.height,
                            sourceMimeType = sourceMimeType,
                        )
                    }
                }
                val canLowerQuality = outputFormat == ImageOutputFormat.JPEG &&
                    qualityIndex < JPEG_QUALITIES.lastIndex
                if (canLowerQuality) {
                    qualityIndex += 1
                    continue
                }
                if (shrinkRounds >= MAX_SHRINK_ROUNDS) {
                    break
                }
                val shrunkSize = ImageCompressionPolicy.shrinkSize(bitmap.width, bitmap.height)
                if (shrunkSize.first == bitmap.width && shrunkSize.second == bitmap.height) {
                    break
                }
                val shrunk = Bitmap.createScaledBitmap(
                    bitmap,
                    shrunkSize.first,
                    shrunkSize.second,
                    true,
                )
                if (shrunk !== bitmap) {
                    bitmap.recycle()
                }
                bitmap = shrunk
                shrinkRounds += 1
                qualityIndex = 0
            }
            val fallback = bestBytes?.takeIf {
                it.size <= ImageCompressionPolicy.MAX_UPLOAD_BYTES
            } ?: throw ImageCompressionException("图片压缩后仍无法小于 20 MB，请换一张图片")
            return compressedResult(
                bytes = fallback,
                outputFormat = outputFormat,
                animationDropped = animationDropped,
                originalByteCount = originalByteCount,
                sourceWidth = sourceWidth,
                sourceHeight = sourceHeight,
                width = bitmap.width,
                height = bitmap.height,
                sourceMimeType = sourceMimeType,
            )
        } finally {
            bitmap.recycle()
        }
    }

    /**
     * 用 `inJustDecodeBounds` 读取尺寸，避免为了判断是否超限而解码整张原图。
     * 读取失败时返回 null，调用方按“尺寸未知”处理。
     */
    private fun readBounds(contentResolver: ContentResolver, uri: Uri): Pair<Int, Int>? {
        return runCatching {
            val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            contentResolver.openInputStream(uri)?.use { stream ->
                BitmapFactory.decodeStream(stream, null, options)
            }
            if (options.outWidth > 0 && options.outHeight > 0) {
                options.outWidth to options.outHeight
            } else {
                null
            }
        }.getOrNull()
    }

    /**
     * 尽量不解码就把文件字节数问出来：先查 `OpenableColumns.SIZE`，再退回文件描述符长度。
     */
    private fun queryDeclaredSize(contentResolver: ContentResolver, uri: Uri): Long? {
        val fromCursor = runCatching {
            contentResolver.query(uri, arrayOf(OpenableColumns.SIZE), null, null, null)?.use { cursor ->
                if (!cursor.moveToFirst()) {
                    return@use null
                }
                val index = cursor.getColumnIndex(OpenableColumns.SIZE)
                if (index < 0 || cursor.isNull(index)) null else cursor.getLong(index)
            }
        }.getOrNull()
        if (fromCursor != null && fromCursor > 0) {
            return fromCursor
        }
        return runCatching {
            contentResolver.openAssetFileDescriptor(uri, "r")?.use { descriptor ->
                descriptor.length
            }
        }.getOrNull()?.takeIf { it > 0 }
    }

    private fun readBytes(contentResolver: ContentResolver, uri: Uri): ByteArray {
        return contentResolver.openInputStream(uri)?.use { it.readBytes() }
            ?: throw IllegalStateException("无法读取所选图片")
    }

    /**
     * 按 `inSampleSize` 解码；内存不足或解码失败时用更大采样重试，最终仍失败才算压缩失败。
     */
    private fun decodeBitmap(
        contentResolver: ContentResolver,
        uri: Uri,
        originalBytes: ByteArray?,
        initialSampleSize: Int,
    ): Bitmap {
        var sampleSize = initialSampleSize.coerceAtLeast(1)
        var attempt = 0
        while (attempt < MAX_DECODE_ATTEMPTS) {
            attempt += 1
            val decoded = runCatching {
                val options = BitmapFactory.Options().apply {
                    inSampleSize = sampleSize
                    inPreferredConfig = Bitmap.Config.ARGB_8888
                }
                if (originalBytes != null) {
                    BitmapFactory.decodeByteArray(originalBytes, 0, originalBytes.size, options)
                } else {
                    contentResolver.openInputStream(uri)?.use { stream ->
                        BitmapFactory.decodeStream(stream, null, options)
                    }
                }
            }.getOrNull()
            if (decoded != null) {
                return decoded
            }
            sampleSize *= 2
        }
        throw ImageCompressionException("图片解码失败，无法压缩，请换一张图片")
    }

    /** 编码到内存；返回 null 表示编码器拒绝该格式或没有产出内容。 */
    private fun encodeBitmap(
        bitmap: Bitmap,
        outputFormat: ImageOutputFormat,
        quality: Int,
    ): ByteArray? {
        val compressFormat = when (outputFormat) {
            ImageOutputFormat.JPEG -> Bitmap.CompressFormat.JPEG
            ImageOutputFormat.PNG -> Bitmap.CompressFormat.PNG
        }
        val output = ByteArrayOutputStream()
        val succeeded = runCatching {
            output.use { bitmap.compress(compressFormat, quality, it) }
        }.getOrDefault(false)
        if (!succeeded) {
            return null
        }
        return output.toByteArray().takeIf { it.isNotEmpty() }
    }

    private fun unchangedResult(
        bytes: ByteArray,
        sourceMimeType: String,
        width: Int,
        height: Int,
    ): ImageCompressionResult {
        return ImageCompressionResult(
            bytes = bytes,
            mimeType = sourceMimeType,
            compressed = false,
            animationDropped = false,
            originalByteCount = bytes.size,
            originalWidth = width,
            originalHeight = height,
            width = width,
            height = height,
            sourceMimeType = sourceMimeType,
            outputFormat = null,
        )
    }

    private fun compressedResult(
        bytes: ByteArray,
        outputFormat: ImageOutputFormat,
        animationDropped: Boolean,
        originalByteCount: Long,
        sourceWidth: Int,
        sourceHeight: Int,
        width: Int,
        height: Int,
        sourceMimeType: String,
    ): ImageCompressionResult {
        return ImageCompressionResult(
            bytes = bytes,
            mimeType = outputFormat.mimeType,
            compressed = true,
            animationDropped = animationDropped,
            originalByteCount = originalByteCount.coerceAtMost(Int.MAX_VALUE.toLong()).toInt(),
            originalWidth = sourceWidth,
            originalHeight = sourceHeight,
            width = width,
            height = height,
            sourceMimeType = sourceMimeType,
            outputFormat = outputFormat,
        )
    }
}
