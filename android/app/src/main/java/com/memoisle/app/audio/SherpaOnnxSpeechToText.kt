package com.memoisle.app.audio

import android.content.Context
import com.k2fsa.sherpa.onnx.FeatureConfig
import com.k2fsa.sherpa.onnx.OfflineModelConfig
import com.k2fsa.sherpa.onnx.OfflineRecognizer
import com.k2fsa.sherpa.onnx.OfflineRecognizerConfig
import com.k2fsa.sherpa.onnx.OfflineSenseVoiceModelConfig
import com.memoisle.app.BuildConfig
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.nio.file.AtomicMoveNotSupportedException
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption
import java.nio.file.StandardOpenOption
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import kotlin.coroutines.cancellation.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.apache.commons.compress.archivers.tar.TarArchiveInputStream
import org.apache.commons.compress.compressors.bzip2.BZip2CompressorInputStream

interface SpeechToTextEngine {
    val isAvailable: Boolean

    suspend fun ensureAvailable(): Result<Unit>

    suspend fun transcribe(audioPath: Path): Result<String>
}

class SpeechModelMissingException : IllegalStateException(
    "设备端语音模型尚未安装，请联网后重试",
)

class SpeechModelDownloadException(cause: Throwable) : IllegalStateException(
    "设备端语音模型下载失败，请检查网络后重试",
    cause,
)

/**
 * 使用 sherpa-onnx SenseVoiceSmall INT8 在设备端完成录音转写。
 *
 * Debug 可以从 assets 读取模型，Release 默认在首次使用时下载到 noBackupFilesDir。
 * 推理固定使用 CPU；sherpa-onnx 自己负责 ONNX Runtime 调度，应用层不绑定具体硬件。
 * Recognizer 不是线程安全的，所以同一个实例上的解码操作统一串行化。
 */
class SherpaOnnxSpeechToText(context: Context) : SpeechToTextEngine, AutoCloseable {
    companion object {
        private const val MODEL_DIRECTORY = "models/sensevoice"
        private const val MODEL_ASSET = "$MODEL_DIRECTORY/model.int8.onnx"
        private const val TOKENS_ASSET = "$MODEL_DIRECTORY/tokens.txt"
        private const val MODEL_FILE_NAME = "model.int8.onnx"
        private const val TOKENS_FILE_NAME = "tokens.txt"
        private const val ARCHIVE_MODEL_DIRECTORY =
            "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
        private const val READY_MARKER = ".ready"
        private const val SAMPLE_RATE = 16_000
        private const val MAX_ARCHIVE_BYTES = 220L * 1024L * 1024L
        private const val MAX_MODEL_BYTES = 350L * 1024L * 1024L
        private const val MAX_TOKENS_BYTES = 2L * 1024L * 1024L
        private const val MODEL_SHA256 =
            "c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51"
        private const val TOKENS_SHA256 =
            "f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc"
    }

    private val appContext = context.applicationContext
    private val recognizerLock = Any()
    private val modelDownloadLock = Mutex()
    private val downloadedModelDirectory = appContext.noBackupFilesDir.toPath()
        .resolve(MODEL_DIRECTORY)
    private val downloadedModelPath = downloadedModelDirectory.resolve(MODEL_FILE_NAME)
    private val downloadedTokensPath = downloadedModelDirectory.resolve(TOKENS_FILE_NAME)
    private val readyMarkerPath = downloadedModelDirectory.resolve(READY_MARKER)
    private var recognizer: OfflineRecognizer? = null

    override val isAvailable: Boolean
        get() = hasModelAssets() || hasDownloadedModel()

    override suspend fun ensureAvailable(): Result<Unit> {
        if (isAvailable) {
            return Result.success(Unit)
        }
        return withContext(Dispatchers.IO) {
            modelDownloadLock.withLock {
                if (isAvailable) {
                    Result.success(Unit)
                } else {
                    try {
                        downloadAndInstallModel()
                        Result.success(Unit)
                    } catch (error: CancellationException) {
                        throw error
                    } catch (error: Throwable) {
                        Result.failure(SpeechModelDownloadException(error))
                    }
                }
            }
        }
    }

    override suspend fun transcribe(audioPath: Path): Result<String> {
        return withContext(Dispatchers.Default) {
            if (!isAvailable) {
                return@withContext Result.failure(SpeechModelMissingException())
            }
            runCatching {
                val waveform = AudioPcmDecoder.decode(audioPath, SAMPLE_RATE)
                require(waveform.isNotEmpty()) { "录音内容为空" }
                synchronized(recognizerLock) {
                    val activeRecognizer = getRecognizer()
                    val stream = activeRecognizer.createStream()
                    try {
                        stream.acceptWaveform(waveform, SAMPLE_RATE)
                        activeRecognizer.decode(stream)
                        activeRecognizer.getResult(stream).text.trim()
                    } finally {
                        stream.release()
                    }
                }.also { text ->
                    require(text.isNotBlank()) { "没有识别到语音内容" }
                }
            }
        }
    }

    override fun close(): Unit {
        synchronized(recognizerLock) {
            recognizer?.release()
            recognizer = null
        }
    }

    private fun getRecognizer(): OfflineRecognizer {
        recognizer?.let { return it }
        val modelPath: String
        val tokensPath: String
        val assetManager = if (hasModelAssets()) {
            modelPath = MODEL_ASSET
            tokensPath = TOKENS_ASSET
            appContext.assets
        } else if (hasDownloadedModel()) {
            modelPath = downloadedModelPath.toString()
            tokensPath = downloadedTokensPath.toString()
            null
        } else {
            throw SpeechModelMissingException()
        }
        val modelConfig = OfflineModelConfig(
            senseVoice = OfflineSenseVoiceModelConfig(
                model = modelPath,
                language = "",
                useInverseTextNormalization = true,
            ),
            numThreads = Runtime.getRuntime().availableProcessors().coerceIn(1, 4),
            provider = "cpu",
            tokens = tokensPath,
        )
        val config = OfflineRecognizerConfig(
            featConfig = FeatureConfig(
                sampleRate = SAMPLE_RATE,
                featureDim = 80,
                dither = 0.0f,
            ),
            modelConfig = modelConfig,
            decodingMethod = "greedy_search",
        )
        return OfflineRecognizer(assetManager, config).also { recognizer = it }
    }

    private fun hasModelAssets(): Boolean {
        val files = runCatching { appContext.assets.list(MODEL_DIRECTORY).orEmpty().toSet() }
            .getOrDefault(emptySet())
        return files.contains(MODEL_ASSET.substringAfterLast('/')) &&
            files.contains(TOKENS_ASSET.substringAfterLast('/'))
    }

    private fun hasDownloadedModel(): Boolean {
        if (!Files.isRegularFile(readyMarkerPath) ||
            !Files.isRegularFile(downloadedModelPath) ||
            !Files.isRegularFile(downloadedTokensPath)
        ) {
            return false
        }
        return runCatching {
            Files.newBufferedReader(readyMarkerPath, StandardCharsets.UTF_8).use {
                it.readText()
            } == "$MODEL_SHA256\n$TOKENS_SHA256\n" &&
                Files.size(downloadedModelPath) > 0L &&
                Files.size(downloadedTokensPath) > 0L
        }.getOrDefault(false)
    }

    private suspend fun downloadAndInstallModel(): Unit {
        Files.createDirectories(downloadedModelDirectory)
        val archivePath = downloadedModelDirectory.resolve("model.tar.bz2.part")
        val modelPartPath = downloadedModelDirectory.resolve("$MODEL_FILE_NAME.part")
        val tokensPartPath = downloadedModelDirectory.resolve("$TOKENS_FILE_NAME.part")
        try {
            downloadArchive(archivePath)
            extractModelFiles(archivePath, modelPartPath, tokensPartPath)
            verifyFile(modelPartPath, MODEL_SHA256, MAX_MODEL_BYTES)
            verifyFile(tokensPartPath, TOKENS_SHA256, MAX_TOKENS_BYTES)
            // 先移除完成标记，进程中断时不会把半成品当成可用模型。
            Files.deleteIfExists(readyMarkerPath)
            moveIntoPlace(modelPartPath, downloadedModelPath)
            moveIntoPlace(tokensPartPath, downloadedTokensPath)
            Files.newBufferedWriter(
                readyMarkerPath,
                StandardCharsets.UTF_8,
                StandardOpenOption.CREATE,
                StandardOpenOption.TRUNCATE_EXISTING,
                StandardOpenOption.WRITE,
            ).use { writer -> writer.write("$MODEL_SHA256\n$TOKENS_SHA256\n") }
        } finally {
            Files.deleteIfExists(archivePath)
            Files.deleteIfExists(modelPartPath)
            Files.deleteIfExists(tokensPartPath)
        }
    }

    private suspend fun downloadArchive(target: Path): Unit {
        val connection = (URL(BuildConfig.SENSEVOICE_MODEL_ARCHIVE_URL)
            .openConnection() as HttpURLConnection)
        try {
            connection.requestMethod = "GET"
            connection.connectTimeout = 15_000
            connection.readTimeout = 60_000
            connection.instanceFollowRedirects = true
            connection.setRequestProperty("Accept", "application/octet-stream")
            val statusCode = connection.responseCode
            require(statusCode in 200..299) { "模型下载服务返回 HTTP $statusCode" }
            val contentLength = connection.contentLengthLong
            require(contentLength <= MAX_ARCHIVE_BYTES || contentLength < 0L) {
                "模型压缩包超过大小限制"
            }
            BufferedInputStream(connection.inputStream).use { input ->
                BufferedOutputStream(
                    Files.newOutputStream(
                        target,
                        StandardOpenOption.CREATE,
                        StandardOpenOption.TRUNCATE_EXISTING,
                        StandardOpenOption.WRITE,
                    ),
                ).use { output ->
                    val buffer = ByteArray(64 * 1024)
                    var total = 0L
                    while (true) {
                        currentCoroutineContext().ensureActive()
                        val count = input.read(buffer)
                        if (count < 0) {
                            break
                        }
                        total += count
                        require(total <= MAX_ARCHIVE_BYTES) { "模型压缩包超过大小限制" }
                        output.write(buffer, 0, count)
                    }
                }
            }
        } finally {
            connection.disconnect()
        }
    }

    private suspend fun extractModelFiles(
        archivePath: Path,
        modelPartPath: Path,
        tokensPartPath: Path,
    ): Unit {
        var modelFound = false
        var tokensFound = false
        BZip2CompressorInputStream(
            BufferedInputStream(Files.newInputStream(archivePath)),
        ).use { compressed ->
            TarArchiveInputStream(compressed).use { archive ->
                while (true) {
                    currentCoroutineContext().ensureActive()
                    val entry = archive.nextEntry ?: break
                    if (entry.isDirectory) {
                        continue
                    }
                    val entryName = entry.name.replace('\\', '/')
                    when (entryName) {
                        "$ARCHIVE_MODEL_DIRECTORY/$MODEL_FILE_NAME",
                        MODEL_FILE_NAME,
                        -> {
                            require(!modelFound) { "模型压缩包包含重复模型文件" }
                            require(entry.isFile) { "模型文件不是普通文件" }
                            copyArchiveEntry(archive, modelPartPath, MAX_MODEL_BYTES)
                            modelFound = true
                        }
                        "$ARCHIVE_MODEL_DIRECTORY/$TOKENS_FILE_NAME",
                        TOKENS_FILE_NAME,
                        -> {
                            require(!tokensFound) { "模型压缩包包含重复词表文件" }
                            require(entry.isFile) { "词表文件不是普通文件" }
                            copyArchiveEntry(archive, tokensPartPath, MAX_TOKENS_BYTES)
                            tokensFound = true
                        }
                    }
                }
            }
        }
        require(modelFound && tokensFound) { "模型压缩包缺少 SenseVoice 文件" }
    }

    private suspend fun copyArchiveEntry(
        archive: TarArchiveInputStream,
        target: Path,
        maxBytes: Long,
    ): Unit {
        BufferedOutputStream(
            Files.newOutputStream(
                target,
                StandardOpenOption.CREATE,
                StandardOpenOption.TRUNCATE_EXISTING,
                StandardOpenOption.WRITE,
            ),
        ).use { output ->
            val buffer = ByteArray(64 * 1024)
            var total = 0L
            while (true) {
                currentCoroutineContext().ensureActive()
                val count = archive.read(buffer)
                if (count < 0) {
                    break
                }
                total += count
                require(total <= maxBytes) { "模型文件超过大小限制" }
                output.write(buffer, 0, count)
            }
        }
    }

    private fun verifyFile(path: Path, expectedSha256: String, maxBytes: Long): Unit {
        require(Files.isRegularFile(path)) { "模型文件未成功解压" }
        require(Files.size(path) in 1..maxBytes) { "模型文件大小无效" }
        require(sha256(path) == expectedSha256) { "模型文件校验失败" }
    }

    private fun sha256(path: Path): String {
        val digest = MessageDigest.getInstance("SHA-256")
        Files.newInputStream(path).use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) {
                    break
                }
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { byte ->
            "%02x".format(byte.toInt() and 0xff)
        }
    }

    private fun moveIntoPlace(source: Path, target: Path): Unit {
        try {
            Files.move(
                source,
                target,
                StandardCopyOption.ATOMIC_MOVE,
                StandardCopyOption.REPLACE_EXISTING,
            )
        } catch (_: AtomicMoveNotSupportedException) {
            Files.move(source, target, StandardCopyOption.REPLACE_EXISTING)
        }
    }
}
