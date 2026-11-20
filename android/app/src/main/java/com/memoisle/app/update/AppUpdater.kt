package com.memoisle.app.update

import android.content.Context
import android.content.Intent
import android.provider.Settings
import androidx.core.content.FileProvider
import androidx.core.net.toUri
import com.memoisle.app.BuildConfig
import com.memoisle.app.data.AndroidRelease
import com.memoisle.app.data.isStaleUpdateFile
import com.memoisle.app.data.updateApkFileName
import com.memoisle.app.network.MemoApiClient
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext

/** 下载的安装包与服务端公布的大小或 SHA-256 对不上。 */
class UpdateVerificationException(message: String) : IOException(message)

/**
 * 下载、校验并交给系统安装器安装新版 APK。
 * 普通应用不能静默安装，最后一步总是由用户在系统安装界面确认。
 */
class AppUpdater(
    context: Context,
    private val api: MemoApiClient,
) {
    private val appContext = context.applicationContext
    private val updateDirectory = File(appContext.cacheDir, UPDATE_DIRECTORY)

    val currentVersionCode: Int get() = BuildConfig.VERSION_CODE
    val currentVersionName: String get() = BuildConfig.VERSION_NAME

    suspend fun fetchLatest(): AndroidRelease? = withContext(Dispatchers.IO) {
        api.getLatestAndroidRelease()
    }

    /** 删掉下载到一半的临时文件和不比本机新的旧更新包。 */
    suspend fun cleanup() = withContext(Dispatchers.IO) {
        updateDirectory.listFiles()?.forEach { file ->
            if (isStaleUpdateFile(file.name, currentVersionCode)) {
                file.delete()
            }
        }
    }

    /**
     * 下载到临时文件，大小与 SHA-256 都和服务端一致后才改成正式文件名。
     * 已经下载并校验过的同版本文件直接复用。失败或取消时删除临时文件。
     */
    suspend fun download(
        release: AndroidRelease,
        onProgress: (downloaded: Long, total: Long) -> Unit,
    ): File = withContext(Dispatchers.IO) {
        updateDirectory.mkdirs()
        val target = File(updateDirectory, updateApkFileName(release.versionCode))
        if (target.isFile && target.length() == release.size && sha256(target) == release.sha256) {
            onProgress(release.size, release.size)
            return@withContext target
        }
        target.delete()
        val partial = File(updateDirectory, "${target.name}.part")
        val downloadContext = coroutineContext
        try {
            api.downloadApk(partial.toPath()) { downloaded, total ->
                downloadContext.ensureActive()
                onProgress(downloaded, if (total > 0) total else release.size)
            }
            downloadContext.ensureActive()
            if (partial.length() != release.size) {
                throw UpdateVerificationException("安装包大小不一致，已删除，请稍后重试")
            }
            if (sha256(partial) != release.sha256) {
                throw UpdateVerificationException("安装包校验失败，已删除，请稍后重试")
            }
            Files.move(partial.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING)
            target
        } finally {
            partial.delete()
        }
    }

    /** Android 8 起要用户单独允许本应用安装未知来源应用。 */
    fun canRequestPackageInstalls(): Boolean = appContext.packageManager.canRequestPackageInstalls()

    fun unknownSourcesSettingsIntent(): Intent = Intent(
        Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
        "package:${appContext.packageName}".toUri(),
    )

    /** 通过 FileProvider 生成 content Uri，交给系统安装器，并只临时授予读权限。 */
    fun installIntent(apk: File): Intent {
        val uri = FileProvider.getUriForFile(
            appContext,
            "${appContext.packageName}$AUTHORITY_SUFFIX",
            apk,
        )
        return Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, APK_MIME_TYPE)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    companion object {
        /** 与 res/xml/update_file_paths.xml 中开放的目录一致。 */
        const val UPDATE_DIRECTORY = "updates"

        /** 与 AndroidManifest 中 `${applicationId}.updates` 一致，debug 包带后缀不会冲突。 */
        const val AUTHORITY_SUFFIX = ".updates"
        const val APK_MIME_TYPE = "application/vnd.android.package-archive"
    }
}
