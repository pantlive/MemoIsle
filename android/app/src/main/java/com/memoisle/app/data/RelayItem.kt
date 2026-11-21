package com.memoisle.app.data

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
import org.json.JSONObject
import com.memoisle.app.R
import com.memoisle.app.ui.UiText

/** 与服务端一致：文本 100 KB（UTF-8 字节），文件 20 MB，长轮询每次最多 25 秒。 */
const val RELAY_MAX_TEXT_BYTES = 100 * 1024
const val RELAY_MAX_FILE_BYTES = 20L * 1024 * 1024
const val RELAY_WAIT_SECONDS = 25
const val RELAY_DEVICE_WEB = "web"
const val RELAY_DEVICE_ANDROID = "android"

/**
 * 一条待接收的中转内容。服务端只在内存里暂放，取走即删、10 分钟后过期。
 * 文本直接带上 [text]，文件需要再调下载接口取走。
 */
data class RelayItem(
    val id: String,
    val kind: String,
    val source: String,
    val target: String,
    val filename: String?,
    val mimeType: String?,
    val size: Long,
    val createdAt: String,
    val expiresAt: String,
    /** 剩余有效秒数，倒计时以它为准，不受两端时钟偏差影响。 */
    val expiresIn: Int,
    val text: String?,
) {
    val isText: Boolean get() = kind == "text"
    val isImage: Boolean get() = kind == "file" && mimeType.orEmpty().substringBefore(';')
        .trim().startsWith("image/", ignoreCase = true)

    companion object {
        fun fromJson(json: JSONObject): RelayItem = RelayItem(
            id = json.getString("id"),
            kind = json.getString("kind"),
            source = json.getString("source"),
            target = json.getString("target"),
            filename = json.optNullableString("filename"),
            mimeType = json.optNullableString("mime_type"),
            size = json.getLong("size"),
            createdAt = json.getString("created_at"),
            expiresAt = json.getString("expires_at"),
            expiresIn = json.optInt("expires_in", 0).coerceAtLeast(0),
            text = json.optNullableString("text"),
        )
    }
}

private fun JSONObject.optNullableString(name: String): String? =
    if (!has(name) || isNull(name)) null else getString(name)

fun relayDeviceLabel(device: String): UiText = when (device) {
    RELAY_DEVICE_WEB -> UiText.res(R.string.relay_device_web)
    RELAY_DEVICE_ANDROID -> UiText.res(R.string.relay_device_android)
    else -> UiText.plain(device)
}

/** 发送前在本地挡住超限文本，返回提示；可以发送时返回 null。 */
fun relayTextError(text: String): UiText? = when {
    text.isBlank() -> UiText.res(R.string.relay_error_text_empty)
    text.toByteArray(Charsets.UTF_8).size > RELAY_MAX_TEXT_BYTES -> UiText.res(R.string.relay_error_text_too_large)
    else -> null
}

/** size 未知时传 null，读取时再按 [RELAY_MAX_FILE_BYTES] 截断检查。 */
fun relayFileError(name: String, size: Long?): UiText? = when {
    size == null -> null
    size <= 0 -> UiText.res(R.string.relay_error_file_empty, name)
    size > RELAY_MAX_FILE_BYTES -> UiText.res(R.string.relay_error_file_too_large, name, formatRelayBytes(size))
    else -> null
}

fun formatRelayBytes(size: Long): String = when {
    size < 1024 -> "$size B"
    size < 1024 * 1024 -> String.format(Locale.ROOT, if (size < 10 * 1024) "%.1f KB" else "%.0f KB", size / 1024.0)
    else -> String.format(Locale.ROOT, "%.1f MB", size / 1024.0 / 1024.0)
}

/** 剩余有效时间，如「9:58」；到期返回「已过期」。 */
fun formatRelayRemaining(seconds: Long): UiText {
    if (seconds <= 0) return UiText.res(R.string.common_expired)
    return UiText.plain("${seconds / 60}:${(seconds % 60).toString().padStart(2, '0')}")
}

fun relayImageExtension(mime: String?): String = when (
    mime.orEmpty().substringBefore(';').trim().lowercase(Locale.ROOT)
) {
    "image/png" -> "png"
    "image/jpeg", "image/jpg" -> "jpg"
    "image/gif" -> "gif"
    "image/webp" -> "webp"
    "image/bmp" -> "bmp"
    "image/svg+xml" -> "svg"
    "image/heic" -> "heic"
    "image/heif" -> "heif"
    else -> "png"
}

fun relayClipboardImageName(mimeType: String?, timeMillis: Long): String {
    val stamp = Instant.ofEpochMilli(timeMillis)
        .atZone(ZoneId.systemDefault())
        .format(CLIPBOARD_IMAGE_TIME)
    return "clipboard-$stamp.${relayImageExtension(mimeType)}"
}

private val CLIPBOARD_IMAGE_TIME: DateTimeFormatter =
    DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss", Locale.ROOT)
