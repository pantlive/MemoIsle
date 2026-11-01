package com.memoisle.app.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.OpenInNew
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.outlined.Archive
import androidx.compose.material.icons.outlined.Autorenew
import androidx.compose.material.icons.outlined.StarBorder
import androidx.compose.material.icons.outlined.TaskAlt
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.memoisle.app.data.Memo
import com.memoisle.app.data.TYPE_IDEA
import com.memoisle.app.data.TYPE_RESOURCE
import com.memoisle.app.data.TYPE_WORD
import com.memoisle.app.data.resourceCategoryLabel
import com.memoisle.app.data.resourceHost
import com.memoisle.app.network.ReviewSettings

// 今日回顾：概览卡片、复习设置与逐条回顾会话。（从 MemoHomeScreen.kt 拆出）

@Composable
internal fun ReviewCard(
    wordCount: Int,
    resourceCount: Int,
    ideaCount: Int,
    onStart: () -> Unit,
) {
    val totalCount = wordCount + resourceCount + ideaCount
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(18.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = BorderStroke(1.dp, Border),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    modifier = Modifier
                        .size(40.dp)
                        .background(TealSoft, RoundedCornerShape(12.dp)),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(Icons.Outlined.Autorenew, contentDescription = null, tint = DeepTeal)
                }
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text("今日回顾", style = MaterialTheme.typography.titleMedium)
                    Text(
                        if (totalCount == 0) "今天没有需要回顾的内容" else "共 $totalCount 项，按计划混合排列",
                        color = TextMuted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                ReviewStat(wordCount, "个单词", memoKindStyle(TYPE_WORD), Modifier.weight(1f))
                ReviewStat(resourceCount, "篇待读", memoKindStyle(TYPE_RESOURCE), Modifier.weight(1f))
                ReviewStat(ideaCount, "条待整理", memoKindStyle(TYPE_IDEA), Modifier.weight(1f))
            }
            Button(
                onClick = onStart,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(48.dp),
                enabled = totalCount > 0,
                shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
            ) {
                Text(if (totalCount == 0) "今天已完成" else "开始回顾", style = MaterialTheme.typography.titleSmall)
            }
        }
    }
}

@Composable
private fun ReviewStat(
    count: Int,
    label: String,
    kind: MemoKindStyle,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier
            .background(kind.soft, RoundedCornerShape(12.dp))
            .padding(horizontal = 12.dp, vertical = 10.dp),
    ) {
        Text(
            "$count",
            color = kind.accent,
            style = MaterialTheme.typography.titleLarge,
        )
        Text(label, color = kind.accent.copy(alpha = 0.85f), style = MaterialTheme.typography.labelMedium)
    }
}

@Composable
internal fun ReviewSettingsDialog(
    settings: ReviewSettings,
    isSaving: Boolean,
    onDismiss: () -> Unit,
    onSave: (Int, List<Int>) -> Unit,
) {
    var dailyLimitText by remember(settings) {
        mutableStateOf(settings.dailyLimit.toString())
    }
    var intervalsText by remember(settings) {
        mutableStateOf(settings.intervalsDays.joinToString(", "))
    }
    var errorText by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = { if (!isSaving) onDismiss() },
        title = { Text("复习计划", fontWeight = FontWeight.SemiBold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(
                    "每日队列会混合单词、待读资料和待整理灵感。单词反馈会使用下面的间隔。",
                    color = TextMuted,
                    style = MaterialTheme.typography.bodySmall,
                )
                OutlinedTextField(
                    value = dailyLimitText,
                    onValueChange = { dailyLimitText = it },
                    label = { Text("每日队列上限（1–100）") },
                    singleLine = true,
                    enabled = !isSaving,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = intervalsText,
                    onValueChange = { intervalsText = it },
                    label = { Text("间隔天数（6 个，用逗号分隔）") },
                    supportingText = { Text("忘记后、模糊后/熟悉度 1、熟悉度 2–5") },
                    singleLine = true,
                    enabled = !isSaving,
                    modifier = Modifier.fillMaxWidth(),
                )
                errorText?.let { error ->
                    Text(error, color = MaterialTheme.colorScheme.error)
                }
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    val dailyLimit = dailyLimitText.trim().toIntOrNull()
                    val intervals = intervalsText.split(",").map { it.trim().toIntOrNull() }
                    if (dailyLimit == null || dailyLimit !in 1..100) {
                        errorText = "每日上限需要是 1–100 的整数"
                    } else if (intervals.size != 6 || intervals.any {
                            it == null || it !in 1..365
                        }
                    ) {
                        errorText = "间隔需要是 6 个 1–365 天的整数"
                    } else {
                        errorText = null
                        onSave(dailyLimit, intervals.filterNotNull())
                    }
                },
                enabled = !isSaving,
                colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
            ) {
                Text(if (isSaving) "保存中…" else "保存")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !isSaving) {
                Text("取消")
            }
        },
        containerColor = SurfaceWhite,
        shape = RoundedCornerShape(14.dp),
    )
}

@Composable
internal fun ReviewSession(
    current: Memo?,
    wordCount: Int,
    resourceCount: Int,
    ideaCount: Int,
    remainingCount: Int,
    dailyLimit: Int,
    filter: String,
    onFilterChange: (String) -> Unit,
    onOpenSettings: () -> Unit,
    showAnswer: Boolean,
    isSaving: Boolean,
    onShowAnswer: () -> Unit,
    onSkip: () -> Unit,
    onReviewWord: (String) -> Unit,
    onOpenResource: () -> Unit,
    onStarResource: () -> Unit,
    onOrganizeIdea: () -> Unit,
    onArchiveIdea: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            listOf(
                "all" to "混合 ${wordCount + resourceCount + ideaCount}",
                TYPE_WORD to "单词 $wordCount",
                TYPE_RESOURCE to "待读 $resourceCount",
                TYPE_IDEA to "待整理 $ideaCount",
            ).forEach { (value, label) ->
                MemoFilterChip(label = label, selected = filter == value, onClick = { onFilterChange(value) })
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "今日计划 $dailyLimit 条，还剩 $remainingCount 条",
                color = TextMuted,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.weight(1f),
            )
            TextButton(onClick = onOpenSettings) { Text("调整计划") }
        }
        if (current == null) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(18.dp),
                colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
                border = BorderStroke(1.dp, Border),
            ) {
                EmptyState(
                    icon = Icons.Outlined.TaskAlt,
                    title = "今天的回顾已经完成",
                    message = "到期单词、待读资料和待整理灵感会显示在这里。",
                )
            }
            return@Column
        }
        val kind = memoKindStyle(current.type, current.audioMimeType != null)
        Card(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(18.dp),
            colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
            border = BorderStroke(1.dp, Border),
        ) {
            Column(
                modifier = Modifier.padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    InfoPill(
                        text = when (current.type) {
                            TYPE_WORD -> "单词复习"
                            TYPE_RESOURCE -> "待阅读"
                            else -> "待整理灵感"
                        },
                        color = kind.accent,
                        background = kind.soft,
                        icon = kind.icon,
                    )
                    Spacer(Modifier.weight(1f))
                    Text("还剩 $remainingCount 条", color = TextMuted, style = MaterialTheme.typography.labelMedium)
                }
                Text(current.title, style = MaterialTheme.typography.headlineSmall)
                when (current.type) {
                    TYPE_WORD -> {
                        ClickablePhonetic(
                            lemma = current.title,
                            phonetic = current.wordPhonetic,
                        )
                        current.wordExample?.takeIf { it.isNotBlank() }?.let {
                            Text(
                                "“$it”",
                                color = TextMuted,
                                style = MaterialTheme.typography.bodyMedium,
                            )
                        }
                        Text(
                            "上次 ${current.lastReviewAt?.let(::formatTime) ?: "尚未复习"} · 下次 ${current.nextReviewAt?.let(::formatTime) ?: "待安排"}",
                            color = TextMuted,
                            style = MaterialTheme.typography.labelSmall,
                        )
                        if (!showAnswer) {
                            OutlinedButton(
                                onClick = onShowAnswer,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .height(48.dp),
                                shape = RoundedCornerShape(14.dp),
                            ) {
                                Icon(Icons.Outlined.Visibility, contentDescription = null, modifier = Modifier.size(18.dp))
                                Spacer(Modifier.width(8.dp))
                                Text("显示答案")
                            }
                        } else {
                            Text(
                                current.wordMeaning ?: current.body,
                                style = MaterialTheme.typography.bodyLarge,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .background(WordSoft, RoundedCornerShape(12.dp))
                                    .padding(14.dp),
                            )
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                OutlinedButton(
                                    onClick = { onReviewWord("forgot") },
                                    modifier = Modifier.weight(1f),
                                    enabled = !isSaving,
                                    shape = RoundedCornerShape(12.dp),
                                    colors = ButtonDefaults.outlinedButtonColors(contentColor = DangerRed),
                                ) { Text("忘记") }
                                OutlinedButton(
                                    onClick = { onReviewWord("fuzzy") },
                                    modifier = Modifier.weight(1f),
                                    enabled = !isSaving,
                                    shape = RoundedCornerShape(12.dp),
                                    colors = ButtonDefaults.outlinedButtonColors(contentColor = WarmAmberText),
                                ) { Text("模糊") }
                                Button(
                                    onClick = { onReviewWord("remembered") },
                                    modifier = Modifier.weight(1f),
                                    enabled = !isSaving,
                                    shape = RoundedCornerShape(12.dp),
                                    colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
                                ) { Text("记得") }
                            }
                        }
                    }
                    TYPE_RESOURCE -> {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            val host = current.sourceUrl?.let(::resourceHost).orEmpty()
                            SiteAvatar(host.ifBlank { current.title }, size = 28.dp)
                            Spacer(Modifier.width(8.dp))
                            Text(
                                listOf(
                                    host,
                                    resourceCategoryLabel(current.resourceCategory, current.resourceCategoryLabel),
                                ).filter { it.isNotBlank() }.joinToString(" · "),
                                color = TextMuted,
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                        (current.resourceAiSummary ?: current.resourceDescription)
                            ?.takeIf { it.isNotBlank() }
                            ?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
                        Button(
                            onClick = onOpenResource,
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(48.dp),
                            enabled = !isSaving && !current.sourceUrl.isNullOrBlank(),
                            shape = RoundedCornerShape(14.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
                        ) {
                            Icon(Icons.AutoMirrored.Outlined.OpenInNew, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("打开原网页")
                        }
                        OutlinedButton(
                            onClick = onStarResource,
                            modifier = Modifier.fillMaxWidth(),
                            enabled = !isSaving,
                            shape = RoundedCornerShape(14.dp),
                        ) {
                            Icon(
                                if (current.starred) Icons.Filled.Star else Icons.Outlined.StarBorder,
                                contentDescription = null,
                                tint = if (current.starred) WarmAmberText else LocalContentColor.current,
                                modifier = Modifier.size(18.dp),
                            )
                            Spacer(Modifier.width(8.dp))
                            Text(if (current.starred) "取消星标" else "星标")
                        }
                    }
                    else -> {
                        Text(current.body, style = MaterialTheme.typography.bodyLarge)
                        Button(
                            onClick = onOrganizeIdea,
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(48.dp),
                            enabled = !isSaving,
                            shape = RoundedCornerShape(14.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
                        ) {
                            Icon(Icons.Outlined.TaskAlt, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("整理完成")
                        }
                        OutlinedButton(
                            onClick = onArchiveIdea,
                            modifier = Modifier.fillMaxWidth(),
                            enabled = !isSaving,
                            shape = RoundedCornerShape(14.dp),
                        ) {
                            Icon(Icons.Outlined.Archive, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("归档")
                        }
                    }
                }
                TextButton(
                    onClick = onSkip,
                    enabled = !isSaving,
                    modifier = Modifier.align(Alignment.CenterHorizontally),
                ) {
                    Text("跳过这一条", color = TextMuted)
                }
            }
        }
    }
}
