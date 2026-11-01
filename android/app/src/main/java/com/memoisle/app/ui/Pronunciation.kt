package com.memoisle.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.VolumeUp
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.memoisle.app.MemoIsleApplication
import com.memoisle.app.audio.WordPronouncer
import java.util.Locale

// 单词与例句发音：播放器、音标点读与发音按钮。（从 MemoHomeScreen.kt 拆出）

@Composable
private fun rememberWordPlayer(
    lemma: String,
    usAudioUrl: String?,
    ukAudioUrl: String?,
): Pair<String?, (String) -> Unit> {
    val context = LocalContext.current
    val apiClient = (context.applicationContext as? MemoIsleApplication)?.api
    var playingTag by remember { mutableStateOf<String?>(null) }
    val pronouncer = remember(context, apiClient) { WordPronouncer(context, apiClient) }
    DisposableEffect(pronouncer) {
        onDispose { pronouncer.release() }
    }
    val play: (String) -> Unit = play@{ tag ->
        if (lemma.isBlank()) {
            return@play
        }
        val locale = if (tag == "uk") Locale.UK else Locale.US
        val audioUrl = if (tag == "uk") ukAudioUrl else usAudioUrl
        playingTag = tag
        pronouncer.play(lemma, locale, audioUrl) { playing ->
            playingTag = if (playing) tag else null
        }
    }
    return playingTag to play
}

@Composable
internal fun SentencePronunciationButton(text: String) {
    val context = LocalContext.current
    val apiClient = (context.applicationContext as? MemoIsleApplication)?.api
    var playing by remember { mutableStateOf(false) }
    val pronouncer = remember(context, apiClient) { WordPronouncer(context, apiClient) }
    DisposableEffect(pronouncer) {
        onDispose { pronouncer.release() }
    }
    OutlinedButton(
        onClick = {
            pronouncer.playText(text, Locale.US) { playing = it }
        },
        enabled = text.isNotBlank() && !playing,
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
    ) {
        Icon(Icons.AutoMirrored.Outlined.VolumeUp, contentDescription = null, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
        Text(if (playing) "播放中…" else "朗读例句 / 内容")
    }
}

@Composable
internal fun PhoneticPlayField(
    lemma: String,
    phonetic: String,
    onPhoneticChange: (String) -> Unit,
    usAudioUrl: String? = null,
    ukAudioUrl: String? = null,
) {
    val (playingTag, play) = rememberWordPlayer(lemma, usAudioUrl, ukAudioUrl)
    val canPlay = lemma.isNotBlank()
    OutlinedTextField(
        value = phonetic,
        onValueChange = onPhoneticChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text("音标") },
        placeholder = { Text("输入单词后自动填入") },
        supportingText = {
            Text(if (canPlay) "点右侧的美式 / 英式按钮播放读音" else "先输入单词再播放读音")
        },
        singleLine = true,
        shape = RoundedCornerShape(12.dp),
        trailingIcon = {
            Row(
                modifier = Modifier.padding(end = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                PronounceChip("美", playingTag == "us", canPlay) { play("us") }
                PronounceChip("英", playingTag == "uk", canPlay) { play("uk") }
            }
        },
    )
}

/** 发音小按钮：喇叭图标加口音，播放时变成实心底。 */
@Composable
private fun PronounceChip(
    accent: String,
    playing: Boolean,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(if (playing) WordAccent else WordSoft)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            Icons.AutoMirrored.Outlined.VolumeUp,
            contentDescription = "播放${accent}式读音",
            tint = if (playing) Color.White else if (enabled) WordAccent else TextMuted,
            modifier = Modifier.size(16.dp),
        )
        Spacer(Modifier.width(4.dp))
        Text(
            accent,
            color = if (playing) Color.White else if (enabled) WordAccent else TextMuted,
            style = MaterialTheme.typography.labelMedium,
        )
    }
}

@Composable
internal fun ClickablePhonetic(
    lemma: String,
    phonetic: String?,
    usAudioUrl: String? = null,
    ukAudioUrl: String? = null,
) {
    val (playingTag, play) = rememberWordPlayer(lemma, usAudioUrl, ukAudioUrl)
    val canPlay = lemma.isNotBlank()
    val display = phonetic?.takeIf { it.isNotBlank() } ?: "点击播放读音"
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            display,
            modifier = Modifier
                .clip(RoundedCornerShape(8.dp))
                .clickable(enabled = canPlay) { play("us") }
                .padding(vertical = 2.dp),
            color = if (canPlay) WordAccent else TextMuted,
            fontSize = 20.sp,
            fontWeight = FontWeight.Medium,
        )
        PronounceChip("美", playingTag == "us", canPlay) { play("us") }
        PronounceChip("英", playingTag == "uk", canPlay) { play("uk") }
    }
}
