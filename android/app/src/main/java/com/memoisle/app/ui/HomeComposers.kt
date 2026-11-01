package com.memoisle.app.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
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
import androidx.compose.material.icons.outlined.ContentPaste
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Lightbulb
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.memoisle.app.data.TYPE_IDEA
import com.memoisle.app.data.TYPE_IMAGE
import com.memoisle.app.data.TYPE_RESOURCE
import com.memoisle.app.data.TYPE_WORD
import com.memoisle.app.network.WordLookupResponse
import com.memoisle.app.network.WordLookupSense

// 首页快捷操作、类型筛选与各类型的快速记录输入。（从 MemoHomeScreen.kt 拆出）

@Composable
internal fun QuickActions(
    activeType: String,
    isUploadingImage: Boolean,
    onSelectWord: () -> Unit,
    onSelectIdea: () -> Unit,
    onBrowseResource: () -> Unit,
    onSelectVoice: () -> Unit,
    onSelectImage: () -> Unit,
) {
    data class Action(val kind: MemoKindStyle, val label: String, val selected: Boolean, val onClick: () -> Unit)
    val actions = listOf(
        Action(memoKindStyle(TYPE_IDEA), "写灵感", activeType == TYPE_IDEA, onSelectIdea),
        Action(memoKindStyle(TYPE_IDEA, isVoice = true), "语音记录", false, onSelectVoice),
        Action(memoKindStyle(TYPE_WORD), "记单词", activeType == TYPE_WORD, onSelectWord),
        Action(memoKindStyle(TYPE_RESOURCE), "看资料", activeType == TYPE_RESOURCE, onBrowseResource),
        Action(memoKindStyle(TYPE_IMAGE), if (isUploadingImage) "上传中" else "图片", activeType == TYPE_IMAGE, onSelectImage),
    )
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        actions.forEach { action ->
            Column(
                modifier = Modifier
                    .clip(RoundedCornerShape(14.dp))
                    .clickable(onClick = action.onClick)
                    .padding(horizontal = 4.dp, vertical = 6.dp)
                    .width(60.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                // 当前首页列表展示的类型用描边标出，比整块填色轻。
                Box(
                    modifier = Modifier
                        .size(52.dp)
                        .background(action.kind.soft, RoundedCornerShape(16.dp))
                        .then(
                            if (action.selected) {
                                Modifier.border(2.dp, action.kind.accent, RoundedCornerShape(16.dp))
                            } else {
                                Modifier
                            },
                        ),
                    contentAlignment = Alignment.Center,
                ) {
                    if (action.label == "上传中") {
                        CircularProgressIndicator(
                            modifier = Modifier.size(22.dp),
                            strokeWidth = 2.dp,
                            color = action.kind.accent,
                        )
                    } else {
                        Icon(
                            action.kind.icon,
                            contentDescription = null,
                            tint = action.kind.accent,
                            modifier = Modifier.size(26.dp),
                        )
                    }
                }
                Spacer(Modifier.height(6.dp))
                Text(
                    text = action.label,
                    color = if (action.selected) TextStrong else TextMuted,
                    style = MaterialTheme.typography.labelMedium,
                    maxLines = 1,
                )
            }
        }
    }
}

@Composable
internal fun LibraryTypeFilter(
    selected: String,
    onSelect: (String) -> Unit,
) {
    val filters = listOf(
        "" to "全部",
        TYPE_IDEA to "灵感",
        TYPE_WORD to "单词",
        TYPE_RESOURCE to "资料",
        TYPE_IMAGE to "图片",
    )
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        filters.forEach { (value, label) ->
            MemoFilterChip(
                label = label,
                selected = selected == value,
                onClick = { onSelect(value) },
                leadingIcon = if (value.isEmpty()) null else memoKindStyle(value).icon,
            )
        }
    }
}

@Composable
internal fun ImageComposerCard(
    isUploading: Boolean,
    onPickImage: () -> Unit,
) {
    val kind = memoKindStyle(TYPE_IMAGE)
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(18.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = BorderStroke(1.dp, Border),
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            KindAvatar(kind, size = 44.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text("收藏图片", style = MaterialTheme.typography.titleSmall)
                Text(
                    "上传原图，标题取自文件名，可在 Web 端补充备注。",
                    color = TextMuted,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            Spacer(Modifier.width(8.dp))
            Button(
                onClick = onPickImage,
                enabled = !isUploading,
                shape = RoundedCornerShape(12.dp),
                colors = ButtonDefaults.buttonColors(containerColor = kind.accent),
                contentPadding = PaddingValues(horizontal = 14.dp),
            ) {
                Text(if (isUploading) "上传中…" else "选择")
            }
        }
    }
}

@Composable
internal fun WordLookupControls(
    lemma: String,
    isSaving: Boolean,
    isLookingUp: Boolean,
    lookup: WordLookupResponse?,
    onLookup: () -> Unit,
    onClearLookup: () -> Unit,
    onApplyLookup: (List<WordLookupSense>) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        // 还没输入单词时不显示查词按钮，避免一个灰色按钮悬在表单中间。
        if (lemma.isNotBlank() || lookup != null) Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedButton(
                onClick = onLookup,
                enabled = lemma.isNotBlank() && !isSaving && !isLookingUp,
                shape = RoundedCornerShape(12.dp),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = WordAccent),
            ) {
                Icon(Icons.Outlined.Search, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text(if (isLookingUp) "正在查词…" else "重新查词")
            }
            if (lookup != null) {
                TextButton(onClick = onClearLookup, enabled = !isSaving) {
                    Text("清除预览")
                }
            }
        }
        lookup?.let { preview ->
            WordLookupPreview(
                preview = preview,
                busy = isSaving || isLookingUp,
                onApply = onApplyLookup,
                onDismiss = onClearLookup,
            )
        }
    }
}

@Composable
private fun WordLookupPreview(
    preview: WordLookupResponse,
    busy: Boolean,
    onApply: (List<WordLookupSense>) -> Unit,
    onDismiss: () -> Unit,
) {
    val selectionKey = preview.senses.joinToString("|") { sense ->
        "${sense.index}:${sense.definition}"
    }
    var selectedIndices by remember(preview.word, preview.lemma, selectionKey) {
        mutableStateOf(preview.senses.take(1).map { it.index })
    }
    fun toggle(index: Int) {
        selectedIndices = if (selectedIndices.contains(index)) {
            selectedIndices.filterNot { it == index }
        } else {
            selectedIndices + index
        }
    }

    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(containerColor = WordSoft),
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Column {
                    Text("词典预览", style = MaterialTheme.typography.titleSmall, color = WordAccent)
                    Text(
                        if (preview.word != preview.lemma) {
                            "按词元 ${preview.lemma} 查询"
                        } else {
                            "选择要保存的中文释义"
                        },
                        color = TextMuted,
                        style = MaterialTheme.typography.labelSmall,
                    )
                }
                TextButton(onClick = onDismiss, enabled = !busy) {
                    Text("收起")
                }
            }
            ClickablePhonetic(
                lemma = preview.word,
                phonetic = preview.phonetic,
                usAudioUrl = preview.usAudioUrl,
                ukAudioUrl = preview.ukAudioUrl,
            )
            if (preview.senses.isEmpty()) {
                Text("词典没有返回中文释义，请手动填写。", color = TextMuted)
            } else {
                preview.senses.forEach { sense ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable(enabled = !busy) { toggle(sense.index) },
                        verticalAlignment = Alignment.Top,
                    ) {
                        Checkbox(
                            checked = selectedIndices.contains(sense.index),
                            onCheckedChange = null,
                            enabled = !busy,
                        )
                        Column(
                            modifier = Modifier.padding(top = 10.dp),
                            verticalArrangement = Arrangement.spacedBy(2.dp),
                        ) {
                            sense.partOfSpeech?.let {
                                Text(
                                    it,
                                    color = WordAccent,
                                    style = MaterialTheme.typography.labelSmall,
                                )
                            }
                            Text(sense.definition)
                            sense.example?.takeIf { it.isNotBlank() }?.let {
                                Text("例句：$it", color = TextMuted, fontSize = 12.sp)
                            }
                        }
                    }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = {
                        onApply(preview.senses.filter { it.index in selectedIndices })
                    },
                    enabled = !busy && selectedIndices.isNotEmpty(),
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = WordAccent),
                ) {
                    Text("使用所选释义")
                }
                OutlinedButton(onClick = onDismiss, enabled = !busy) {
                    Text("保留手动填写")
                }
            }
        }
    }
}

@Composable
internal fun WordComposer(
    lemma: String,
    phonetic: String,
    meaning: String,
    example: String,
    isSaving: Boolean,
    isLookingUp: Boolean,
    lookup: WordLookupResponse?,
    showLookupPreview: Boolean = true,
    onLemmaChange: (String) -> Unit,
    onPhoneticChange: (String) -> Unit,
    onMeaningChange: (String) -> Unit,
    onExampleChange: (String) -> Unit,
    onFillClipboard: () -> Unit,
    onLookup: () -> Unit,
    onClearLookup: () -> Unit,
    onApplyLookup: (List<WordLookupSense>) -> Unit,
    onSave: () -> Unit,
) {
    val fieldColors = OutlinedTextFieldDefaults.colors(
        unfocusedBorderColor = Border,
        focusedBorderColor = WordAccent,
        focusedLabelColor = WordAccent,
    )
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(18.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = BorderStroke(1.dp, Border),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("收藏英语单词", style = MaterialTheme.typography.titleSmall)
                    Text(
                        if (isLookingUp) "正在填入中文释义、音标和例句…" else "输入后自动填入释义、音标和例句",
                        color = TextMuted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                TextButton(onClick = onFillClipboard, enabled = !isSaving) {
                    Icon(Icons.Outlined.ContentPaste, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(4.dp))
                    Text("剪贴板")
                }
            }
            OutlinedTextField(
                value = lemma,
                onValueChange = onLemmaChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("单词或短语") },
                placeholder = { Text("例如 serendipity") },
                singleLine = true,
                shape = RoundedCornerShape(12.dp),
                colors = fieldColors,
            )
            PhoneticPlayField(
                lemma = lemma,
                phonetic = phonetic,
                onPhoneticChange = onPhoneticChange,
                usAudioUrl = lookup?.usAudioUrl,
                ukAudioUrl = lookup?.ukAudioUrl,
            )
            if (showLookupPreview) {
                WordLookupControls(
                    lemma = lemma,
                    isSaving = isSaving,
                    isLookingUp = isLookingUp,
                    lookup = lookup,
                    onLookup = onLookup,
                    onClearLookup = onClearLookup,
                    onApplyLookup = onApplyLookup,
                )
            }
            OutlinedTextField(
                value = meaning,
                onValueChange = onMeaningChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("中文释义（自动填入）") },
                minLines = 2,
                maxLines = 5,
                shape = RoundedCornerShape(12.dp),
                colors = fieldColors,
            )
            OutlinedTextField(
                value = example,
                onValueChange = onExampleChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("例句（自动填入）") },
                minLines = 2,
                maxLines = 5,
                shape = RoundedCornerShape(12.dp),
                colors = fieldColors,
            )
            Button(
                onClick = onSave,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(48.dp),
                enabled = lemma.isNotBlank() && !isSaving,
                shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
            ) {
                Text(if (isSaving) "保存中…" else "收藏单词")
            }
        }
    }
}

@Composable
internal fun ResourceReadOnlyCard() {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(SurfaceSubtle, RoundedCornerShape(12.dp))
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Outlined.Info, contentDescription = null, tint = TextMuted, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
        Text(
            "手机上只读浏览；收藏网页可在浏览器里分享到 MemoIsle，整理请到 Web 端。",
            color = TextMuted,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
internal fun ResourceCategoryFilter(
    selected: String,
    onSelect: (String) -> Unit,
) {
    val categories = listOf(
        "" to "全部分类",
        "learning" to "学习资料",
        "article" to "文章阅读",
        "media" to "视频音频",
        "tool" to "工具服务",
        "book_paper" to "书籍论文",
        "product" to "商品好物",
        "other" to "其他",
    )
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        categories.forEach { (value, label) ->
            MemoFilterChip(label = label, selected = selected == value, onClick = { onSelect(value) })
        }
    }
}

@Composable
internal fun IdeaComposer(
    value: String,
    isSaving: Boolean,
    onValueChange: (String) -> Unit,
    onSave: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(18.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = BorderStroke(1.dp, Border),
    ) {
        Column(
            modifier = Modifier.padding(start = 16.dp, end = 12.dp, top = 6.dp, bottom = 12.dp),
        ) {
            TextField(
                value = value,
                onValueChange = onValueChange,
                modifier = Modifier.fillMaxWidth(),
                minLines = 2,
                maxLines = 7,
                placeholder = { Text("记下此刻的想法，稍后再整理……", color = TextMuted) },
                colors = TextFieldDefaults.colors(
                    focusedContainerColor = Color.Transparent,
                    unfocusedContainerColor = Color.Transparent,
                    focusedIndicatorColor = Color.Transparent,
                    unfocusedIndicatorColor = Color.Transparent,
                ),
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Outlined.Lightbulb,
                    contentDescription = null,
                    tint = IdeaAccent,
                    modifier = Modifier
                        .padding(start = 0.dp)
                        .size(18.dp),
                )
                Spacer(Modifier.width(6.dp))
                Text("保存后先进入收件箱", color = TextMuted, style = MaterialTheme.typography.labelMedium)
                Spacer(Modifier.weight(1f))
                Button(
                    onClick = onSave,
                    enabled = value.isNotBlank() && !isSaving,
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
                ) {
                    Text(if (isSaving) "保存中…" else "保存灵感")
                }
            }
        }
    }
}
