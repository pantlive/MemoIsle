package com.memoisle.app.data

import java.util.Locale
import org.json.JSONArray
import org.json.JSONObject
import com.memoisle.app.R
import com.memoisle.app.ui.UiText

const val FORGET_TITLE_MAX = 100
const val FORGET_CONTENT_MAX = 10_000
const val FORGET_MAX_ATTACHMENTS = 20
const val FORGET_MAX_ATTACHMENT_BYTES = 20L * 1024 * 1024
/** 超过这个大小的图片不在页内解码，避免把大图读进内存。 */
const val FORGET_PREVIEW_MAX_BYTES = 8L * 1024 * 1024

data class ForgetItemInput(
    val title: String = "",
    val content: String = "",
    val pinned: Boolean = false,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("title", title)
        .put("content", content)
        .put("pinned", pinned)
}

data class ForgetAttachment(
    val id: String,
    val kind: String,
    val originalName: String,
    val mime: String,
    val size: Long,
    val sha256: String,
    val position: Int,
    val createdAt: String,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("id", id)
        .put("kind", kind)
        .put("original_name", originalName)
        .put("mime", mime)
        .put("size", size)
        .put("sha256", sha256)
        .put("position", position)
        .put("created_at", createdAt)

    companion object {
        fun fromJson(json: JSONObject): ForgetAttachment = ForgetAttachment(
            id = json.getString("id"),
            kind = json.optString("kind"),
            originalName = json.optString("original_name"),
            mime = json.optString("mime"),
            size = json.optLong("size"),
            sha256 = json.optString("sha256"),
            position = json.optInt("position"),
            createdAt = json.optString("created_at"),
        )
    }
}

data class ForgetItem(
    val id: String,
    val title: String,
    val content: String,
    val pinned: Boolean,
    val version: Int,
    val createdAt: String,
    val updatedAt: String,
    val attachments: List<ForgetAttachment> = emptyList(),
) {
    fun toJson(): JSONObject {
        val rows = JSONArray()
        attachments.forEach { rows.put(it.toJson()) }
        return JSONObject()
            .put("id", id)
            .put("title", title)
            .put("content", content)
            .put("pinned", pinned)
            .put("version", version)
            .put("created_at", createdAt)
            .put("updated_at", updatedAt)
            .put("attachments", rows)
    }

    companion object {
        fun fromJson(json: JSONObject): ForgetItem {
            val rows = json.optJSONArray("attachments") ?: JSONArray()
            return ForgetItem(
                id = json.getString("id"),
                title = json.optString("title"),
                content = json.optString("content"),
                pinned = json.optBoolean("pinned"),
                version = json.optInt("version"),
                createdAt = json.optString("created_at"),
                updatedAt = json.optString("updated_at"),
                attachments = List(rows.length()) { ForgetAttachment.fromJson(rows.getJSONObject(it)) },
            )
        }
    }
}

/** 与 Web 一样按 Unicode 码位计字数，一个汉字和一个 emoji 都算一个字。 */
fun forgetTextLength(value: String): Int = value.codePointCount(0, value.length)

/** 标题、正文超长时返回提示；都可以为空，用来只收藏附件。 */
fun forgetTextError(title: String, content: String): UiText? {
    if (forgetTextLength(title.trim()) > FORGET_TITLE_MAX) return UiText.res(R.string.forget_error_title_too_long, FORGET_TITLE_MAX)
    if (forgetTextLength(content.trim()) > FORGET_CONTENT_MAX) {
        return UiText.res(R.string.forget_error_content_too_long, FORGET_CONTENT_MAX)
    }
    return null
}

/** 上传前挡住空文件和超过 20 MB 的附件。大小未知时先放行，读取时再数。 */
fun forgetFileError(size: Long?): UiText? {
    if (size == null) return null
    if (size <= 0L) return UiText.res(R.string.error_attachment_empty)
    if (size > FORGET_MAX_ATTACHMENT_BYTES) return UiText.res(R.string.forget_error_attachment_too_large)
    return null
}

fun formatForgetBytes(size: Long): String {
    if (size < 1024) return "$size B"
    if (size < 1024 * 1024) {
        val digits = if (size < 10 * 1024) 1 else 0
        val text = String.format(Locale.US, "%.${digits}f", size / 1024.0)
        val trimmed = if (text.endsWith(".0")) text.dropLast(2) else text
        return "$trimmed KB"
    }
    return String.format(Locale.US, "%.1f MB", size / 1024.0 / 1024.0)
}

fun forgetDisplayTitle(title: String): String = title.trim().ifBlank { ContentDefaults.untitled }

fun isForgetImage(attachment: ForgetAttachment): Boolean = attachment.kind == "image"

/** 另存对话框只用文件名，去掉路径。 */
fun forgetSaveName(name: String): String {
    val cleaned = name.substringAfterLast('/').substringAfterLast('\\').trim()
    return cleaned.ifBlank { "file" }
}

/** 只有校验过的图片沿用图片类型；其他一律按二进制另存，避免把网页当页面打开。 */
fun forgetSaveType(attachment: ForgetAttachment): String =
    if (attachment.kind == "image" && attachment.mime.startsWith("image/")) attachment.mime
    else "application/octet-stream"
