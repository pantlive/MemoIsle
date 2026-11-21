package com.memoisle.app.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CollectionsBookmark
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.outlined.Archive
import androidx.compose.material.icons.outlined.CloudUpload
import androidx.compose.material.icons.outlined.CollectionsBookmark
import androidx.compose.material.icons.outlined.DeleteForever
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.Restore
import androidx.compose.material.icons.outlined.SearchOff
import androidx.compose.material.icons.outlined.TaskAlt
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.memoisle.app.R
import com.memoisle.app.data.Memo
import com.memoisle.app.data.SyncState
import com.memoisle.app.data.TYPE_IMAGE
import com.memoisle.app.data.TYPE_RESOURCE
import com.memoisle.app.data.TYPE_WORD
import com.memoisle.app.data.formatFileSize
import com.memoisle.app.data.hasUploadedImage
import com.memoisle.app.data.imageDimensionsLabel
import com.memoisle.app.data.resourceCategoryLabel
import com.memoisle.app.data.resourceHost
import com.memoisle.app.data.trashDaysRemaining

// 资料库列表行（普通、收件箱、回收站）、同步状态与冲突处理。（从 MemoHomeScreen.kt 拆出）

/** 网页资料的简介：优先用大模型写的用途简介，其次网页自带描述，最后备注；备注只是网址时不算。 */
internal fun resourceSummary(memo: Memo): String? =
    (memo.resourceAiSummary?.takeIf { it.isNotBlank() }
        ?: memo.resourceDescription?.takeIf { it.isNotBlank() }
        ?: memo.body.takeIf { it.isNotBlank() && it.trim() != memo.sourceUrl })
        ?.trim()
        ?.replace(Regex("\\s*\n\\s*"), " ")

/** 标题取自正文第一行时，摘要只显示后面的内容，避免同一句话出现两次。 */
private fun bodySnippet(memo: Memo): String {
    val body = memo.body.trim()
    val firstLine = body.lineSequence().firstOrNull { it.isNotBlank() }?.trim().orEmpty()
    val title = memo.title.trim()
    val titleFromBody = title == firstLine ||
        (title.endsWith("...") && firstLine.startsWith(title.removeSuffix("...")))
    val rest = if (titleFromBody) body.substringAfter(firstLine, "").trim() else body
    // 列表里只看摘要，空行和换行合并成空格，避免出现单独一行省略号。
    return rest.replace(Regex("\\s*\n\\s*"), " ")
}

@Composable
internal fun MemoRow(
    memo: Memo,
    onClick: () -> Unit,
    imageThumbnail: ByteArray? = null,
    imageLoading: Boolean = false,
    onRequestThumbnail: () -> Unit = {},
) {
    val isResource = memo.type == TYPE_RESOURCE
    val isWord = memo.type == TYPE_WORD
    val isImage = memo.type == TYPE_IMAGE
    val kind = memoKindStyle(memo.type, memo.audioMimeType != null)
    if (isImage) {
        LaunchedEffect(memo.clientId, memo.version, imageThumbnail == null) {
            if (imageThumbnail == null) {
                onRequestThumbnail()
            }
        }
    }
    val host = if (isResource) memo.sourceUrl?.let(::resourceHost).orEmpty() else ""
    val subtitle = when {
        isImage -> imageRowSubtitle(memo)
        isResource -> resourceSummary(memo) ?: host
        isWord -> listOfNotNull(
            memo.wordPhonetic?.takeIf { it.isNotBlank() },
            memo.wordMeaning?.takeIf { it.isNotBlank() }?.lineSequence()?.firstOrNull(),
        ).joinToString("  ").ifBlank { stringResource(R.string.row_waiting_meaning) }
        else -> bodySnippet(memo)
    }
    Card(
        modifier = Modifier.fillMaxWidth(),
        onClick = onClick,
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = BorderStroke(1.dp, Border),
    ) {
        Row(
            modifier = Modifier.padding(14.dp),
            verticalAlignment = Alignment.Top,
        ) {
            when {
                isImage -> MemoImage(
                    bytes = imageThumbnail,
                    loading = imageLoading && imageThumbnail == null,
                    modifier = Modifier
                        .size(56.dp)
                        .clip(RoundedCornerShape(12.dp)),
                    maxDimension = 320,
                    contentScale = ContentScale.Crop,
                    contentDescription = memo.title,
                )
                isResource -> SiteAvatar(host.ifBlank { memo.title })
                else -> KindAvatar(kind)
            }
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = memo.title,
                        modifier = Modifier.weight(1f, fill = false),
                        maxLines = if (subtitle.isBlank()) 2 else 1,
                        overflow = TextOverflow.Ellipsis,
                        style = MaterialTheme.typography.titleSmall,
                    )
                    if (memo.starred) {
                        Spacer(Modifier.width(4.dp))
                        Icon(
                            Icons.Filled.Star,
                            contentDescription = stringResource(R.string.row_star),
                            tint = Color(0xFFE6A23C),
                            modifier = Modifier.size(16.dp),
                        )
                    }
                }
                if (subtitle.isNotBlank()) {
                    Spacer(Modifier.height(2.dp))
                    Text(
                        text = subtitle,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                        color = TextMuted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                Spacer(Modifier.height(8.dp))
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    when {
                        isResource -> InfoPill(
                            resourceCategoryLabel(memo.resourceCategory, memo.resourceCategoryLabel).asString(),
                            color = ResourceAccent,
                            background = ResourceSoft,
                        )
                        isWord -> InfoPill(
                            stringResource(R.string.row_familiarity, memo.familiarity),
                            color = WordAccent,
                            background = WordSoft,
                        )
                        isImage -> imageMimeLabel(memo.imageMimeType)?.let {
                            InfoPill(it, color = ImageAccent, background = ImageSoft)
                        }
                        memo.audioMimeType != null -> InfoPill(
                            memo.audioDurationMs?.takeIf { it > 0 }?.let { stringResource(R.string.row_voice_seconds, it / 1_000) }
                                ?: stringResource(R.string.row_voice),
                            color = IdeaAccent,
                            background = IdeaSoft,
                        )
                    }
                    Text(
                        text = formatTime(memo.updatedAt),
                        color = TextMuted,
                        style = MaterialTheme.typography.labelSmall,
                        maxLines = 1,
                    )
                    Spacer(Modifier.weight(1f))
                    SyncBadge(memo.syncState)
                }
            }
        }
    }
}

@Composable
private fun imageRowSubtitle(memo: Memo): String {
    val metadata = listOfNotNull(
        imageDimensionsLabel(memo.imageWidth, memo.imageHeight)?.asString(),
        formatFileSize(memo.imageSizeBytes),
    ).joinToString(" · ")
    return when {
        metadata.isNotBlank() -> metadata
        memo.body.isNotBlank() -> memo.body
        memo.hasUploadedImage() -> stringResource(R.string.content_default_image_title)
        else -> stringResource(R.string.row_image_pending_upload)
    }
}

internal fun imageMimeLabel(mimeType: String?): String? = when (mimeType) {
    "image/png" -> "PNG"
    "image/jpeg", "image/jpg" -> "JPEG"
    "image/webp" -> "WebP"
    "image/gif" -> "GIF"
    else -> null
}

/**
 * 展示经 Bearer 鉴权拉取的图片字节；缩略图未就绪时显示进度或占位符。
 */
@Composable
internal fun MemoImage(
    bytes: ByteArray?,
    loading: Boolean,
    modifier: Modifier,
    maxDimension: Int,
    contentScale: ContentScale,
    contentDescription: String?,
) {
    val bitmap = remember(bytes, maxDimension) { decodeImageBitmap(bytes, maxDimension) }
    Box(
        modifier = modifier.background(SurfaceSubtle, RoundedCornerShape(10.dp)),
        contentAlignment = Alignment.Center,
    ) {
        when {
            bitmap != null -> Image(
                bitmap = bitmap,
                contentDescription = contentDescription,
                modifier = Modifier.fillMaxSize(),
                contentScale = contentScale,
            )
            loading -> CircularProgressIndicator(
                modifier = Modifier.size(20.dp),
                strokeWidth = 2.dp,
            )
            else -> Icon(Icons.Outlined.Image, contentDescription = null, tint = TextMuted)
        }
    }
}

private fun decodeImageBitmap(bytes: ByteArray?, maxDimension: Int): ImageBitmap? {
    if (bytes == null || bytes.isEmpty()) {
        return null
    }
    return runCatching {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        var sampleSize = 1
        while (
            bounds.outWidth / sampleSize > maxDimension ||
            bounds.outHeight / sampleSize > maxDimension
        ) {
            sampleSize *= 2
        }
        val options = BitmapFactory.Options().apply { inSampleSize = sampleSize }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)?.asImageBitmap()
    }.getOrNull()
}

@Composable
internal fun InboxMemoRow(
    memo: Memo,
    isSaving: Boolean,
    onOpen: () -> Unit,
    onOrganize: () -> Unit,
    onArchive: () -> Unit,
) {
    val kind = memoKindStyle(memo.type, memo.audioMimeType != null)
    val snippet = bodySnippet(memo)
    Card(
        modifier = Modifier.fillMaxWidth(),
        onClick = onOpen,
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = BorderStroke(1.dp, Border),
    ) {
        Column(Modifier.padding(start = 14.dp, end = 14.dp, top = 14.dp, bottom = 8.dp)) {
            Row(verticalAlignment = Alignment.Top) {
                KindAvatar(kind, size = 36.dp, iconSize = 20.dp)
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        memo.title,
                        style = MaterialTheme.typography.titleSmall,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (snippet.isNotBlank()) {
                        Spacer(Modifier.height(2.dp))
                        Text(
                            snippet,
                            color = TextMuted,
                            style = MaterialTheme.typography.bodySmall,
                            maxLines = 3,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "${stringResource(kind.label)} · ${formatTime(memo.updatedAt)}",
                        color = TextMuted,
                        style = MaterialTheme.typography.labelSmall,
                    )
                }
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
            ) {
                TextButton(onClick = onArchive, enabled = !isSaving) {
                    Icon(Icons.Outlined.Archive, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.row_archive))
                }
                TextButton(onClick = onOrganize, enabled = !isSaving) {
                    Icon(Icons.Outlined.TaskAlt, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.row_sorted))
                }
            }
        }
    }
}

@Composable
internal fun TrashMemoRow(
    memo: Memo,
    isSaving: Boolean,
    onRestore: () -> Unit,
    onPermanentDelete: () -> Unit,
) {
    val kind = memoKindStyle(memo.type, memo.audioMimeType != null)
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = BorderStroke(1.dp, Border),
    ) {
        Column(Modifier.padding(start = 14.dp, end = 14.dp, top = 14.dp, bottom = 8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                KindAvatar(kind, size = 36.dp, iconSize = 20.dp)
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        memo.title,
                        style = MaterialTheme.typography.titleSmall,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        pluralStringResource(
                            R.plurals.row_trash_days_left,
                            memo.trashDaysRemaining(),
                            stringResource(kind.label),
                            memo.trashDaysRemaining(),
                        ),
                        color = TextMuted,
                        style = MaterialTheme.typography.labelSmall,
                    )
                }
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
            ) {
                TextButton(
                    onClick = onPermanentDelete,
                    enabled = !isSaving && memo.id != null,
                    colors = ButtonDefaults.textButtonColors(contentColor = DangerRed),
                ) {
                    Icon(Icons.Outlined.DeleteForever, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.home_purge))
                }
                TextButton(onClick = onRestore, enabled = !isSaving && memo.id != null) {
                    Icon(Icons.Outlined.Restore, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.row_restore))
                }
            }
        }
    }
}

/** 已同步是常态，不再每张卡片都标；只在等待、失败或冲突时提示。 */
@Composable
private fun SyncBadge(syncState: SyncState) {
    val (label, color, icon) = when (syncState) {
        SyncState.SYNCED -> return
        SyncState.PENDING -> Triple(stringResource(R.string.row_sync_pending), TextMuted, Icons.Outlined.CloudUpload)
        SyncState.FAILED -> Triple(stringResource(R.string.row_sync_failed), DangerRed, Icons.Outlined.ErrorOutline)
        SyncState.CONFLICT -> Triple(stringResource(R.string.row_sync_conflict), WarmAmberText, Icons.Outlined.ErrorOutline)
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(14.dp))
        Spacer(Modifier.width(3.dp))
        Text(label, color = color, style = MaterialTheme.typography.labelSmall)
    }
}

@Composable
internal fun ConflictResolutionDialog(
    serverMemo: Memo,
    onKeepLocal: () -> Unit,
    onUseServer: () -> Unit,
    onLater: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onLater,
        title = { Text(stringResource(R.string.row_conflict_title), fontWeight = FontWeight.SemiBold) },
        text = {
            Text(
                stringResource(R.string.row_conflict_text, serverMemo.title),
            )
        },
        confirmButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = onUseServer) {
                    Text(stringResource(R.string.row_conflict_use_server))
                }
                Button(
                    onClick = onKeepLocal,
                    colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
                ) {
                    Text(stringResource(R.string.row_conflict_keep_mine))
                }
            }
        },
        dismissButton = {
            TextButton(onClick = onLater) {
                Text(stringResource(R.string.row_conflict_later))
            }
        },
        containerColor = SurfaceWhite,
        shape = RoundedCornerShape(14.dp),
    )
}

@Composable
internal fun EmptyMemos(
    activeType: String,
    isLibrary: Boolean,
    hasQuery: Boolean,
) {
    val kind = memoKindStyle(activeType)
    EmptyState(
        icon = when {
            hasQuery -> Icons.Outlined.SearchOff
            isLibrary -> Icons.Outlined.CollectionsBookmark
            else -> kind.icon
        },
        accent = if (hasQuery || isLibrary) DeepTeal else kind.accent,
        soft = if (hasQuery || isLibrary) TealSoft else kind.soft,
        title = when {
            hasQuery -> stringResource(R.string.row_empty_no_match)
            isLibrary -> stringResource(R.string.row_empty_library)
            activeType == TYPE_RESOURCE -> stringResource(R.string.row_empty_resource)
            activeType == TYPE_WORD -> stringResource(R.string.row_empty_word)
            activeType == TYPE_IMAGE -> stringResource(R.string.row_empty_image)
            else -> stringResource(R.string.row_empty_idea)
        },
        message = when {
            hasQuery -> stringResource(R.string.row_empty_no_match_hint)
            isLibrary -> stringResource(R.string.row_empty_library_hint)
            activeType == TYPE_RESOURCE -> stringResource(R.string.row_empty_resource_hint)
            activeType == TYPE_WORD -> stringResource(R.string.row_empty_word_hint)
            activeType == TYPE_IMAGE -> stringResource(R.string.row_empty_image_hint)
            else -> stringResource(R.string.row_empty_idea_hint)
        },
    )
}
