package com.memoisle.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.OpenInNew
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.outlined.Archive
import androidx.compose.material.icons.outlined.CloseFullscreen
import androidx.compose.material.icons.outlined.CloudUpload
import androidx.compose.material.icons.outlined.ContentCopy
import androidx.compose.material.icons.outlined.ContentPaste
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.FileDownload
import androidx.compose.material.icons.outlined.HealthAndSafety
import androidx.compose.material.icons.outlined.Mic
import androidx.compose.material.icons.outlined.Pause
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.OpenInFull
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material.icons.outlined.Psychology
import androidx.compose.material.icons.outlined.Share
import androidx.compose.material.icons.outlined.TaskAlt
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.memoisle.app.audio.VoiceRecording
import com.memoisle.app.data.Memo
import com.memoisle.app.data.SyncState
import com.memoisle.app.data.TYPE_IMAGE
import com.memoisle.app.data.TYPE_RESOURCE
import com.memoisle.app.data.TYPE_WORD
import com.memoisle.app.data.formatFileSize
import com.memoisle.app.data.hasUploadedImage
import com.memoisle.app.data.imageDimensionsLabel
import com.memoisle.app.data.imageOcrSourceLabel
import com.memoisle.app.data.imageOcrStatusLabel
import com.memoisle.app.data.linkHealthLabel
import com.memoisle.app.data.normalizeResourceUrl
import com.memoisle.app.data.resourceCategoryLabel
import com.memoisle.app.data.resourceHost
import com.memoisle.app.network.WordLookupResponse
import com.memoisle.app.network.WordLookupSense

// 条目详情、编辑、新建与语音记录对话框。（从 MemoHomeScreen.kt 拆出）

/** 详情页右上角的「更多」菜单。 */
@Composable
private fun DetailMenu(
    enabled: Boolean = true,
    content: @Composable ColumnScope.(close: () -> Unit) -> Unit,
) {
    var open by remember { mutableStateOf(false) }
    Box {
        IconButton(onClick = { open = true }, enabled = enabled) {
            Icon(Icons.Outlined.MoreVert, contentDescription = "更多操作")
        }
        DropdownMenu(
            expanded = open,
            onDismissRequest = { open = false },
            containerColor = SurfaceWhite,
            shape = RoundedCornerShape(14.dp),
        ) {
            content { open = false }
        }
    }
}

@Composable
private fun MoveToTrashMenuItem(close: () -> Unit, onMoveToTrash: () -> Unit) {
    DropdownMenuItem(
        text = { Text("移入回收站", color = DangerRed) },
        leadingIcon = { Icon(Icons.Outlined.DeleteOutline, contentDescription = null, tint = DangerRed) },
        onClick = {
            close()
            onMoveToTrash()
        },
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun ResourceDetailDialog(
    memo: Memo,
    isSaving: Boolean,
    onDismiss: () -> Unit,
    onMoveToTrash: () -> Unit,
    onArchive: () -> Unit,
    onOpen: () -> Unit,
    onCopy: () -> Unit,
    onShare: () -> Unit,
) {
    val hasUrl = memo.sourceUrl != null
    val host = memo.sourceUrl?.let(::resourceHost).orEmpty()
    DetailScreen(
        kind = memoKindStyle(TYPE_RESOURCE),
        onClose = onDismiss,
        closeEnabled = !isSaving,
        actions = {
            IconButton(onClick = onCopy, enabled = hasUrl && !isSaving) {
                Icon(Icons.Outlined.ContentCopy, contentDescription = "复制链接")
            }
            IconButton(onClick = onShare, enabled = hasUrl && !isSaving) {
                Icon(Icons.Outlined.Share, contentDescription = "分享")
            }
            DetailMenu(enabled = !isSaving) { close ->
                DropdownMenuItem(
                    text = { Text("归档") },
                    leadingIcon = { Icon(Icons.Outlined.Archive, contentDescription = null) },
                    onClick = {
                        close()
                        onArchive()
                    },
                )
                MoveToTrashMenuItem(close, onMoveToTrash)
            }
        },
        bottomBar = {
            Button(
                onClick = onOpen,
                enabled = hasUrl && !isSaving,
                modifier = Modifier
                    .weight(1f)
                    .height(50.dp),
                shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
            ) {
                Icon(Icons.AutoMirrored.Outlined.OpenInNew, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                Text("打开原网页", style = MaterialTheme.typography.titleSmall)
            }
        },
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            SiteAvatar(host.ifBlank { memo.title }, size = 44.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    memo.resourceSiteName?.takeIf { it.isNotBlank() } ?: host,
                    style = MaterialTheme.typography.titleSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    memo.sourceUrl.orEmpty(),
                    color = TextMuted,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        Text(memo.title, style = MaterialTheme.typography.headlineSmall)
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            InfoPill(
                resourceCategoryLabel(memo.resourceCategory, memo.resourceCategoryLabel),
                color = ResourceAccent,
                background = ResourceSoft,
            )
            if (memo.starred) {
                InfoPill("星标", color = WarmAmberText, background = WarmAmberSoft, icon = Icons.Filled.Star)
            }
            InfoPill(
                "巡检：${linkHealthLabel(memo.linkHealthStatus)}",
                icon = Icons.Outlined.HealthAndSafety,
            )
        }
        memo.resourceAiSummary?.takeIf { it.isNotBlank() }?.let { summary ->
            // 大模型写的用途简介放在最前，比网页自带描述更醒目。
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(ResourceSoft, RoundedCornerShape(12.dp))
                    .padding(12.dp),
                verticalAlignment = Alignment.Top,
            ) {
                Text("用途", color = ResourceAccent, style = MaterialTheme.typography.labelMedium, modifier = Modifier.padding(top = 2.dp))
                Spacer(Modifier.width(8.dp))
                Text(summary, style = MaterialTheme.typography.bodyMedium, color = TextStrong)
            }
        }
        memo.resourceDescription?.takeIf { it.isNotBlank() }?.let { description ->
            Text(description, style = MaterialTheme.typography.bodyLarge)
        }
        if (memo.body != memo.sourceUrl && memo.body.isNotBlank()) {
            DetailField("个人备注") {
                Text(
                    memo.body,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(SurfaceSubtle, RoundedCornerShape(12.dp))
                        .padding(12.dp),
                )
            }
        }
        Text(
            listOfNotNull(
                "收藏于 ${formatTime(memo.createdAt)}",
                memo.linkLastCheckedAt?.let { "最近检查 ${formatTime(it)}" },
            ).joinToString(" · "),
            color = TextMuted,
            style = MaterialTheme.typography.labelSmall,
        )
        ResourceReadOnlyCard()
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun ImageDetailDialog(
    memo: Memo,
    isSaving: Boolean,
    thumbnail: ByteArray?,
    fullImage: ByteArray?,
    isLoadingThumbnail: Boolean,
    isLoadingFull: Boolean,
    onDismiss: () -> Unit,
    onMoveToTrash: () -> Unit,
    onRequestThumbnail: () -> Unit,
    onRequestFull: () -> Unit,
    onShare: () -> Unit,
) {
    var expanded by rememberSaveable(memo.clientId) { mutableStateOf(false) }
    LaunchedEffect(memo.clientId, memo.version) {
        onRequestThumbnail()
    }
    LaunchedEffect(expanded) {
        if (expanded && memo.id != null && fullImage == null) {
            onRequestFull()
        }
    }
    val displayBytes = if (expanded) fullImage ?: thumbnail else thumbnail
    DetailScreen(
        kind = memoKindStyle(TYPE_IMAGE),
        onClose = onDismiss,
        closeEnabled = !isSaving,
        actions = {
            IconButton(onClick = onShare, enabled = !isSaving) {
                Icon(Icons.Outlined.Share, contentDescription = "分享")
            }
            DetailMenu(enabled = !isSaving) { close ->
                MoveToTrashMenuItem(close, onMoveToTrash)
            }
        },
    ) {
        Text(memo.title, style = MaterialTheme.typography.headlineSmall)
        Box {
            MemoImage(
                bytes = displayBytes,
                loading = displayBytes == null && (isLoadingThumbnail || isLoadingFull),
                modifier = Modifier
                    .fillMaxWidth()
                    .height(if (expanded) 420.dp else 240.dp)
                    .clip(RoundedCornerShape(16.dp))
                    .clickable { expanded = !expanded },
                maxDimension = if (expanded) 2_048 else 1_280,
                contentScale = if (expanded) ContentScale.Fit else ContentScale.Crop,
                contentDescription = memo.title,
            )
            if (memo.id != null) {
                Row(
                    modifier = Modifier
                        .align(Alignment.BottomEnd)
                        .padding(10.dp)
                        .background(Color.Black.copy(alpha = 0.55f), RoundedCornerShape(999.dp))
                        .clickable { expanded = !expanded }
                        .padding(horizontal = 12.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(
                        if (expanded) Icons.Outlined.CloseFullscreen else Icons.Outlined.OpenInFull,
                        contentDescription = null,
                        tint = Color.White,
                        modifier = Modifier.size(16.dp),
                    )
                    Spacer(Modifier.width(6.dp))
                    Text(
                        if (expanded) "收起原图" else "查看原图",
                        color = Color.White,
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
            }
        }
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            imageDimensionsLabel(memo.imageWidth, memo.imageHeight)?.let { ImageMetaChip(it) }
            formatFileSize(memo.imageSizeBytes)?.let { ImageMetaChip(it) }
            imageMimeLabel(memo.imageMimeType)?.let { ImageMetaChip(it) }
        }
        memo.body.takeIf { it.isNotBlank() }?.let { note ->
            DetailField("备注") {
                Text(note, style = MaterialTheme.typography.bodyMedium)
            }
        }
        ImageOcrSection(memo)
        if (memo.id == null || !memo.hasUploadedImage()) {
            InfoPill(
                "图片尚未上传完成，联网后会自动重试",
                color = WarmAmberText,
                background = WarmAmberSoft,
                icon = Icons.Outlined.CloudUpload,
            )
        }
    }
}

@Composable
private fun ImageMetaChip(label: String) {
    InfoPill(label, color = ImageAccent, background = ImageSoft)
}

/**
 * 只读展示服务端识别出的图片 OCR 文字与自动标签；Android 不触发识别。
 */
@Composable
private fun ImageOcrSection(memo: Memo) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(SurfaceSubtle, RoundedCornerShape(12.dp))
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text("图片文字识别", color = TextMuted, fontSize = 11.sp)
            Text(memo.imageOcrStatusLabel(), color = DeepTeal, fontSize = 11.sp)
        }
        when (memo.imageOcrStatus) {
            "ready" -> {
                val ocrText = memo.imageOcrText?.trim().orEmpty()
                if (ocrText.isEmpty()) {
                    Text(
                        "没有识别到文字",
                        color = TextMuted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                } else {
                    Text(
                        ocrText,
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(max = 200.dp)
                            .verticalScroll(rememberScrollState()),
                    )
                }
                if (memo.imageAutoTags.isNotEmpty()) {
                    Text("自动标签", color = TextMuted, fontSize = 11.sp)
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .horizontalScroll(rememberScrollState()),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        memo.imageAutoTags.forEach { tag -> ImageMetaChip(tag) }
                    }
                }
                val metaLine = listOfNotNull(
                    memo.imageOcrSourceLabel()?.let { source -> "来源：$source" },
                    memo.imageOcrUpdatedAt
                        ?.takeIf { it.isNotBlank() }
                        ?.let { updated -> "更新于 ${formatTime(updated)}" },
                ).joinToString(" · ")
                if (metaLine.isNotEmpty()) {
                    Text(
                        metaLine,
                        color = TextMuted,
                        style = MaterialTheme.typography.labelSmall,
                    )
                }
            }
            "failed" -> Text(
                memo.imageOcrError?.takeIf { it.isNotBlank() } ?: "图片文字识别失败。",
                color = WarmAmberText,
                style = MaterialTheme.typography.labelSmall,
            )
            "disabled" -> Text(
                memo.imageOcrError?.takeIf { it.isNotBlank() } ?: "图片文字识别未启用。",
                color = WarmAmberText,
                style = MaterialTheme.typography.labelSmall,
            )
            "pending" -> Text(
                "已排队，等待识别图片文字。",
                color = TextMuted,
                style = MaterialTheme.typography.labelSmall,
            )
            "processing" -> Text(
                "正在识别图片文字…",
                color = TextMuted,
                style = MaterialTheme.typography.labelSmall,
            )
            else -> Text(
                "尚未开始识别图片文字。",
                color = TextMuted,
                style = MaterialTheme.typography.labelSmall,
            )
        }
    }
}

@Composable
internal fun EditMemoDialog(
    memo: Memo,
    isSaving: Boolean,
    isDownloadingAudio: Boolean,
    onDismiss: () -> Unit,
    onMoveToTrash: () -> Unit,
    onSave: (String, String, String?, String?, String?) -> Unit,
    onReview: (String) -> Unit,
    onPlayAudio: () -> Unit,
    onDownloadAudio: () -> Unit,
    resetToServerMemo: Memo? = null,
) {
    var title by rememberSaveable(memo.clientId) { mutableStateOf(memo.title) }
    var body by rememberSaveable(memo.clientId) {
        mutableStateOf(memo.body)
    }
    var wordPhonetic by rememberSaveable(memo.clientId) {
        mutableStateOf(memo.wordPhonetic.orEmpty())
    }
    var wordMeaning by rememberSaveable(memo.clientId) {
        mutableStateOf(memo.wordMeaning.orEmpty())
    }
    var wordExample by rememberSaveable(memo.clientId) {
        mutableStateOf(memo.wordExample.orEmpty())
    }
    var showWordAnswer by rememberSaveable(memo.clientId) {
        mutableStateOf(false)
    }
    val isWord = memo.type == TYPE_WORD
    val kind = memoKindStyle(memo.type, memo.audioMimeType != null)

    LaunchedEffect(resetToServerMemo?.clientId, resetToServerMemo?.version) {
        resetToServerMemo?.let { serverMemo ->
            title = serverMemo.title
            body = serverMemo.body
            wordPhonetic = serverMemo.wordPhonetic.orEmpty()
            wordMeaning = serverMemo.wordMeaning.orEmpty()
            wordExample = serverMemo.wordExample.orEmpty()
            showWordAnswer = false
        }
    }
    // 冲突时编辑器保留的是本地修改，此时也允许保存；否则没有改动就不必保存。
    val dirty = memo.syncState == SyncState.CONFLICT ||
        title != memo.title ||
        (if (isWord) {
            wordPhonetic != memo.wordPhonetic.orEmpty() ||
                wordMeaning != memo.wordMeaning.orEmpty() ||
                wordExample != memo.wordExample.orEmpty()
        } else {
            body != memo.body
        })
    val canSave = dirty && title.isNotBlank() && (isWord || body.isNotBlank()) && !isSaving
    val fieldColors = OutlinedTextFieldDefaults.colors(
        unfocusedBorderColor = Border,
        focusedBorderColor = kind.accent,
        focusedLabelColor = kind.accent,
    )

    DetailScreen(
        kind = kind,
        onClose = onDismiss,
        closeEnabled = !isSaving,
        actions = {
            DetailMenu(enabled = !isSaving) { close ->
                MoveToTrashMenuItem(close, onMoveToTrash)
            }
        },
        bottomBar = {
            Text(
                "更新于 ${formatTime(memo.updatedAt)}",
                color = TextMuted,
                style = MaterialTheme.typography.labelSmall,
                modifier = Modifier.weight(1f),
            )
            Button(
                onClick = {
                    onSave(
                        title,
                        when {
                            isWord -> wordMeaning.ifBlank { title }
                            else -> body
                        },
                        if (isWord) wordPhonetic.ifBlank { null } else null,
                        if (isWord) wordMeaning.ifBlank { null } else null,
                        if (isWord) wordExample.ifBlank { null } else null,
                    )
                },
                enabled = canSave,
                modifier = Modifier.height(48.dp),
                shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
            ) {
                Text(if (isSaving) "保存中…" else "保存修改", style = MaterialTheme.typography.titleSmall)
            }
        },
    ) {
        if (memo.audioMimeType != null) {
            val seconds = (memo.audioDurationMs ?: 0) / 1_000
            val hasAudio = memo.id != null || memo.localAudioPath != null
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedButton(
                    onClick = onPlayAudio,
                    modifier = Modifier
                        .weight(1.15f)
                        .height(48.dp),
                    enabled = hasAudio,
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = IdeaAccent),
                ) {
                    Icon(Icons.Outlined.PlayArrow, contentDescription = null)
                    Spacer(Modifier.width(6.dp))
                    Text(
                        text = if (seconds > 0) "播放 · ${seconds} 秒" else "播放录音",
                        maxLines = 1,
                    )
                }
                OutlinedButton(
                    onClick = onDownloadAudio,
                    modifier = Modifier
                        .weight(1f)
                        .height(48.dp),
                    enabled = hasAudio && !isDownloadingAudio,
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = IdeaAccent),
                ) {
                    Icon(Icons.Outlined.FileDownload, contentDescription = null)
                    Spacer(Modifier.width(6.dp))
                    Text(
                        text = if (isDownloadingAudio) "保存中…" else "下载录音",
                        maxLines = 1,
                    )
                }
            }
        }
        if (!memo.transcript.isNullOrBlank()) {
            DetailField("会议转写（我 / 对方）") {
                Text(
                    memo.transcript,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(max = 260.dp)
                        .background(SurfaceSubtle, RoundedCornerShape(12.dp))
                        .verticalScroll(rememberScrollState())
                        .padding(12.dp),
                )
            }
        }
        OutlinedTextField(
            value = title,
            onValueChange = { title = it },
            label = { Text(if (isWord) "单词或短语" else "标题") },
            modifier = Modifier.fillMaxWidth(),
            textStyle = if (isWord) MaterialTheme.typography.titleLarge else MaterialTheme.typography.bodyLarge,
            shape = RoundedCornerShape(12.dp),
            colors = fieldColors,
        )
        if (isWord) {
            PhoneticPlayField(
                lemma = title,
                phonetic = wordPhonetic,
                onPhoneticChange = { wordPhonetic = it },
            )
            if (!showWordAnswer) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(WordSoft, RoundedCornerShape(16.dp))
                        .padding(20.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Icon(Icons.Outlined.Psychology, contentDescription = null, tint = WordAccent, modifier = Modifier.size(28.dp))
                    Text("先回想释义和例句", color = WordAccent, style = MaterialTheme.typography.titleSmall)
                    OutlinedButton(
                        onClick = { showWordAnswer = true },
                        shape = RoundedCornerShape(12.dp),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = WordAccent),
                    ) {
                        Icon(Icons.Outlined.Visibility, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("显示答案")
                    }
                }
            } else {
                OutlinedTextField(
                    value = wordMeaning,
                    onValueChange = { wordMeaning = it },
                    label = { Text("释义") },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 3,
                    maxLines = 7,
                    shape = RoundedCornerShape(12.dp),
                    colors = fieldColors,
                )
                OutlinedTextField(
                    value = wordExample,
                    onValueChange = { wordExample = it },
                    label = { Text("例句或上下文") },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 2,
                    maxLines = 5,
                    shape = RoundedCornerShape(12.dp),
                    colors = fieldColors,
                )
                SentencePronunciationButton(text = wordExample)
                DetailField("这次记得怎么样？") {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        OutlinedButton(
                            onClick = { onReview("forgot") },
                            modifier = Modifier.weight(1f),
                            enabled = !isSaving,
                            shape = RoundedCornerShape(12.dp),
                            colors = ButtonDefaults.outlinedButtonColors(contentColor = DangerRed),
                        ) { Text("忘记") }
                        OutlinedButton(
                            onClick = { onReview("fuzzy") },
                            modifier = Modifier.weight(1f),
                            enabled = !isSaving,
                            shape = RoundedCornerShape(12.dp),
                            colors = ButtonDefaults.outlinedButtonColors(contentColor = WarmAmberText),
                        ) { Text("模糊") }
                        Button(
                            onClick = { onReview("remembered") },
                            modifier = Modifier.weight(1f),
                            enabled = !isSaving,
                            shape = RoundedCornerShape(12.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = WordAccent),
                        ) { Text("记得") }
                    }
                }
            }
            Text(
                "熟悉度 ${memo.familiarity}/5 · 已复习 ${memo.reviewCount} 次 · " +
                    "上次 ${memo.lastReviewAt?.let(::formatTime) ?: "尚未复习"} · " +
                    "下次 ${memo.nextReviewAt?.let(::formatTime) ?: "待安排"}",
                color = TextMuted,
                style = MaterialTheme.typography.labelSmall,
            )
        } else {
            OutlinedTextField(
                value = body,
                onValueChange = { body = it },
                label = { Text("内容") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 6,
                maxLines = 16,
                shape = RoundedCornerShape(12.dp),
                colors = fieldColors,
            )
            SentencePronunciationButton(text = body)
        }
    }
}

@Composable
internal fun CreateIdeaDialog(
    isSaving: Boolean,
    onDismiss: () -> Unit,
    onSave: (String) -> Unit,
) {
    var body by rememberSaveable { mutableStateOf("") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("写灵感", fontWeight = FontWeight.SemiBold) },
        text = {
            OutlinedTextField(
                value = body,
                onValueChange = { body = it },
                label = { Text("此刻想到什么？") },
                modifier = Modifier.fillMaxWidth(),
                minLines = 5,
                maxLines = 12,
                shape = RoundedCornerShape(10.dp),
            )
        },
        confirmButton = {
            Button(
                onClick = { onSave(body) },
                enabled = body.isNotBlank() && !isSaving,
            ) {
                Text(if (isSaving) "保存中…" else "保存灵感")
            }
        },
        dismissButton = {
            OutlinedButton(onClick = onDismiss, enabled = !isSaving) {
                Text("取消")
            }
        },
        containerColor = SurfaceWhite,
        shape = RoundedCornerShape(14.dp),
    )
}

@Composable
internal fun CreateResourceDialog(
    url: String,
    title: String,
    note: String,
    isSaving: Boolean,
    onUrlChange: (String) -> Unit,
    onTitleChange: (String) -> Unit,
    onNoteChange: (String) -> Unit,
    onDismiss: () -> Unit,
    onSave: () -> Unit,
) {
    val kind = memoKindStyle(TYPE_RESOURCE)
    val fieldColors = OutlinedTextFieldDefaults.colors(unfocusedBorderColor = Border, focusedBorderColor = kind.accent)
    DetailScreen(
        kind = kind,
        onClose = onDismiss,
        closeEnabled = !isSaving,
        bottomBar = {
            OutlinedButton(
                onClick = onDismiss,
                enabled = !isSaving,
                modifier = Modifier.height(48.dp),
                shape = RoundedCornerShape(14.dp),
            ) { Text("取消") }
            Button(
                onClick = onSave,
                enabled = normalizeResourceUrl(url) != null && !isSaving,
                modifier = Modifier.height(48.dp),
                shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
            ) { Text(if (isSaving) "保存中…" else "保存资料") }
        },
    ) {
        Text("保存分享的网页", style = MaterialTheme.typography.headlineSmall)
        Text(
            "确认浏览器分享的链接；保存后资料在手机上只读，完整整理请使用 Web。",
            color = TextMuted,
            style = MaterialTheme.typography.bodySmall,
        )
        OutlinedTextField(
            value = url,
            onValueChange = onUrlChange,
            label = { Text("网页链接") },
            modifier = Modifier.fillMaxWidth(),
            placeholder = { Text("https://example.com/article") },
            singleLine = true,
            shape = RoundedCornerShape(12.dp),
            colors = fieldColors,
        )
        OutlinedTextField(
            value = title,
            onValueChange = onTitleChange,
            label = { Text("标题（可选）") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            shape = RoundedCornerShape(12.dp),
            colors = fieldColors,
        )
        OutlinedTextField(
            value = note,
            onValueChange = onNoteChange,
            label = { Text("个人备注（可选）") },
            modifier = Modifier.fillMaxWidth(),
            minLines = 3,
            maxLines = 7,
            shape = RoundedCornerShape(12.dp),
            colors = fieldColors,
        )
    }
}

@Composable
internal fun CreateWordDialog(
    lemma: String,
    phonetic: String,
    meaning: String,
    example: String,
    isSaving: Boolean,
    isLookingUp: Boolean,
    lookup: WordLookupResponse?,
    onLemmaChange: (String) -> Unit,
    onPhoneticChange: (String) -> Unit,
    onMeaningChange: (String) -> Unit,
    onExampleChange: (String) -> Unit,
    onFillClipboard: () -> Unit,
    onLookup: () -> Unit,
    onClearLookup: () -> Unit,
    onApplyLookup: (List<WordLookupSense>) -> Unit,
    onDismiss: () -> Unit,
    onSave: () -> Unit,
) {
    val kind = memoKindStyle(TYPE_WORD)
    val fieldColors = OutlinedTextFieldDefaults.colors(
        unfocusedBorderColor = Border,
        focusedBorderColor = kind.accent,
        focusedLabelColor = kind.accent,
    )
    DetailScreen(
        kind = kind,
        onClose = onDismiss,
        closeEnabled = !isSaving,
        actions = {
            TextButton(onClick = onFillClipboard, enabled = !isSaving) {
                Icon(Icons.Outlined.ContentPaste, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("从剪贴板填入")
            }
        },
        bottomBar = {
            OutlinedButton(
                onClick = onDismiss,
                enabled = !isSaving,
                modifier = Modifier.height(48.dp),
                shape = RoundedCornerShape(14.dp),
            ) { Text("取消") }
            Button(
                onClick = onSave,
                enabled = lemma.isNotBlank() && !isSaving,
                modifier = Modifier.height(48.dp),
                shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
            ) { Text(if (isSaving) "保存中…" else "收藏单词") }
        },
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("收藏英语单词", style = MaterialTheme.typography.headlineSmall)
            Text(
                if (isLookingUp) "正在填入中文释义、音标和例句…" else "输入单词后自动填入中文释义、音标和例句",
                color = TextMuted,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        OutlinedTextField(
            value = lemma,
            onValueChange = onLemmaChange,
            label = { Text("单词或短语") },
            modifier = Modifier.fillMaxWidth(),
            placeholder = { Text("例如 serendipity") },
            singleLine = true,
            textStyle = MaterialTheme.typography.titleLarge,
            shape = RoundedCornerShape(12.dp),
            colors = fieldColors,
            trailingIcon = if (isLookingUp) {
                { CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp, color = kind.accent) }
            } else {
                null
            },
        )
        PhoneticPlayField(
            lemma = lemma,
            phonetic = phonetic,
            onPhoneticChange = onPhoneticChange,
            usAudioUrl = lookup?.usAudioUrl,
            ukAudioUrl = lookup?.ukAudioUrl,
        )
        WordLookupControls(
            lemma = lemma,
            isSaving = isSaving,
            isLookingUp = isLookingUp,
            lookup = lookup,
            onLookup = onLookup,
            onClearLookup = onClearLookup,
            onApplyLookup = onApplyLookup,
        )
        OutlinedTextField(
            value = meaning,
            onValueChange = onMeaningChange,
            label = { Text("中文释义（自动填入）") },
            modifier = Modifier.fillMaxWidth(),
            minLines = 3,
            maxLines = 6,
            shape = RoundedCornerShape(12.dp),
            colors = fieldColors,
        )
        OutlinedTextField(
            value = example,
            onValueChange = onExampleChange,
            label = { Text("例句（自动填入）") },
            modifier = Modifier.fillMaxWidth(),
            minLines = 2,
            maxLines = 5,
            shape = RoundedCornerShape(12.dp),
            colors = fieldColors,
        )
    }
}

@Composable
internal fun VoiceCaptureDialog(
    text: String,
    isRecording: Boolean,
    isPaused: Boolean,
    recording: VoiceRecording?,
    elapsedMs: () -> Int,
    amplitudePercent: () -> Int,
    isTranscribing: Boolean,
    transcriptionMessage: String?,
    isSaving: Boolean,
    permissionDenied: Boolean,
    onTextChange: (String) -> Unit,
    onStart: () -> Unit,
    onStop: () -> Unit,
    onTogglePause: () -> Unit,
    onReset: () -> Unit,
    onRequestDismiss: () -> Unit,
    onSave: () -> Unit,
) {
    val seconds = elapsedMs() / 1_000
    AlertDialog(
        onDismissRequest = { if (!isSaving) onRequestDismiss() },
        title = { Text("语音记录", fontWeight = FontWeight.SemiBold) },
        text = {
            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Box(
                    modifier = Modifier
                        .size(112.dp)
                        .background(
                            if (isRecording) WarmAmberSoft else TealSoft,
                            CircleShape,
                        ),
                    contentAlignment = Alignment.Center,
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Icon(
                            when {
                                isPaused -> Icons.Outlined.Pause
                                recording != null && !isRecording -> Icons.Outlined.TaskAlt
                                else -> Icons.Outlined.Mic
                            },
                            contentDescription = null,
                            tint = if (isRecording) WarmAmberText else DeepTeal,
                            modifier = Modifier.size(30.dp),
                        )
                        Text(
                            "${seconds}秒",
                            style = MaterialTheme.typography.titleMedium,
                        )
                        Text(
                            when {
                                isPaused -> "已暂停"
                                isRecording -> "正在录音"
                                recording != null -> "录音已就绪"
                                else -> "等待开始"
                            },
                            color = TextMuted,
                            fontSize = 11.sp,
                        )
                    }
                }
                Column(modifier = Modifier.fillMaxWidth()) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text("输入音量", color = TextMuted, fontSize = 12.sp)
                        Text("${amplitudePercent()}%", color = TextMuted, fontSize = 12.sp)
                    }
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(8.dp)
                            .background(TealSoft, RoundedCornerShape(99.dp)),
                    ) {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth((amplitudePercent() / 100f).coerceIn(0f, 1f))
                                .height(8.dp)
                                .background(WarmAmberText, RoundedCornerShape(99.dp)),
                        )
                    }
                }
                if (permissionDenied) {
                    Text(
                        "需要麦克风权限才能录音，你仍可使用文字记录。",
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                OutlinedTextField(
                    value = text,
                    onValueChange = onTextChange,
                    label = { Text("转写结果（可编辑，可选）") },
                    placeholder = { Text("录音停止后会自动填入识别结果") },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 3,
                    maxLines = 7,
                    enabled = !isSaving,
                    shape = RoundedCornerShape(10.dp),
                )
                if (isTranscribing) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                        )
                        Text(
                            transcriptionMessage ?: "正在转写…",
                            color = TextMuted,
                            style = MaterialTheme.typography.labelSmall,
                        )
                    }
                } else if (transcriptionMessage != null) {
                    Text(
                        transcriptionMessage,
                        color = TextMuted,
                        style = MaterialTheme.typography.labelSmall,
                    )
                }
                Text(
                    "原始录音只保存到你的私人资料库；没有模型时仍可手动填写文字。",
                    color = TextMuted,
                    style = MaterialTheme.typography.labelSmall,
                )
            }
        },
        confirmButton = {
            when {
                isRecording -> Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = onTogglePause) {
                        Text(if (isPaused) "继续" else "暂停")
                    }
                    Button(onClick = onStop) { Text("结束录音") }
                }
                recording != null -> Button(onClick = onSave, enabled = !isSaving) {
                    Text(if (isSaving) "保存中…" else "保存语音灵感")
                }
                else -> Button(onClick = onStart, enabled = !isSaving) {
                    Text("开始录音")
                }
            }
        },
        dismissButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (recording != null && !isSaving) {
                    TextButton(onClick = onReset) { Text("重新录制") }
                }
                OutlinedButton(
                    onClick = onRequestDismiss,
                    enabled = !isSaving,
                ) {
                    Text("取消")
                }
            }
        },
        containerColor = SurfaceWhite,
        shape = RoundedCornerShape(14.dp),
    )
}
