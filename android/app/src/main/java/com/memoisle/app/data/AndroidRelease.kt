package com.memoisle.app.data

import org.json.JSONObject

/** 自动检查最多每 24 小时一次。 */
const val UPDATE_AUTO_CHECK_INTERVAL_MS = 24L * 60 * 60 * 1000

private const val UPDATE_APK_PREFIX = "memoisle-"
private const val UPDATE_APK_SUFFIX = ".apk"
private val SHA256_PATTERN = Regex("^[0-9a-f]{64}$")

/**
 * 服务端 `GET /android/latest` 返回的已发布安装包信息。
 * [downloadUrl] 是相对 API 根地址的路径，客户端只用固定的下载接口，不跟随任意地址。
 */
data class AndroidRelease(
    val versionCode: Int,
    val versionName: String,
    val sha256: String,
    val size: Long,
    val releaseNotes: String,
    val downloadUrl: String,
) {
    companion object {
        /** 字段缺失或明显不合法时返回 null，按「没有可用更新」处理。 */
        fun fromJson(json: JSONObject): AndroidRelease? {
            val versionCode = json.opt("version_code") as? Number ?: return null
            val versionName = json.optStringOrNull("version_name")?.trim()?.ifEmpty { null } ?: return null
            val sha256 = json.optStringOrNull("sha256")?.trim()?.lowercase() ?: return null
            val size = json.opt("size") as? Number ?: return null
            val code = versionCode.toInt()
            if (code <= 0 || code.toDouble() != versionCode.toDouble()) return null
            if (!SHA256_PATTERN.matches(sha256)) return null
            if (size.toLong() <= 0) return null
            return AndroidRelease(
                versionCode = code,
                versionName = versionName,
                sha256 = sha256,
                size = size.toLong(),
                releaseNotes = json.optStringOrNull("release_notes")?.trim().orEmpty(),
                downloadUrl = json.optStringOrNull("download_url")?.trim()?.ifEmpty { null }
                    ?: "android/download",
            )
        }
    }
}

private fun JSONObject.optStringOrNull(name: String): String? =
    if (!has(name) || isNull(name)) null else opt(name) as? String

/** 服务端版本比本机新才算有更新。 */
fun isNewerRelease(release: AndroidRelease, currentVersionCode: Int): Boolean =
    release.versionCode > currentVersionCode

/**
 * 是否弹出更新提示。手动检查只看是否更新；
 * 自动检查还要跳过用户点过「忽略此版本」的那个 versionCode。
 */
fun shouldPromptRelease(
    release: AndroidRelease,
    currentVersionCode: Int,
    ignoredVersionCode: Int?,
    manual: Boolean,
): Boolean {
    if (!isNewerRelease(release, currentVersionCode)) return false
    return manual || release.versionCode != ignoredVersionCode
}

/** 距上次自动检查满 24 小时才再查；系统时间被往回调时也重新检查。 */
fun shouldAutoCheck(
    lastCheckedAtMs: Long,
    nowMs: Long,
    intervalMs: Long = UPDATE_AUTO_CHECK_INTERVAL_MS,
): Boolean = lastCheckedAtMs <= 0 || nowMs < lastCheckedAtMs || nowMs - lastCheckedAtMs >= intervalMs

/** 下载完成并校验通过的更新包文件名。 */
fun updateApkFileName(versionCode: Int): String = "$UPDATE_APK_PREFIX$versionCode$UPDATE_APK_SUFFIX"

/** 从更新包文件名取回 versionCode，不是更新包时返回 null。 */
fun updateApkVersionCode(fileName: String): Int? {
    if (!fileName.startsWith(UPDATE_APK_PREFIX) || !fileName.endsWith(UPDATE_APK_SUFFIX)) return null
    return fileName.removePrefix(UPDATE_APK_PREFIX).removeSuffix(UPDATE_APK_SUFFIX).toIntOrNull()
}

/** 启动清理时只保留比本机新、且已校验完成的更新包，下载到一半的临时文件和旧包都删掉。 */
fun isStaleUpdateFile(fileName: String, currentVersionCode: Int): Boolean {
    val versionCode = updateApkVersionCode(fileName) ?: return true
    return versionCode <= currentVersionCode
}
