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

    fun start(): Boolean {
        if (recorder != null) {
            return false
        }
        val audioDirectory = context.cacheDir.toPath().resolve("voice-drafts")
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
        val durationMs = (SystemClock.elapsedRealtime() - startedAtMs)
            .coerceAtMost(Int.MAX_VALUE.toLong())
            .toInt()
        return runCatching {
            activeRecorder.stop()
            activeRecorder.release()
            recorder = null
            outputPath = null
            VoiceRecording(path = activePath.toString(), durationMs = durationMs)
        }.getOrElse {
            activeRecorder.release()
            recorder = null
            outputPath = null
            Files.deleteIfExists(activePath)
            null
        }
    }

    fun cancel() {
        val activeRecorder = recorder
        val activePath = outputPath
        if (activeRecorder != null) {
            runCatching { activeRecorder.stop() }
            activeRecorder.release()
        }
        recorder = null
        outputPath = null
        if (activePath != null) {
            Files.deleteIfExists(activePath)
        }
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
