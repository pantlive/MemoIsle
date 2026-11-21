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
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.memoisle.app.R
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
                    Text(stringResource(R.string.home_title_review), style = MaterialTheme.typography.titleMedium)
                    Text(
                        if (totalCount == 0) stringResource(R.string.review_nothing_today) else pluralStringResource(R.plurals.review_total, totalCount, totalCount),
                        color = TextMuted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                ReviewStat(wordCount, pluralStringResource(R.plurals.review_stat_words, wordCount), memoKindStyle(TYPE_WORD), Modifier.weight(1f))
                ReviewStat(resourceCount, pluralStringResource(R.plurals.review_stat_to_read, resourceCount), memoKindStyle(TYPE_RESOURCE), Modifier.weight(1f))
                ReviewStat(ideaCount, pluralStringResource(R.plurals.review_stat_to_sort, ideaCount), memoKindStyle(TYPE_IDEA), Modifier.weight(1f))
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
                Text(if (totalCount == 0) stringResource(R.string.review_done_today) else stringResource(R.string.review_start), style = MaterialTheme.typography.titleSmall)
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
    var errorText by remember { mutableStateOf<Int?>(null) }

    AlertDialog(
        onDismissRequest = { if (!isSaving) onDismiss() },
        title = { Text(stringResource(R.string.review_plan_title), fontWeight = FontWeight.SemiBold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(
                    stringResource(R.string.review_plan_text),
                    color = TextMuted,
                    style = MaterialTheme.typography.bodySmall,
                )
                OutlinedTextField(
                    value = dailyLimitText,
                    onValueChange = { dailyLimitText = it },
                    label = { Text(stringResource(R.string.review_daily_limit_label)) },
                    singleLine = true,
                    enabled = !isSaving,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = intervalsText,
                    onValueChange = { intervalsText = it },
                    label = { Text(stringResource(R.string.review_intervals_label)) },
                    supportingText = { Text(stringResource(R.string.review_intervals_hint)) },
                    singleLine = true,
                    enabled = !isSaving,
                    modifier = Modifier.fillMaxWidth(),
                )
                errorText?.let { error ->
                    Text(stringResource(error), color = MaterialTheme.colorScheme.error)
                }
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    val dailyLimit = dailyLimitText.trim().toIntOrNull()
                    val intervals = intervalsText.split(",").map { it.trim().toIntOrNull() }
                    if (dailyLimit == null || dailyLimit !in 1..100) {
                        errorText = R.string.review_error_daily_limit
                    } else if (intervals.size != 6 || intervals.any {
                            it == null || it !in 1..365
                        }
                    ) {
                        errorText = R.string.review_error_intervals
                    } else {
                        errorText = null
                        onSave(dailyLimit, intervals.filterNotNull())
                    }
                },
                enabled = !isSaving,
                colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
            ) {
                Text(if (isSaving) stringResource(R.string.relay_ui_saving) else stringResource(R.string.common_save))
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !isSaving) {
                Text(stringResource(R.string.common_cancel))
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
                "all" to stringResource(R.string.review_filter_mixed, wordCount + resourceCount + ideaCount),
                TYPE_WORD to stringResource(R.string.review_filter_words, wordCount),
                TYPE_RESOURCE to stringResource(R.string.review_filter_to_read, resourceCount),
                TYPE_IDEA to stringResource(R.string.review_filter_to_sort, ideaCount),
            ).forEach { (value, label) ->
                MemoFilterChip(label = label, selected = filter == value, onClick = { onFilterChange(value) })
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                pluralStringResource(R.plurals.review_plan_remaining, remainingCount, dailyLimit, remainingCount),
                color = TextMuted,
                style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.weight(1f),
            )
            TextButton(onClick = onOpenSettings) { Text(stringResource(R.string.review_adjust_plan)) }
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
                    title = stringResource(R.string.review_all_done),
                    message = stringResource(R.string.review_all_done_hint),
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
                            TYPE_WORD -> stringResource(R.string.review_kind_word)
                            TYPE_RESOURCE -> stringResource(R.string.review_kind_resource)
                            else -> stringResource(R.string.review_kind_idea)
                        },
                        color = kind.accent,
                        background = kind.soft,
                        icon = kind.icon,
                    )
                    Spacer(Modifier.weight(1f))
                    Text(pluralStringResource(R.plurals.review_remaining, remainingCount, remainingCount), color = TextMuted, style = MaterialTheme.typography.labelMedium)
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
                            stringResource(R.string.review_last_next, current.lastReviewAt?.let(::formatTime) ?: stringResource(R.string.review_never), current.nextReviewAt?.let(::formatTime) ?: stringResource(R.string.review_unscheduled)),
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
                                Text(stringResource(R.string.review_show_answer))
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
                                ) { Text(stringResource(R.string.review_forgot)) }
                                OutlinedButton(
                                    onClick = { onReviewWord("fuzzy") },
                                    modifier = Modifier.weight(1f),
                                    enabled = !isSaving,
                                    shape = RoundedCornerShape(12.dp),
                                    colors = ButtonDefaults.outlinedButtonColors(contentColor = WarmAmberText),
                                ) { Text(stringResource(R.string.review_fuzzy)) }
                                Button(
                                    onClick = { onReviewWord("remembered") },
                                    modifier = Modifier.weight(1f),
                                    enabled = !isSaving,
                                    shape = RoundedCornerShape(12.dp),
                                    colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
                                ) { Text(stringResource(R.string.review_remembered)) }
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
                                    resourceCategoryLabel(current.resourceCategory, current.resourceCategoryLabel).asString(),
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
                            Text(stringResource(R.string.review_open_source))
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
                            Text(if (current.starred) stringResource(R.string.review_unstar) else stringResource(R.string.row_star))
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
                            Text(stringResource(R.string.row_sorted))
                        }
                        OutlinedButton(
                            onClick = onArchiveIdea,
                            modifier = Modifier.fillMaxWidth(),
                            enabled = !isSaving,
                            shape = RoundedCornerShape(14.dp),
                        ) {
                            Icon(Icons.Outlined.Archive, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(8.dp))
                            Text(stringResource(R.string.row_archive))
                        }
                    }
                }
                TextButton(
                    onClick = onSkip,
                    enabled = !isSaving,
                    modifier = Modifier.align(Alignment.CenterHorizontally),
                ) {
                    Text(stringResource(R.string.review_skip), color = TextMuted)
                }
            }
        }
    }
}
