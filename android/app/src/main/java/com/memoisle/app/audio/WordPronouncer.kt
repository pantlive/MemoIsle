package com.memoisle.app.audio

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import com.memoisle.app.network.MemoApiClient
import java.io.File
import java.net.HttpURLConnection
import java.net.URI
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.Locale
import java.util.concurrent.Executors

private const val YOUDAO_VOICE_URL = "https://dict.youdao.com/dictvoice"

fun youdaoVoiceUrl(lemma: String, locale: Locale): String {
    val voiceType = if (isBritish(locale)) 1 else 2
    val encoded = URLEncoder
        .encode(lemma.trim(), StandardCharsets.UTF_8.name())
        .replace("+", "%20")
    return "$YOUDAO_VOICE_URL?audio=$encoded&type=$voiceType"
}

private fun isBritish(locale: Locale): Boolean {
    return locale.country.equals("GB", ignoreCase = true) || locale == Locale.UK
}

class WordPronouncer(
    context: Context,
    private val apiClient: MemoApiClient? = null,
) {
    private val appContext = context.applicationContext
    private val mainHandler = Handler(Looper.getMainLooper())
    private val executor = Executors.newSingleThreadExecutor()
    private var player: MediaPlayer? = null
    private var tts: TextToSpeech? = null
    private var usReady = false
    private var ukReady = false
    private var generation = 0
    private var onPlaying: ((Boolean) -> Unit)? = null

    init {
        prepareTts()
    }

    private fun prepareTts() {
        if (tts != null) {
            return
        }
        tts = TextToSpeech(appContext) { status ->
            if (status != TextToSpeech.SUCCESS) {
                return@TextToSpeech
            }
            val engine = tts ?: return@TextToSpeech
            usReady = engine.isLanguageAvailable(Locale.US) >= TextToSpeech.LANG_AVAILABLE
            ukReady = engine.isLanguageAvailable(Locale.UK) >= TextToSpeech.LANG_AVAILABLE
            engine.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                override fun onStart(utteranceId: String?) = Unit

                override fun onDone(utteranceId: String?) {
                    finishIfCurrent(utteranceId)
                }

                @Deprecated("Deprecated in Java")
                override fun onError(utteranceId: String?) {
                    finishIfCurrent(utteranceId)
                }

                override fun onError(utteranceId: String?, errorCode: Int) {
                    finishIfCurrent(utteranceId)
                }
            })
        }
    }

    fun play(lemma: String, locale: Locale, preferredUrl: String?, onPlaying: (Boolean) -> Unit) {
        val cleaned = lemma.trim()
        if (cleaned.isEmpty()) {
            return
        }
        val token = ++generation
        releasePlayer()
        tts?.stop()
        this.onPlaying = onPlaying
        notifyPlaying(true)
        val audioUrl = preferredUrl?.takeIf { it.isNotBlank() } ?: youdaoVoiceUrl(cleaned, locale)
        startAudio(audioUrl, token, cleaned, locale, triedYoudao = audioUrl.contains("dict.youdao.com"))
    }

    fun playText(text: String, locale: Locale, onPlaying: (Boolean) -> Unit) {
        val cleaned = text.trim()
        if (cleaned.isEmpty()) {
            return
        }
        val token = ++generation
        releasePlayer()
        tts?.stop()
        this.onPlaying = onPlaying
        notifyPlaying(true)
        startServerTts(cleaned, token, locale)
    }

    fun release() {
        onPlaying = null
        generation += 1
        releasePlayer()
        tts?.stop()
        tts?.shutdown()
        tts = null
        executor.shutdownNow()
    }

    private fun startAudio(
        audioUrl: String,
        token: Int,
        lemma: String,
        locale: Locale,
        triedYoudao: Boolean,
    ) {
        executor.execute {
            val file = downloadAudio(audioUrl, token)
            mainHandler.post {
                if (token != generation) {
                    return@post
                }
                if (file != null && playFile(
                        file,
                        token,
                        lemma,
                        locale,
                        triedYoudao = triedYoudao,
                        triedServerTts = false,
                    )
                ) {
                    return@post
                }
                val youdaoUrl = youdaoVoiceUrl(lemma, locale)
                if (!triedYoudao && audioUrl != youdaoUrl) {
                    startAudio(youdaoUrl, token, lemma, locale, triedYoudao = true)
                    return@post
                }
                if (apiClient != null) {
                    startServerTts(lemma, token, locale)
                } else if (!speakTts(lemma, locale, token)) {
                    notifyPlaying(false)
                }
            }
        }
    }

    private fun startServerTts(text: String, token: Int, locale: Locale) {
        val client = apiClient
        if (client == null) {
            if (!speakTts(text, locale, token)) {
                notifyPlaying(false)
            }
            return
        }
        executor.execute {
            val file = runCatching {
                val audio = client.synthesizeSpeech(text)
                if (token != generation || audio.isEmpty()) {
                    return@runCatching null
                }
                val target = File(appContext.cacheDir, "memoisle-speech-$token.wav")
                target.outputStream().use { output -> output.write(audio) }
                target.takeIf { it.length() > 44 }
            }.getOrNull()
            mainHandler.post {
                if (token != generation) {
                    return@post
                }
                if (file != null && playFile(
                        file,
                        token,
                        text,
                        locale,
                        triedYoudao = true,
                        triedServerTts = true,
                    )
                ) {
                    return@post
                }
                if (!speakTts(text, locale, token)) {
                    notifyPlaying(false)
                }
            }
        }
    }

    private fun downloadAudio(audioUrl: String, token: Int): File? {
        return runCatching {
            val connection = URI.create(audioUrl).toURL().openConnection() as HttpURLConnection
            try {
                connection.connectTimeout = 5_000
                connection.readTimeout = 8_000
                connection.instanceFollowRedirects = true
                connection.setRequestProperty("User-Agent", "MemoIsle/0.1 (word pronunciation)")
                if (connection.responseCode !in 200..299) {
                    return@runCatching null
                }
                val contentType = connection.contentType.orEmpty()
                if (contentType.contains("text/html", ignoreCase = true)) {
                    return@runCatching null
                }
                connection.inputStream.use { input ->
                    if (token != generation) {
                        return@runCatching null
                    }
                    val file = File(appContext.cacheDir, "memoisle-word-voice-$token.mp3")
                    file.outputStream().use { output -> input.copyTo(output) }
                    file.takeIf { it.length() > 0 }
                }
            } finally {
                connection.disconnect()
            }
        }.getOrNull()
    }

    private fun playFile(
        file: File,
        token: Int,
        lemma: String,
        locale: Locale,
        triedYoudao: Boolean,
        triedServerTts: Boolean,
    ): Boolean {
        val newPlayer = MediaPlayer()
        return runCatching {
            newPlayer.setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build(),
            )
            newPlayer.setDataSource(file.absolutePath)
            newPlayer.setOnPreparedListener { mediaPlayer ->
                if (token != generation) {
                    mediaPlayer.release()
                    return@setOnPreparedListener
                }
                mediaPlayer.start()
            }
            newPlayer.setOnCompletionListener {
                if (token == generation) {
                    releasePlayer()
                    notifyPlaying(false)
                }
            }
            newPlayer.setOnErrorListener { _, _, _ ->
                mainHandler.post {
                    if (token != generation) {
                        return@post
                    }
                    releasePlayer()
                    val youdaoUrl = youdaoVoiceUrl(lemma, locale)
                    if (!triedYoudao) {
                        startAudio(youdaoUrl, token, lemma, locale, triedYoudao = true)
                    } else if (!triedServerTts && apiClient != null) {
                        startServerTts(lemma, token, locale)
                    } else if (!speakTts(lemma, locale, token)) {
                        notifyPlaying(false)
                    }
                }
                true
            }
            player = newPlayer
            newPlayer.prepareAsync()
            true
        }.getOrElse {
            newPlayer.release()
            false
        }
    }

    private fun speakTts(lemma: String, locale: Locale, token: Int): Boolean {
        val engine = tts ?: return false
        val ready = if (isBritish(locale)) ukReady else usReady
        if (!ready || token != generation) {
            return false
        }
        engine.language = locale
        val utteranceId = "$token:${locale.toLanguageTag()}"
        return engine.speak(
            lemma,
            TextToSpeech.QUEUE_FLUSH,
            null,
            utteranceId,
        ) == TextToSpeech.SUCCESS
    }

    private fun finishIfCurrent(utteranceId: String?) {
        val token = utteranceId?.substringBefore(":")?.toIntOrNull() ?: return
        mainHandler.post {
            if (token == generation) {
                notifyPlaying(false)
            }
        }
    }

    private fun releasePlayer() {
        player?.runCatching { release() }
        player = null
    }

    private fun notifyPlaying(playing: Boolean) {
        val callback = onPlaying ?: return
        if (Looper.myLooper() == Looper.getMainLooper()) {
            callback(playing)
        } else {
            mainHandler.post { callback(playing) }
        }
    }
}
