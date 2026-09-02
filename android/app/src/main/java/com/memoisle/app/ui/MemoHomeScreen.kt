package com.memoisle.app.ui

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.pm.PackageManager
import android.os.SystemClock
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.memoisle.app.MemoViewModel
import com.memoisle.app.audio.VoiceRecorder
import com.memoisle.app.audio.VoiceRecording
import com.memoisle.app.data.Memo
import com.memoisle.app.data.SyncState
import com.memoisle.app.data.TYPE_IDEA
import com.memoisle.app.data.TYPE_RESOURCE
import com.memoisle.app.data.TYPE_WORD
import com.memoisle.app.data.isVisibleInLibrary
import com.memoisle.app.data.matchesQuery
import com.memoisle.app.data.normalizeResourceUrl
import com.memoisle.app.data.resourceCategoryLabel
import com.memoisle.app.data.resourceHost
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private val displayTimeFormatter = DateTimeFormatter.ofPattern("M月d日 HH:mm")

@Composable
fun MemoHomeScreen(
    viewModel: MemoViewModel,
    sharedText: String? = null,
    onSharedTextConsumed: () -> Unit = {},
) {
    val memos by viewModel.memos.collectAsState()
    val uiState = viewModel.uiState
    val snackbarHostState = remember { SnackbarHostState() }
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    val uriHandler = LocalUriHandler.current
    val voiceRecorder = remember { VoiceRecorder(context.applicationContext) }
    var draft by rememberSaveable { mutableStateOf("") }
    var selectedMemo by remember { mutableStateOf<Memo?>(null) }
    var showCreateDialog by rememberSaveable { mutableStateOf(false) }
    var sharedResourcePending by rememberSaveable { mutableStateOf(false) }
    var activeType by rememberSaveable { mutableStateOf(TYPE_IDEA) }
    var showAllMemos by rememberSaveable { mutableStateOf(false) }
    var searchQuery by rememberSaveable { mutableStateOf("") }
    var resourceUrl by rememberSaveable { mutableStateOf("") }
    var resourceTitle by rememberSaveable { mutableStateOf("") }
    var resourceNote by rememberSaveable { mutableStateOf("") }
    var resourceCategoryFilter by rememberSaveable { mutableStateOf("") }
    var wordLemma by rememberSaveable { mutableStateOf("") }
    var wordPhonetic by rememberSaveable { mutableStateOf("") }
    var wordMeaning by rememberSaveable { mutableStateOf("") }
    var wordExample by rememberSaveable { mutableStateOf("") }
    var showVoiceDialog by rememberSaveable { mutableStateOf(false) }
    var isVoiceRecording by rememberSaveable { mutableStateOf(false) }
    var voiceRecording by remember { mutableStateOf<VoiceRecording?>(null) }
    var voiceText by rememberSaveable { mutableStateOf("") }
    var voiceElapsedMs by rememberSaveable { mutableStateOf(0) }
    var voicePermissionDenied by rememberSaveable { mutableStateOf(false) }
    val normalizedSearchQuery = searchQuery.trim()
    val visibleMemos = memos.filter { memo ->
        val typeMatches = showAllMemos || normalizedSearchQuery.isNotEmpty() ||
            memo.type == activeType
        val categoryMatches = showAllMemos || normalizedSearchQuery.isNotEmpty() ||
            activeType != TYPE_RESOURCE || resourceCategoryFilter.isEmpty() ||
            memo.resourceCategory == resourceCategoryFilter
        memo.isVisibleInLibrary() && typeMatches && categoryMatches &&
            memo.matchesQuery(normalizedSearchQuery)
    }
    val microphonePermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { granted ->
        voicePermissionDenied = !granted
        if (granted && voiceRecorder.start()) {
            voiceRecording = null
            voiceElapsedMs = 0
            isVoiceRecording = true
        }
    }

    DisposableEffect(voiceRecorder) {
        onDispose { voiceRecorder.cancel() }
    }

    LaunchedEffect(isVoiceRecording) {
        if (isVoiceRecording) {
            val startedAt = SystemClock.elapsedRealtime()
            while (isVoiceRecording) {
                voiceElapsedMs = (SystemClock.elapsedRealtime() - startedAt)
                    .coerceAtMost(Int.MAX_VALUE.toLong())
                    .toInt()
                delay(250)
            }
        }
    }

    LaunchedEffect(uiState.message) {
        uiState.message?.let { message ->
            snackbarHostState.showSnackbar(message)
            viewModel.clearMessage()
        }
    }

    LaunchedEffect(sharedText) {
        if (!sharedText.isNullOrBlank()) {
            val sharedUrl = findSharedUrl(sharedText)
            if (sharedUrl != null) {
                // 系统分享进入时直接打开资料表单，保留可识别的分享标题。
                activeType = TYPE_RESOURCE
                showAllMemos = false
                resourceUrl = sharedUrl
                resourceTitle = sharedTitle(sharedText, sharedUrl)
                sharedResourcePending = true
                showCreateDialog = true
            }
            onSharedTextConsumed()
        }
    }

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        containerColor = WarmMist,
        snackbarHost = { SnackbarHost(snackbarHostState) },
        bottomBar = {
            MemoBottomNavigation(
                showAllMemos = showAllMemos,
                onShowHome = {
                    showAllMemos = false
                    searchQuery = ""
                },
                onShowLibrary = { showAllMemos = true },
            )
        },
        floatingActionButton = {
            FloatingActionButton(
                onClick = {
                    if (activeType == TYPE_RESOURCE) {
                        activeType = TYPE_IDEA
                    }
                    sharedResourcePending = false
                    showCreateDialog = true
                },
                containerColor = DeepTeal,
                contentColor = Color.White,
                shape = RoundedCornerShape(18.dp),
            ) {
                Text("＋", fontSize = 24.sp)
            }
        },
    ) { innerPadding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .imePadding(),
            contentPadding = PaddingValues(
                start = 16.dp,
                top = 18.dp,
                end = 16.dp,
                bottom = 104.dp,
            ),
            verticalArrangement = Arrangement.spacedBy(18.dp),
        ) {
            item {
                MemoHeader(
                    isRefreshing = uiState.isRefreshing,
                    onRefresh = viewModel::refresh,
                )
            }
            item {
                MemoSearchField(
                    value = searchQuery,
                    onValueChange = { value ->
                        searchQuery = value
                        if (value.isNotBlank()) {
                            showAllMemos = true
                        }
                    },
                    onClear = { searchQuery = "" },
                )
            }
            if (!showAllMemos && normalizedSearchQuery.isEmpty()) {
                item { ReviewCard() }
                item {
                    QuickActions(
                        activeType = activeType,
                        onSelectWord = {
                            activeType = TYPE_WORD
                            showAllMemos = false
                            showCreateDialog = true
                        },
                        onSelectIdea = {
                            activeType = TYPE_IDEA
                            showAllMemos = false
                            showCreateDialog = true
                        },
                        onBrowseResource = {
                            activeType = TYPE_RESOURCE
                            showAllMemos = false
                            showCreateDialog = false
                        },
                        onSelectVoice = { showVoiceDialog = true },
                    )
                }
                item {
                    if (activeType == TYPE_IDEA) {
                        IdeaComposer(
                            value = draft,
                            isSaving = uiState.isSaving,
                            onValueChange = { draft = it },
                            onSave = {
                                viewModel.createIdea(draft) {
                                    draft = ""
                                }
                            },
                        )
                    } else if (activeType == TYPE_RESOURCE) {
                        ResourceReadOnlyCard()
                    } else {
                        WordComposer(
                            lemma = wordLemma,
                            phonetic = wordPhonetic,
                            meaning = wordMeaning,
                            example = wordExample,
                            isSaving = uiState.isSaving,
                            onLemmaChange = { wordLemma = it },
                            onPhoneticChange = { wordPhonetic = it },
                            onMeaningChange = { wordMeaning = it },
                            onExampleChange = { wordExample = it },
                            onSave = {
                                viewModel.createWord(
                                    wordLemma,
                                    wordPhonetic,
                                    wordMeaning,
                                    wordExample,
                                ) {
                                    wordLemma = ""
                                    wordPhonetic = ""
                                    wordMeaning = ""
                                    wordExample = ""
                                }
                            },
                        )
                    }
                }
                if (activeType == TYPE_RESOURCE) {
                    item {
                        ResourceCategoryFilter(
                            selected = resourceCategoryFilter,
                            onSelect = { resourceCategoryFilter = it },
                        )
                    }
                }
            }
            item {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = when {
                            normalizedSearchQuery.isNotEmpty() -> "搜索结果"
                            showAllMemos -> "全部内容"
                            else -> "最近内容"
                        },
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Spacer(Modifier.weight(1f))
                    Text(
                        text = when {
                            normalizedSearchQuery.isNotEmpty() || showAllMemos -> {
                                "${visibleMemos.size} 条内容"
                            }
                            activeType == TYPE_IDEA -> "${visibleMemos.size} 条灵感"
                            activeType == TYPE_RESOURCE -> "${visibleMemos.size} 条资料"
                            else -> "${visibleMemos.size} 个单词"
                        },
                        color = TextMuted,
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
            }
            if (visibleMemos.isEmpty()) {
                item {
                    EmptyMemos(
                        activeType = activeType,
                        isLibrary = showAllMemos,
                        hasQuery = normalizedSearchQuery.isNotEmpty(),
                    )
                }
            } else {
                items(items = visibleMemos, key = Memo::clientId) { memo ->
                    MemoRow(memo = memo, onClick = { selectedMemo = memo })
                }
            }
        }
    }

    selectedMemo?.let { memo ->
        if (memo.type == TYPE_RESOURCE) {
            ResourceDetailDialog(
                memo = memo,
                onDismiss = { selectedMemo = null },
                onOpen = { memo.sourceUrl?.let(uriHandler::openUri) },
                onCopy = {
                    val clipboard = context.getSystemService(ClipboardManager::class.java)
                    clipboard.setPrimaryClip(
                        ClipData.newPlainText("MemoIsle 网页链接", memo.sourceUrl.orEmpty()),
                    )
                    coroutineScope.launch { snackbarHostState.showSnackbar("网页链接已复制") }
                },
                onShare = {
                    val shareIntent = Intent(Intent.ACTION_SEND).apply {
                        type = "text/plain"
                        putExtra(
                            Intent.EXTRA_TEXT,
                            listOfNotNull(memo.title, memo.sourceUrl).joinToString("\n"),
                        )
                    }
                    context.startActivity(Intent.createChooser(shareIntent, "分享网页资料"))
                },
            )
        } else {
            EditMemoDialog(
                memo = memo,
                isSaving = uiState.isSaving,
                onDismiss = { selectedMemo = null },
                onSave = { title, body, phonetic, meaning, example ->
                    viewModel.updateMemo(
                        memo,
                        title,
                        body,
                        null,
                        phonetic,
                        meaning,
                        example,
                    ) {
                        selectedMemo = null
                    }
                },
                onReview = { feedback ->
                    viewModel.reviewWord(memo, feedback) {
                        selectedMemo = null
                    }
                },
                onPlayAudio = {
                    memo.id?.let { memoId -> uriHandler.openUri(viewModel.audioUrl(memoId)) }
                },
            )
        }
    }

    if (showCreateDialog && activeType == TYPE_IDEA) {
        CreateIdeaDialog(
            isSaving = uiState.isSaving,
            onDismiss = { showCreateDialog = false },
            onSave = { body ->
                viewModel.createIdea(body) { showCreateDialog = false }
            },
        )
    }
    if (showCreateDialog && activeType == TYPE_RESOURCE && sharedResourcePending) {
        CreateResourceDialog(
            url = resourceUrl,
            title = resourceTitle,
            note = resourceNote,
            isSaving = uiState.isSaving,
            onUrlChange = { resourceUrl = it },
            onTitleChange = { resourceTitle = it },
            onNoteChange = { resourceNote = it },
            onDismiss = {
                sharedResourcePending = false
                showCreateDialog = false
            },
            onSave = {
                viewModel.createSharedResource(resourceUrl, resourceTitle, resourceNote) {
                    resourceUrl = ""
                    resourceTitle = ""
                    resourceNote = ""
                    sharedResourcePending = false
                    showCreateDialog = false
                }
            },
        )
    }
    if (showCreateDialog && activeType == TYPE_WORD) {
        CreateWordDialog(
            lemma = wordLemma,
            phonetic = wordPhonetic,
            meaning = wordMeaning,
            example = wordExample,
            isSaving = uiState.isSaving,
            onLemmaChange = { wordLemma = it },
            onPhoneticChange = { wordPhonetic = it },
            onMeaningChange = { wordMeaning = it },
            onExampleChange = { wordExample = it },
            onDismiss = { showCreateDialog = false },
            onSave = {
                viewModel.createWord(wordLemma, wordPhonetic, wordMeaning, wordExample) {
                    wordLemma = ""
                    wordPhonetic = ""
                    wordMeaning = ""
                    wordExample = ""
                    showCreateDialog = false
                }
            },
        )
    }
    if (showVoiceDialog) {
        VoiceCaptureDialog(
            text = voiceText,
            isRecording = isVoiceRecording,
            recording = voiceRecording,
            elapsedMs = voiceElapsedMs,
            isSaving = uiState.isSaving,
            permissionDenied = voicePermissionDenied,
            onTextChange = { voiceText = it },
            onStart = {
                voicePermissionDenied = false
                val permission = ContextCompat.checkSelfPermission(
                    context,
                    Manifest.permission.RECORD_AUDIO,
                )
                if (permission == PackageManager.PERMISSION_GRANTED) {
                    if (voiceRecorder.start()) {
                        voiceRecording = null
                        voiceElapsedMs = 0
                        isVoiceRecording = true
                    }
                } else {
                    microphonePermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                }
            },
            onStop = {
                voiceRecording = voiceRecorder.stop()
                isVoiceRecording = false
                voiceElapsedMs = voiceRecording?.durationMs ?: 0
            },
            onReset = {
                voiceRecorder.cancel()
                voiceRecording = null
                voiceElapsedMs = 0
                isVoiceRecording = false
            },
            onDismiss = {
                voiceRecorder.cancel()
                voiceRecording = null
                voiceText = ""
                voiceElapsedMs = 0
                isVoiceRecording = false
                showVoiceDialog = false
            },
            onSave = {
                voiceRecording?.let { recording ->
                    viewModel.createVoiceIdea(
                        voiceText,
                        recording.path,
                        recording.durationMs,
                    ) {
                        voiceRecording = null
                        voiceText = ""
                        voiceElapsedMs = 0
                        activeType = TYPE_IDEA
                        showVoiceDialog = false
                    }
                }
            },
        )
    }
}

@Composable
private fun MemoHeader(isRefreshing: Boolean, onRefresh: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column {
            Text(
                text = "MemoIsle",
                color = DeepTealHover,
                fontSize = 22.sp,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = "保存值得再次遇见的内容",
                color = TextMuted,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Spacer(Modifier.weight(1f))
        TextButton(onClick = onRefresh, enabled = !isRefreshing) {
            if (isRefreshing) {
                CircularProgressIndicator(
                    modifier = Modifier.size(18.dp),
                    strokeWidth = 2.dp,
                )
                Spacer(Modifier.width(8.dp))
            }
            Text(if (isRefreshing) "同步中" else "同步")
        }
    }
}

@Composable
private fun MemoSearchField(
    value: String,
    onValueChange: (String) -> Unit,
    onClear: () -> Unit,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = Modifier.fillMaxWidth(),
        singleLine = true,
        label = { Text("搜索全部内容") },
        placeholder = { Text("标题、正文、网址、释义或标签") },
        leadingIcon = { Text("⌕", color = TextMuted, fontSize = 18.sp) },
        trailingIcon = if (value.isNotEmpty()) {
            {
                TextButton(onClick = onClear) {
                    Text("清除")
                }
            }
        } else {
            null
        },
        shape = RoundedCornerShape(12.dp),
    )
}

@Composable
private fun ReviewCard() {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = CardDefaults.outlinedCardBorder(),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column {
                    Text("今日回顾", fontWeight = FontWeight.SemiBold, fontSize = 18.sp)
                    Text(
                        "5 个单词、2 篇待读、1 条待整理",
                        color = TextMuted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                Spacer(Modifier.weight(1f))
                Box(
                    modifier = Modifier
                        .size(36.dp)
                        .background(TealSoft, CircleShape),
                    contentAlignment = Alignment.Center,
                ) {
                    Text("◷", color = DeepTeal)
                }
            }
            Button(
                onClick = {},
                modifier = Modifier.fillMaxWidth(),
                enabled = false,
            ) {
                Text("回顾功能将在下一里程碑开放")
            }
        }
    }
}

@Composable
private fun QuickActions(
    activeType: String,
    onSelectWord: () -> Unit,
    onSelectIdea: () -> Unit,
    onBrowseResource: () -> Unit,
    onSelectVoice: () -> Unit,
) {
    val actions = listOf(
        "Aa" to "记单词",
        "↗" to "看资料",
        "✦" to "写灵感",
        "●" to "语音记录",
    )
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        actions.forEach { (icon, label) ->
            val enabled = label in setOf("记单词", "看资料", "写灵感", "语音记录")
            val selected = (label == "写灵感" && activeType == TYPE_IDEA) ||
                (label == "看资料" && activeType == TYPE_RESOURCE) ||
                (label == "记单词" && activeType == TYPE_WORD)
            Column(
                modifier = Modifier.clickable(enabled = enabled) {
                    when (label) {
                        "记单词" -> onSelectWord()
                        "写灵感" -> onSelectIdea()
                        "看资料" -> onBrowseResource()
                        else -> onSelectVoice()
                    }
                },
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Box(
                    modifier = Modifier
                        .size(48.dp)
                        .background(
                            color = if (selected) TealSoft else SurfaceSubtle,
                            shape = CircleShape,
                        ),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(icon, color = if (selected) DeepTeal else TextMuted)
                }
                Spacer(Modifier.height(6.dp))
                Text(label, color = TextMuted, fontSize = 11.sp)
            }
        }
    }
}

@Composable
private fun WordComposer(
    lemma: String,
    phonetic: String,
    meaning: String,
    example: String,
    isSaving: Boolean,
    onLemmaChange: (String) -> Unit,
    onPhoneticChange: (String) -> Unit,
    onMeaningChange: (String) -> Unit,
    onExampleChange: (String) -> Unit,
    onSave: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = CardDefaults.outlinedCardBorder(),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text("收藏英语单词", fontWeight = FontWeight.SemiBold)
            OutlinedTextField(
                value = lemma,
                onValueChange = onLemmaChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("单词或短语") },
                placeholder = { Text("serendipity") },
                singleLine = true,
                shape = RoundedCornerShape(10.dp),
            )
            OutlinedTextField(
                value = phonetic,
                onValueChange = onPhoneticChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("音标（可选）") },
                singleLine = true,
                shape = RoundedCornerShape(10.dp),
            )
            OutlinedTextField(
                value = meaning,
                onValueChange = onMeaningChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("释义（可选）") },
                minLines = 2,
                maxLines = 5,
                shape = RoundedCornerShape(10.dp),
            )
            OutlinedTextField(
                value = example,
                onValueChange = onExampleChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("例句或上下文（可选）") },
                minLines = 2,
                maxLines = 5,
                shape = RoundedCornerShape(10.dp),
            )
            Button(
                onClick = onSave,
                modifier = Modifier.fillMaxWidth(),
                enabled = lemma.isNotBlank() && !isSaving,
                colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
            ) {
                Text(if (isSaving) "保存中…" else "收藏单词")
            }
        }
    }
}

@Composable
private fun ResourceReadOnlyCard() {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = CardDefaults.outlinedCardBorder(),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text("网页资料只读浏览", fontWeight = FontWeight.SemiBold)
            Text(
                "在 Web 端收藏、导入和整理网页；Android 用于搜索、查看摘要并打开原链接。" +
                    "如需从手机收藏，请在浏览器中使用系统分享。",
                color = TextMuted,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun ResourceCategoryFilter(
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
            if (selected == value) {
                Button(
                    onClick = { onSelect(value) },
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 2.dp),
                ) { Text(label, fontSize = 11.sp) }
            } else {
                OutlinedButton(
                    onClick = { onSelect(value) },
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 2.dp),
                ) { Text(label, fontSize = 11.sp) }
            }
        }
    }
}

@Composable
private fun IdeaComposer(
    value: String,
    isSaving: Boolean,
    onValueChange: (String) -> Unit,
    onSave: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = CardDefaults.outlinedCardBorder(),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("快速记录灵感", fontWeight = FontWeight.SemiBold)
            OutlinedTextField(
                value = value,
                onValueChange = onValueChange,
                modifier = Modifier.fillMaxWidth(),
                minLines = 3,
                maxLines = 7,
                placeholder = { Text("写下此刻的想法，稍后再整理……") },
                shape = RoundedCornerShape(10.dp),
            )
            Button(
                onClick = onSave,
                modifier = Modifier.fillMaxWidth(),
                enabled = value.isNotBlank() && !isSaving,
                colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
            ) {
                Text(if (isSaving) "保存中…" else "保存灵感")
            }
        }
    }
}

@Composable
private fun MemoRow(memo: Memo, onClick: () -> Unit) {
    val isResource = memo.type == TYPE_RESOURCE
    val isWord = memo.type == TYPE_WORD
    val isVoice = memo.audioMimeType != null
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = CardDefaults.outlinedCardBorder(),
    ) {
        Row(
            modifier = Modifier.padding(14.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Box(
                modifier = Modifier
                    .size(36.dp)
                    .background(
                        when {
                            isResource -> TealSoft
                            isWord -> Color(0xFFEDEFF8)
                            else -> WarmAmberSoft
                        },
                        RoundedCornerShape(10.dp),
                    ),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    when {
                        isResource -> "↗"
                        isWord -> "Aa"
                        isVoice -> "●"
                        else -> "✦"
                    },
                    color = if (isResource || isWord) DeepTeal else WarmAmberText,
                )
            }
            Spacer(Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = if (isResource && memo.starred) "★ ${memo.title}" else memo.title,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.height(3.dp))
                Text(
                    text = when {
                        isResource -> memo.resourceDescription ?: if (
                            memo.body == memo.sourceUrl
                        ) {
                            resourceHost(memo.sourceUrl.orEmpty())
                        } else {
                            memo.body
                        }
                        isWord -> memo.wordPhonetic ?: memo.wordMeaning ?: "等待补充释义"
                        else -> memo.body
                    },
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    color = TextMuted,
                    style = MaterialTheme.typography.bodySmall,
                )
                Spacer(Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = formatTime(memo.updatedAt),
                        color = TextMuted,
                        fontSize = 11.sp,
                    )
                    Spacer(Modifier.width(8.dp))
                    if (isWord) {
                        Text(
                            "熟悉度 ${memo.familiarity}/5",
                            color = TextMuted,
                            fontSize = 11.sp,
                        )
                        Spacer(Modifier.width(8.dp))
                    }
                    if (isResource) {
                        Text(
                            resourceCategoryLabel(memo.resourceCategory),
                            color = DeepTeal,
                            fontSize = 11.sp,
                        )
                        Spacer(Modifier.width(8.dp))
                    }
                    SyncBadge(memo.syncState)
                }
            }
        }
    }
}

@Composable
private fun SyncBadge(syncState: SyncState) {
    val (label, color) = when (syncState) {
        SyncState.SYNCED -> "已同步" to DeepTeal
        SyncState.PENDING -> "等待同步" to TextMuted
        SyncState.FAILED -> "同步失败" to MaterialTheme.colorScheme.error
    }
    Text(
        text = label,
        color = color,
        fontSize = 11.sp,
        fontWeight = FontWeight.Medium,
    )
}

@Composable
private fun EmptyMemos(
    activeType: String,
    isLibrary: Boolean,
    hasQuery: Boolean,
) {
    val isResource = activeType == TYPE_RESOURCE
    val isWord = activeType == TYPE_WORD
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(SurfaceWhite, RoundedCornerShape(14.dp))
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            when {
                hasQuery -> "⌕"
                isLibrary -> "□"
                isResource -> "↗"
                isWord -> "Aa"
                else -> "✦"
            },
            color = DeepTeal,
            fontSize = 24.sp,
        )
        Text(
            when {
                hasQuery -> "没有找到匹配内容"
                isLibrary -> "资料库还是空的"
                isResource -> "还没有收藏网页资料"
                isWord -> "从第一个英语单词开始"
                else -> "第一条灵感正在等你"
            },
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            when {
                hasQuery -> "换个关键词，或清除搜索后浏览全部收藏。"
                isLibrary -> "从灵感、英语单词或网页资料开始收藏第一条内容。"
                isResource -> "可在 Web 端收藏，或从手机浏览器分享链接到 MemoIsle。"
                isWord -> "保存词形、释义和例句，稍后按计划复习。"
                else -> "保存后会进入本地资料库，并在联网时同步到 Web。"
            },
            color = TextMuted,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun ResourceDetailDialog(
    memo: Memo,
    onDismiss: () -> Unit,
    onOpen: () -> Unit,
    onCopy: () -> Unit,
    onShare: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("网页资料", color = DeepTeal, fontSize = 12.sp)
                Text(
                    if (memo.starred) "★ ${memo.title}" else memo.title,
                    fontWeight = FontWeight.SemiBold,
                )
            }
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        resourceCategoryLabel(memo.resourceCategory),
                        modifier = Modifier
                            .background(TealSoft, RoundedCornerShape(20.dp))
                            .padding(horizontal = 10.dp, vertical = 5.dp),
                        color = DeepTeal,
                        fontSize = 11.sp,
                    )
                    if (memo.starred) {
                        Text(
                            "★ 星标",
                            modifier = Modifier
                                .background(SurfaceSubtle, RoundedCornerShape(20.dp))
                                .padding(horizontal = 10.dp, vertical = 5.dp),
                            color = TextMuted,
                            fontSize = 11.sp,
                        )
                    }
                }
                memo.resourceDescription?.let { description ->
                    Text(description, style = MaterialTheme.typography.bodyMedium)
                }
                if (memo.body != memo.sourceUrl && memo.body.isNotBlank()) {
                    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        Text("个人备注", color = TextMuted, fontSize = 11.sp)
                        Text(memo.body, style = MaterialTheme.typography.bodyMedium)
                    }
                }
                Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                    Text(
                        memo.resourceSiteName ?: resourceHost(memo.sourceUrl.orEmpty()),
                        color = TextMuted,
                        fontSize = 11.sp,
                    )
                    Text(
                        memo.sourceUrl.orEmpty(),
                        color = DeepTeal,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                Text(
                    "Android 端只读展示；标题、网址、备注、分类和星标请在 Web 端整理。",
                    color = TextMuted,
                    style = MaterialTheme.typography.labelSmall,
                )
            }
        },
        confirmButton = {
            Button(
                onClick = onOpen,
                enabled = memo.sourceUrl != null,
                colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
            ) { Text("打开原网页") }
        },
        dismissButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                TextButton(onClick = onCopy, enabled = memo.sourceUrl != null) {
                    Text("复制")
                }
                TextButton(onClick = onShare, enabled = memo.sourceUrl != null) {
                    Text("分享")
                }
                OutlinedButton(onClick = onDismiss) { Text("关闭") }
            }
        },
        containerColor = SurfaceWhite,
        shape = RoundedCornerShape(14.dp),
    )
}

@Composable
private fun EditMemoDialog(
    memo: Memo,
    isSaving: Boolean,
    onDismiss: () -> Unit,
    onSave: (String, String, String?, String?, String?) -> Unit,
    onReview: (String) -> Unit,
    onPlayAudio: () -> Unit,
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
    var showWordAnswer by rememberSaveable(memo.clientId) { mutableStateOf(false) }
    val isWord = memo.type == TYPE_WORD

    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                when {
                    isWord -> "学习单词"
                    else -> "继续整理"
                },
                fontWeight = FontWeight.SemiBold,
            )
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                if (memo.audioMimeType != null) {
                    Button(
                        onClick = onPlayAudio,
                        modifier = Modifier.fillMaxWidth(),
                        enabled = memo.id != null,
                        colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
                    ) {
                        val seconds = (memo.audioDurationMs ?: 0) / 1_000
                        Text(if (seconds > 0) "播放原始录音 · ${seconds}秒" else "播放原始录音")
                    }
                }
                OutlinedTextField(
                    value = title,
                    onValueChange = { title = it },
                    label = { Text(if (isWord) "单词或短语" else "标题") },
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(10.dp),
                )
                if (isWord) {
                    OutlinedTextField(
                        value = wordPhonetic,
                        onValueChange = { wordPhonetic = it },
                        label = { Text("音标（可选）") },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        shape = RoundedCornerShape(10.dp),
                    )
                    if (!showWordAnswer) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .background(SurfaceSubtle, RoundedCornerShape(12.dp))
                                .padding(18.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Text("先回想释义和例句", color = TextMuted)
                            OutlinedButton(onClick = { showWordAnswer = true }) {
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
                            shape = RoundedCornerShape(10.dp),
                        )
                        OutlinedTextField(
                            value = wordExample,
                            onValueChange = { wordExample = it },
                            label = { Text("例句或上下文") },
                            modifier = Modifier.fillMaxWidth(),
                            minLines = 2,
                            maxLines = 5,
                            shape = RoundedCornerShape(10.dp),
                        )
                        Text(
                            "熟悉度 ${memo.familiarity}/5 · 已复习 ${memo.reviewCount} 次",
                            color = TextMuted,
                            style = MaterialTheme.typography.labelSmall,
                        )
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            OutlinedButton(
                                onClick = { onReview("forgot") },
                                modifier = Modifier.weight(1f),
                                enabled = !isSaving,
                            ) { Text("忘记") }
                            OutlinedButton(
                                onClick = { onReview("fuzzy") },
                                modifier = Modifier.weight(1f),
                                enabled = !isSaving,
                            ) { Text("模糊") }
                            Button(
                                onClick = { onReview("remembered") },
                                modifier = Modifier.weight(1f),
                                enabled = !isSaving,
                            ) { Text("记得") }
                        }
                    }
                } else {
                    OutlinedTextField(
                        value = body,
                        onValueChange = { body = it },
                        label = { Text("内容") },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 5,
                        maxLines = 12,
                        shape = RoundedCornerShape(10.dp),
                    )
                }
                HorizontalDivider(color = Border)
                Text(
                    "服务端版本 ${memo.version}",
                    color = TextMuted,
                    style = MaterialTheme.typography.labelSmall,
                )
            }
        },
        confirmButton = {
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
                enabled = title.isNotBlank() &&
                    when {
                        isWord -> true
                        else -> body.isNotBlank()
                    } &&
                    !isSaving,
            ) {
                Text(if (isSaving) "保存中…" else "保存修改")
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
private fun CreateIdeaDialog(
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
private fun CreateResourceDialog(
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
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("保存分享的网页", fontWeight = FontWeight.SemiBold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    "确认浏览器分享的链接；保存后资料在 Android 端只读，完整整理请使用 Web。",
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
                    shape = RoundedCornerShape(10.dp),
                )
                OutlinedTextField(
                    value = title,
                    onValueChange = onTitleChange,
                    label = { Text("标题（可选）") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    shape = RoundedCornerShape(10.dp),
                )
                OutlinedTextField(
                    value = note,
                    onValueChange = onNoteChange,
                    label = { Text("个人备注（可选）") },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 3,
                    maxLines = 7,
                    shape = RoundedCornerShape(10.dp),
                )
            }
        },
        confirmButton = {
            Button(
                onClick = onSave,
                enabled = normalizeResourceUrl(url) != null && !isSaving,
            ) {
                Text(if (isSaving) "保存中…" else "保存资料")
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
private fun CreateWordDialog(
    lemma: String,
    phonetic: String,
    meaning: String,
    example: String,
    isSaving: Boolean,
    onLemmaChange: (String) -> Unit,
    onPhoneticChange: (String) -> Unit,
    onMeaningChange: (String) -> Unit,
    onExampleChange: (String) -> Unit,
    onDismiss: () -> Unit,
    onSave: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("收藏英语单词", fontWeight = FontWeight.SemiBold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(
                    value = lemma,
                    onValueChange = onLemmaChange,
                    label = { Text("单词或短语") },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("serendipity") },
                    singleLine = true,
                    shape = RoundedCornerShape(10.dp),
                )
                OutlinedTextField(
                    value = phonetic,
                    onValueChange = onPhoneticChange,
                    label = { Text("音标（可选）") },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    shape = RoundedCornerShape(10.dp),
                )
                OutlinedTextField(
                    value = meaning,
                    onValueChange = onMeaningChange,
                    label = { Text("释义（可选）") },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 3,
                    maxLines = 6,
                    shape = RoundedCornerShape(10.dp),
                )
                OutlinedTextField(
                    value = example,
                    onValueChange = onExampleChange,
                    label = { Text("例句或上下文（可选）") },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 2,
                    maxLines = 5,
                    shape = RoundedCornerShape(10.dp),
                )
            }
        },
        confirmButton = {
            Button(
                onClick = onSave,
                enabled = lemma.isNotBlank() && !isSaving,
            ) {
                Text(if (isSaving) "保存中…" else "收藏单词")
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
private fun VoiceCaptureDialog(
    text: String,
    isRecording: Boolean,
    recording: VoiceRecording?,
    elapsedMs: Int,
    isSaving: Boolean,
    permissionDenied: Boolean,
    onTextChange: (String) -> Unit,
    onStart: () -> Unit,
    onStop: () -> Unit,
    onReset: () -> Unit,
    onDismiss: () -> Unit,
    onSave: () -> Unit,
) {
    val seconds = elapsedMs / 1_000
    AlertDialog(
        onDismissRequest = { if (!isRecording && !isSaving) onDismiss() },
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
                        Text(
                            "●",
                            color = if (isRecording) WarmAmberText else DeepTeal,
                            fontSize = 24.sp,
                        )
                        Text(
                            "${seconds}秒",
                            fontWeight = FontWeight.SemiBold,
                        )
                        Text(
                            when {
                                isRecording -> "正在录音"
                                recording != null -> "录音已就绪"
                                else -> "等待开始"
                            },
                            color = TextMuted,
                            fontSize = 11.sp,
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
                    label = { Text("配套文字（可选）") },
                    placeholder = { Text("写下关键词或整理后的文字") },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 3,
                    maxLines = 7,
                    enabled = !isSaving,
                    shape = RoundedCornerShape(10.dp),
                )
                Text(
                    "原始录音只保存到你的私人资料库。",
                    color = TextMuted,
                    style = MaterialTheme.typography.labelSmall,
                )
            }
        },
        confirmButton = {
            when {
                isRecording -> Button(onClick = onStop) { Text("结束录音") }
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
                    onClick = onDismiss,
                    enabled = !isRecording && !isSaving,
                ) {
                    Text("取消")
                }
            }
        },
        containerColor = SurfaceWhite,
        shape = RoundedCornerShape(14.dp),
    )
}

@Composable
private fun MemoBottomNavigation(
    showAllMemos: Boolean,
    onShowHome: () -> Unit,
    onShowLibrary: () -> Unit,
) {
    NavigationBar(containerColor = SurfaceWhite) {
        NavigationBarItem(
            selected = !showAllMemos,
            onClick = onShowHome,
            icon = { Text("⌂", fontSize = 17.sp) },
            label = { Text("首页", fontSize = 11.sp) },
            colors = memoNavigationColors(),
        )
        NavigationBarItem(
            selected = showAllMemos,
            onClick = onShowLibrary,
            icon = { Text("□", fontSize = 17.sp) },
            label = { Text("资料库", fontSize = 11.sp) },
            colors = memoNavigationColors(),
        )
        listOf("◷" to "回顾", "○" to "我的").forEach { (icon, label) ->
            NavigationBarItem(
                selected = false,
                onClick = {},
                enabled = false,
                icon = { Text(icon, fontSize = 17.sp) },
                label = { Text(label, fontSize = 11.sp) },
                colors = memoNavigationColors(),
            )
        }
    }
}

@Composable
private fun memoNavigationColors() = NavigationBarItemDefaults.colors(
    selectedIconColor = DeepTeal,
    selectedTextColor = DeepTeal,
    indicatorColor = TealSoft,
    disabledIconColor = TextMuted.copy(alpha = 0.42f),
    disabledTextColor = TextMuted.copy(alpha = 0.42f),
)

private fun formatTime(value: String): String {
    return runCatching {
        val dateTime = Instant.parse(value).atZone(ZoneId.systemDefault())
        displayTimeFormatter.format(dateTime)
    }.getOrDefault(value)
}

private fun findSharedUrl(value: String): String? {
    val urlPattern = Regex("https?://[^\\s]+", RegexOption.IGNORE_CASE)
    val matchedUrl = urlPattern.find(value)?.value?.trimEnd('.', ',', '，', '。', ')')
    return matchedUrl?.let(::normalizeResourceUrl)
        ?: value.lineSequence().mapNotNull(::normalizeResourceUrl).firstOrNull()
}

private fun sharedTitle(value: String, url: String): String {
    return value.lineSequence()
        .map(String::trim)
        .firstOrNull { line -> line.isNotEmpty() && !line.contains(url) }
        ?.take(200)
        .orEmpty()
}
