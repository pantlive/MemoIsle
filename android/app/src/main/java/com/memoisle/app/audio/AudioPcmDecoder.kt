package com.memoisle.app.audio

import android.media.AudioFormat
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import java.nio.ByteOrder
import java.nio.file.Files
import java.nio.file.Path
import kotlin.math.ceil
import kotlin.math.floor

/**
 * 解码录音为 sherpa-onnx 所需的单声道 Float32 波形。
 *
 * MediaRecorder 生成的是 AAC/M4A，不能直接交给 WaveReader，因此这里使用
 * Android 系统解码器把它转成 PCM，并在最后统一重采样到 16 kHz。
 */
object AudioPcmDecoder {
    private const val DEFAULT_SAMPLE_RATE = 16_000
    private const val BUFFER_TIMEOUT_US = 10_000L

    fun decode(path: Path, targetSampleRate: Int = DEFAULT_SAMPLE_RATE): FloatArray {
        require(targetSampleRate > 0) { "目标采样率必须大于 0" }
        require(Files.isRegularFile(path)) { "录音文件不存在" }

        val extractor = MediaExtractor()
        var codec: MediaCodec? = null
        try {
            extractor.setDataSource(path.toString())
            val trackIndex = findAudioTrack(extractor)
            require(trackIndex >= 0) { "录音不包含音频轨道" }
            extractor.selectTrack(trackIndex)
            val inputFormat = extractor.getTrackFormat(trackIndex)
            val mimeType = inputFormat.getString(MediaFormat.KEY_MIME)
                ?: error("录音格式缺少 MIME 类型")
            codec = MediaCodec.createDecoderByType(mimeType)
            codec.configure(inputFormat, null, null, 0)
            codec.start()

            val samples = FloatAccumulator()
            val bufferInfo = MediaCodec.BufferInfo()
            var inputEnded = false
            var outputEnded = false
            var sampleRate = inputFormat.getIntegerOrDefault(
                MediaFormat.KEY_SAMPLE_RATE,
                DEFAULT_SAMPLE_RATE,
            )
            var channelCount = inputFormat.getIntegerOrDefault(
                MediaFormat.KEY_CHANNEL_COUNT,
                1,
            ).coerceAtLeast(1)
            var pcmEncoding = AudioFormat.ENCODING_PCM_16BIT

            while (!outputEnded) {
                if (!inputEnded) {
                    val inputIndex = codec.dequeueInputBuffer(BUFFER_TIMEOUT_US)
                    if (inputIndex >= 0) {
                        val inputBuffer = codec.getInputBuffer(inputIndex)
                            ?: error("无法获取解码输入缓冲区")
                        inputBuffer.clear()
                        val sampleSize = extractor.readSampleData(inputBuffer, 0)
                        if (sampleSize < 0) {
                            codec.queueInputBuffer(
                                inputIndex,
                                0,
                                0,
                                0,
                                MediaCodec.BUFFER_FLAG_END_OF_STREAM,
                            )
                            inputEnded = true
                        } else {
                            codec.queueInputBuffer(
                                inputIndex,
                                0,
                                sampleSize,
                                extractor.sampleTime.coerceAtLeast(0L),
                                0,
                            )
                            extractor.advance()
                        }
                    }
                }

                when (val outputIndex = codec.dequeueOutputBuffer(bufferInfo, BUFFER_TIMEOUT_US)) {
                    MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                        val outputFormat = codec.outputFormat
                        sampleRate = outputFormat.getIntegerOrDefault(
                            MediaFormat.KEY_SAMPLE_RATE,
                            sampleRate,
                        )
                        channelCount = outputFormat.getIntegerOrDefault(
                            MediaFormat.KEY_CHANNEL_COUNT,
                            channelCount,
                        ).coerceAtLeast(1)
                        pcmEncoding = outputFormat.getIntegerOrDefault(
                            MediaFormat.KEY_PCM_ENCODING,
                            AudioFormat.ENCODING_PCM_16BIT,
                        )
                    }

                    MediaCodec.INFO_TRY_AGAIN_LATER -> Unit

                    else -> {
                        if (outputIndex < 0) {
                            continue
                        }
                        val outputBuffer = codec.getOutputBuffer(outputIndex)
                        if (outputBuffer != null && bufferInfo.size > 0) {
                            appendPcm(
                                samples = samples,
                                buffer = outputBuffer,
                                offset = bufferInfo.offset,
                                size = bufferInfo.size,
                                channelCount = channelCount,
                                pcmEncoding = pcmEncoding,
                            )
                        }
                        codec.releaseOutputBuffer(outputIndex, false)
                        if (bufferInfo.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) {
                            outputEnded = true
                        }
                    }
                }
            }
            require(samples.size > 0) { "录音没有可用的 PCM 数据" }
            return resample(samples.toArray(), sampleRate, targetSampleRate)
        } finally {
            runCatching { codec?.stop() }
            runCatching { codec?.release() }
            extractor.release()
        }
    }

    private fun findAudioTrack(extractor: MediaExtractor): Int {
        for (index in 0 until extractor.trackCount) {
            val format = extractor.getTrackFormat(index)
            if (format.getString(MediaFormat.KEY_MIME)?.startsWith("audio/") == true) {
                return index
            }
        }
        return -1
    }

    private fun appendPcm(
        samples: FloatAccumulator,
        buffer: java.nio.ByteBuffer,
        offset: Int,
        size: Int,
        channelCount: Int,
        pcmEncoding: Int,
    ): Unit {
        val pcm = buffer.duplicate()
            .order(ByteOrder.LITTLE_ENDIAN)
            .apply {
                position(offset)
                limit(offset + size)
            }
        val bytesPerSample = if (pcmEncoding == AudioFormat.ENCODING_PCM_FLOAT) 4 else 2
        val frameSize = bytesPerSample * channelCount
        while (pcm.remaining() >= frameSize) {
            var mixed = 0.0f
            repeat(channelCount) {
                mixed += if (bytesPerSample == 4) {
                    pcm.float
                } else {
                    pcm.short / 32_768.0f
                }
            }
            samples.add((mixed / channelCount).coerceIn(-1.0f, 1.0f))
        }
    }

    private fun resample(
        source: FloatArray,
        sourceSampleRate: Int,
        targetSampleRate: Int,
    ): FloatArray {
        if (sourceSampleRate == targetSampleRate) {
            return source
        }
        require(sourceSampleRate > 0) { "源采样率无效" }
        val targetSize = ceil(
            source.size.toDouble() * targetSampleRate / sourceSampleRate,
        ).toInt()
        return FloatArray(targetSize) { index ->
            val sourcePosition = index.toDouble() * sourceSampleRate / targetSampleRate
            val leftIndex = floor(sourcePosition).toInt().coerceIn(0, source.lastIndex)
            val rightIndex = (leftIndex + 1).coerceAtMost(source.lastIndex)
            val fraction = (sourcePosition - leftIndex).toFloat()
            source[leftIndex] + (source[rightIndex] - source[leftIndex]) * fraction
        }
    }

    private fun MediaFormat.getIntegerOrDefault(key: String, default: Int): Int {
        return if (containsKey(key)) getInteger(key) else default
    }

    private class FloatAccumulator(initialCapacity: Int = 16_000) {
        private var values = FloatArray(initialCapacity)
        var size: Int = 0
            private set

        fun add(value: Float): Unit {
            if (size == values.size) {
                values = values.copyOf(values.size * 2)
            }
            values[size] = value
            size += 1
        }

        fun toArray(): FloatArray = values.copyOf(size)
    }
}
