package com.memoisle.app.audio

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import android.os.SystemClock
import java.nio.file.Files
import java.nio.file.Path
import java.util.UUID

data class VoiceRecording(
    val path: String,
    val durationMs: Int,
)

class VoiceRecorder(private val context: Context) {
    private var recorder: MediaRecorder? = null
    private var outputPath: Path? = null
    private var startedAtMs: Long = 0
    private var pausedAtMs: Long? = null
    private var pausedTotalMs: Long = 0

    fun start(): Boolean {
        if (recorder != null) {
            return false
        }
        // 录音属于待同步用户数据，不能放在可被系统清理的缓存目录。
        // noBackupFilesDir 保证跨进程和重启可恢复，同时避免把私人录音自动备份到云端。
        val audioDirectory = context.noBackupFilesDir.toPath().resolve("voice-drafts")
        Files.createDirectories(audioDirectory)
        val path = audioDirectory.resolve("${UUID.randomUUID()}.m4a")
        val newRecorder = createRecorder()
        return runCatching {
            // Android 端统一生成 AAC/M4A，服务端按 audio/mp4 接收。
            newRecorder.setAudioSource(MediaRecorder.AudioSource.MIC)
            newRecorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            newRecorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            newRecorder.setAudioEncodingBitRate(96_000)
            newRecorder.setAudioSamplingRate(44_100)
            newRecorder.setMaxDuration(10 * 60 * 1000)
            newRecorder.setOutputFile(path.toString())
            newRecorder.prepare()
            newRecorder.start()
            recorder = newRecorder
            outputPath = path
            startedAtMs = SystemClock.elapsedRealtime()
            pausedAtMs = null
            pausedTotalMs = 0
            true
        }.getOrElse {
            newRecorder.release()
            Files.deleteIfExists(path)
            false
        }
    }

    fun stop(): VoiceRecording? {
        val activeRecorder = recorder ?: return null
        val activePath = outputPath ?: return null
        val durationMs = elapsedMs()
        return runCatching {
            activeRecorder.stop()
            activeRecorder.release()
            clearState()
            VoiceRecording(path = activePath.toString(), durationMs = durationMs)
        }.getOrElse {
            activeRecorder.release()
            clearState()
            Files.deleteIfExists(activePath)
            null
        }
    }

    fun pause(): Boolean {
        val activeRecorder = recorder ?: return false
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            return false
        }
        if (pausedAtMs != null) {
            return true
        }
        return runCatching {
            // 暂停计时从 MediaRecorder 成功暂停后开始，避免把失败调用算入时长。
            activeRecorder.pause()
            pausedAtMs = SystemClock.elapsedRealtime()
            true
        }.getOrDefault(false)
    }

    fun resume(): Boolean {
        val activeRecorder = recorder ?: return false
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) {
            return false
        }
        val pausedAt = pausedAtMs ?: return false
        return runCatching {
            activeRecorder.resume()
            pausedTotalMs += SystemClock.elapsedRealtime() - pausedAt
            pausedAtMs = null
            true
        }.getOrDefault(false)
    }

    fun amplitudePercent(): Int {
        val activeRecorder = recorder ?: return 0
        // maxAmplitude 是当前采样窗口峰值，用于界面反馈而不是录音质量判断。
        val amplitude = runCatching { activeRecorder.maxAmplitude }.getOrDefault(0)
        return (amplitude.toLong() * 100L / 32_767L).toInt().coerceIn(0, 100)
    }

    fun elapsedMs(): Int {
        // 公开有效录音时长，暂停期间不会累加。
        return elapsedDurationMs()
            .coerceAtMost(Int.MAX_VALUE.toLong())
            .toInt()
    }

    fun cancel() {
        val activeRecorder = recorder
        val activePath = outputPath
        if (activeRecorder != null) {
            runCatching { activeRecorder.stop() }
            activeRecorder.release()
        }
        clearState()
        if (activePath != null) {
            Files.deleteIfExists(activePath)
        }
    }

    private fun elapsedDurationMs(): Long {
        val now = SystemClock.elapsedRealtime()
        val activePausedMs = pausedAtMs?.let { now - it } ?: 0
        return (now - startedAtMs - pausedTotalMs - activePausedMs).coerceAtLeast(0)
    }

    private fun clearState() {
        recorder = null
        outputPath = null
        startedAtMs = 0
        pausedAtMs = null
        pausedTotalMs = 0
    }

    @Suppress("DEPRECATION")
    private fun createRecorder(): MediaRecorder {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            MediaRecorder(context)
        } else {
            MediaRecorder()
        }
    }
}
