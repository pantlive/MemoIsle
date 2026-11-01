package com.memoisle.app.ui

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.pm.PackageManager
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.Logout
import androidx.compose.material.icons.filled.CollectionsBookmark
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Autorenew
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.CollectionsBookmark
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.FileDownload
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Inbox
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Sync
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.memoisle.app.MemoViewModel
import com.memoisle.app.VaultViewModel
import com.memoisle.app.audio.SherpaOnnxSpeechToText
import com.memoisle.app.audio.VoiceRecorder
import com.memoisle.app.audio.VoiceRecording
import com.memoisle.app.data.Memo
import com.memoisle.app.data.SyncState
import com.memoisle.app.data.TYPE_IDEA
import com.memoisle.app.data.TYPE_IMAGE
import com.memoisle.app.data.TYPE_RESOURCE
import com.memoisle.app.data.TYPE_WORD
import com.memoisle.app.data.assignedCategoryCodes
import com.memoisle.app.data.isDueWord
import com.memoisle.app.data.isInTrash
import com.memoisle.app.data.isInboxIdea
import com.memoisle.app.data.isUnreadResource
import com.memoisle.app.data.isVisibleInLibrary
import com.memoisle.app.data.matchesQuery
import com.memoisle.app.data.newLocalWord
import com.memoisle.app.data.normalizeResourceUrl
import com.memoisle.app.data.parseClipboardWord
import com.memoisle.app.data.todayReviewCounts
import com.memoisle.app.data.todayReviewItems
import com.memoisle.app.network.WordLookupResponse
import com.memoisle.app.network.WordLookupSense
import java.nio.file.Paths
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private val displayTimeFormatter = DateTimeFormatter.ofPattern("M月d日 HH:mm")

@Composable
fun MemoHomeScreen(
    viewModel: MemoViewModel,
    vaultViewModel: VaultViewModel,
    sharedText: String? = null,
    onSharedTextConsumed: () -> Unit = {},
    onLogout: () -> Unit = {},
) {
    val memos by viewModel.memos.collectAsState()
    val uiState = viewModel.uiState
    val snackbarHostState = remember { SnackbarHostState() }
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()
    val uriHandler = LocalUriHandler.current
    val voiceRecorder = remember { VoiceRecorder(context.applicationContext) }
    val speechToText = remember(context) { SherpaOnnxSpeechToText(context) }
    val exportLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.CreateDocument("application/json"),
    ) { uri ->
        if (uri != null) {
            viewModel.exportUserData(uri, context.contentResolver)
        }
    }
    var draft by rememberSaveable { mutableStateOf("") }
    var selectedMemo by remember { mutableStateOf<Memo?>(null) }
    var showCreateDialog by rememberSaveable { mutableStateOf(false) }
    var sharedResourcePending by rememberSaveable { mutableStateOf(false) }
    var activeType by rememberSaveable { mutableStateOf(TYPE_IDEA) }
    var libraryTypeFilter by rememberSaveable { mutableStateOf("") }
    var showAllMemos by rememberSaveable { mutableStateOf(false) }
    var showReview by rememberSaveable { mutableStateOf(false) }
    var showTrash by rememberSaveable { mutableStateOf(false) }
    var showInbox by rememberSaveable { mutableStateOf(false) }
    var showVault by rememberSaveable { mutableStateOf(false) }
    var pendingPermanentDelete by remember { mutableStateOf<Memo?>(null) }
    var pendingMoveToTrash by remember { mutableStateOf<Memo?>(null) }
    var showReviewAnswer by rememberSaveable { mutableStateOf(false) }
    var searchQuery by rememberSaveable { mutableStateOf("") }
    var resourceUrl by rememberSaveable { mutableStateOf("") }
    var resourceTitle by rememberSaveable { mutableStateOf("") }
    var resourceNote by rememberSaveable { mutableStateOf("") }
    var resourceCategoryFilter by rememberSaveable { mutableStateOf("") }
    var wordLemma by rememberSaveable { mutableStateOf("") }
    var wordPhonetic by rememberSaveable { mutableStateOf("") }
    var wordMeaning by rememberSaveable { mutableStateOf("") }
    var wordExample by rememberSaveable { mutableStateOf("") }
    val wordDraft = remember {
        object {
            var lemma = ""
            var phonetic = ""
            var meaning = ""
            var example = ""
            var autoPhonetic = ""
            var autoMeaning = ""
            var autoExample = ""
        }
    }
    wordDraft.lemma = wordLemma
    wordDraft.phonetic = wordPhonetic
    wordDraft.meaning = wordMeaning
    wordDraft.example = wordExample
    var reviewFilter by rememberSaveable { mutableStateOf("all") }
    var showVoiceDialog by rememberSaveable { mutableStateOf(false) }
    var isVoiceRecording by rememberSaveable { mutableStateOf(false) }
    var isVoicePaused by rememberSaveable { mutableStateOf(false) }
    var voiceRecording by remember { mutableStateOf<VoiceRecording?>(null) }
    var voiceText by rememberSaveable { mutableStateOf("") }
    var voiceElapsedMs by rememberSaveable { mutableStateOf(0) }
    var voiceAmplitude by rememberSaveable { mutableStateOf(0) }
    var voicePermissionDenied by rememberSaveable { mutableStateOf(false) }
    var isVoiceTranscribing by rememberSaveable { mutableStateOf(false) }
    var voiceTranscriptionMessage by rememberSaveable { mutableStateOf<String?>(null) }
    var showVoiceDiscardConfirm by rememberSaveable { mutableStateOf(false) }
    var pendingConflictMemo by remember { mutableStateOf<Memo?>(null) }
    var resetEditorToServerMemo by remember { mutableStateOf<Memo?>(null) }
    var showLogoutDialog by rememberSaveable { mutableStateOf(false) }
    var isPreparingLogout by rememberSaveable { mutableStateOf(false) }
    val normalizedSearchQuery = searchQuery.trim()
    // 以下派生数据只在依赖变化时重算：录音计时、输入框打字等无关重组
    // 不再对整张 memo 表做多次过滤和全文匹配。
    val visibleMemos = remember(
        memos,
        showAllMemos,
        normalizedSearchQuery,
        activeType,
        libraryTypeFilter,
        resourceCategoryFilter,
    ) { memos.filter { memo ->
        val typeMatches = showAllMemos || normalizedSearchQuery.isNotEmpty() ||
            memo.type == activeType
        val libraryTypeMatches = !showAllMemos || libraryTypeFilter.isEmpty() ||
            memo.type == libraryTypeFilter
        val categoryMatches = showAllMemos || normalizedSearchQuery.isNotEmpty() ||
            activeType != TYPE_RESOURCE || resourceCategoryFilter.isEmpty() ||
            memo.assignedCategoryCodes().contains(resourceCategoryFilter)
        memo.isVisibleInLibrary() && typeMatches && libraryTypeMatches && categoryMatches &&
            memo.matchesQuery(normalizedSearchQuery)
    } }
    val libraryMemos = remember(memos) { memos.filter { it.isVisibleInLibrary() } }
    val trashMemos = remember(memos, normalizedSearchQuery) {
        memos.filter { memo ->
            memo.isInTrash() && memo.matchesQuery(normalizedSearchQuery)
        }
    }
    val inboxMemos = remember(memos, normalizedSearchQuery) {
        memos.filter { memo ->
            memo.status == "inbox" && memo.matchesQuery(normalizedSearchQuery)
        }
    }
    // 到期判断依赖当前时间：每分钟换一次键，开着应用时到点的单词也能出现，
    // 同时避免像以前那样每次重组都重算。
    var reviewClockMinute by remember { mutableStateOf(System.currentTimeMillis() / 60_000) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(60_000)
            reviewClockMinute = System.currentTimeMillis() / 60_000
        }
    }
    val reviewCounts = remember(libraryMemos, reviewClockMinute) {
        libraryMemos.todayReviewCounts()
    }
    val reviewLimit = uiState.reviewSettings.dailyLimit
    val reviewItems = remember(libraryMemos, reviewLimit, reviewClockMinute) {
        libraryMemos.todayReviewItems(limit = reviewLimit)
    }
    val filteredReviewItems = remember(
        libraryMemos,
        reviewItems,
        reviewFilter,
        reviewLimit,
        reviewClockMinute,
    ) {
        when (reviewFilter) {
            TYPE_WORD -> libraryMemos.filter { it.isDueWord() }.take(reviewLimit)
            TYPE_RESOURCE -> libraryMemos.filter { it.isUnreadResource() }.take(reviewLimit)
            TYPE_IDEA -> libraryMemos.filter { it.isInboxIdea() }.take(reviewLimit)
            else -> reviewItems
        }
    }
    val currentReview = filteredReviewItems.firstOrNull()
    var showReviewSettingsDialog by rememberSaveable { mutableStateOf(false) }

    val imagePickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.PickVisualMedia(),
    ) { uri ->
        if (uri != null) {
            viewModel.createImageMemo(uri, context.contentResolver) { created ->
                // 上传成功后直接进入资料库的图片视图并打开详情，方便确认结果。
                activeType = TYPE_IMAGE
                libraryTypeFilter = TYPE_IMAGE
                showAllMemos = true
                showReview = false
                showTrash = false
                showInbox = false
                searchQuery = ""
                selectedMemo = created
            }
        }
    }

    fun resetVoiceRecording() {
        voiceRecorder.cancel()
        voiceRecording = null
        isVoiceRecording = false
        isVoicePaused = false
        voiceAmplitude = 0
        isVoiceTranscribing = false
        voiceTranscriptionMessage = null
        voiceElapsedMs = 0
    }

    fun discardVoiceCapture() {
        resetVoiceRecording()
        voiceText = ""
        showVoiceDiscardConfirm = false
        showVoiceDialog = false
    }

    fun requestVoiceDismiss() {
        if (uiState.isSaving) {
            return
        }
        if (isVoiceRecording || voiceRecording != null || voiceText.isNotBlank()) {
            showVoiceDiscardConfirm = true
        } else {
            discardVoiceCapture()
        }
    }

    fun openMemo(memo: Memo): Unit {
        selectedMemo = memo
        if (memo.syncState == SyncState.CONFLICT && memo.id != null) {
            // 重启后重新读取服务端版本，确保冲突仍然可以选择两边内容。
            viewModel.loadConflictServer(memo) { serverMemo ->
                if (selectedMemo?.clientId == memo.clientId) {
                    selectedMemo = serverMemo
                    pendingConflictMemo = serverMemo
                    resetEditorToServerMemo = null
                }
            }
        }
    }

    fun requestLogout(): Unit {
        if (uiState.isSaving || isPreparingLogout) {
            coroutineScope.launch {
                snackbarHostState.showSnackbar("当前还有内容正在保存，请稍后再退出")
            }
            return
        }
        if (viewModel.unsyncedCount() == 0) {
            onLogout()
        } else {
            showLogoutDialog = true
        }
    }

    fun syncAndLogout(): Unit {
        if (isPreparingLogout) {
            return
        }
        isPreparingLogout = true
        viewModel.syncBeforeLogout { completed ->
            isPreparingLogout = false
            if (completed) {
                showLogoutDialog = false
                onLogout()
            } else {
                coroutineScope.launch {
                    snackbarHostState.showSnackbar("同步未完成，当前仍保持登录，内容不会被清理")
                }
            }
        }
    }
    fun fillWordFromClipboard(overwrite: Boolean = false): Boolean {
        val clipboard = context.getSystemService(ClipboardManager::class.java) ?: return false
        val text = clipboard.primaryClip
            ?.takeIf { it.itemCount > 0 }
            ?.getItemAt(0)
            ?.coerceToText(context)
            ?.toString()
            .orEmpty()
        val draft = parseClipboardWord(text) ?: return false
        if (overwrite) {
            viewModel.clearWordLookup()
        }
        if (overwrite || wordLemma.isBlank()) {
            wordLemma = draft.lemma
        }
        if (!draft.phonetic.isNullOrBlank() && (overwrite || wordPhonetic.isBlank())) {
            wordPhonetic = draft.phonetic
        }
        if (!draft.meaning.isNullOrBlank() && (overwrite || wordMeaning.isBlank())) {
            wordMeaning = draft.meaning
        }
        if (!draft.example.isNullOrBlank() && (overwrite || wordExample.isBlank())) {
            wordExample = draft.example
        }
        coroutineScope.launch {
            snackbarHostState.showSnackbar("已从剪贴板填入「${draft.lemma}」")
        }
        return true
    }

    fun applyDictionaryPreview(
        preview: WordLookupResponse,
        selectedSenses: List<WordLookupSense> = preview.senses.take(4),
    ): List<String> {
        val filled = mutableListOf<String>()
        val meaning = selectedSenses.joinToString("\n") { sense ->
            if (sense.partOfSpeech.isNullOrBlank()) {
                sense.definition
            } else {
                "${sense.partOfSpeech}: ${sense.definition}"
            }
        }
        val example = selectedSenses.firstOrNull { !it.example.isNullOrBlank() }
            ?.example
            .orEmpty()
        val phonetic = preview.phonetic.orEmpty()
        if (
            phonetic.isNotBlank() &&
            (wordDraft.phonetic.isBlank() || wordDraft.phonetic == wordDraft.autoPhonetic)
        ) {
            wordPhonetic = phonetic
            wordDraft.autoPhonetic = phonetic
            filled += "音标"
        }
        if (
            meaning.isNotBlank() &&
            (wordDraft.meaning.isBlank() || wordDraft.meaning == wordDraft.autoMeaning)
        ) {
            wordMeaning = meaning
            wordDraft.autoMeaning = meaning
            filled += "中文释义"
        }
        if (
            example.isNotBlank() &&
            (wordDraft.example.isBlank() || wordDraft.example == wordDraft.autoExample)
        ) {
            wordExample = example
            wordDraft.autoExample = example
            filled += "例句"
        }
        return filled
    }

    fun applyWordLookup(senses: List<WordLookupSense>) {
        val preview = viewModel.uiState.wordLookup
        if (preview != null) {
            applyDictionaryPreview(preview, senses)
        }
        viewModel.clearWordLookup()
        coroutineScope.launch {
            snackbarHostState.showSnackbar("已应用所选释义；手工填写内容已保留")
        }
    }

    val microphonePermissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { granted ->
        voicePermissionDenied = !granted
        if (granted && voiceRecorder.start()) {
            voiceRecording = null
            voiceElapsedMs = 0
            voiceAmplitude = 0
            isVoicePaused = false
            isVoiceRecording = true
        }
    }

    DisposableEffect(voiceRecorder) {
        onDispose { voiceRecorder.cancel() }
    }

    DisposableEffect(speechToText) {
        onDispose { speechToText.close() }
    }

    LaunchedEffect(isVoiceRecording) {
        if (isVoiceRecording) {
            while (isVoiceRecording) {
                voiceElapsedMs = voiceRecorder.elapsedMs()
                delay(250)
            }
        }
    }

    LaunchedEffect(isVoiceRecording, isVoicePaused) {
        if (isVoiceRecording && !isVoicePaused) {
            while (isVoiceRecording && !isVoicePaused) {
                voiceAmplitude = voiceRecorder.amplitudePercent()
                delay(100)
            }
        }
        voiceAmplitude = 0
    }

    LaunchedEffect(voiceRecording?.path) {
        val recording = voiceRecording ?: return@LaunchedEffect
        if (isVoiceRecording) {
            return@LaunchedEffect
        }
        isVoiceTranscribing = true
        voiceTranscriptionMessage = if (speechToText.isAvailable) {
            "正在使用设备端 SenseVoice 转写…"
        } else {
            "首次使用正在下载设备端语音模型（约 160 MB）…"
        }
        val modelResult = speechToText.ensureAvailable()
        if (modelResult.isFailure) {
            isVoiceTranscribing = false
            voiceTranscriptionMessage = modelResult.exceptionOrNull()?.message
                ?: "设备端模型下载失败，可手动填写文字。"
            return@LaunchedEffect
        }
        voiceTranscriptionMessage = "正在使用设备端 SenseVoice 转写…"
        val result = speechToText.transcribe(Paths.get(recording.path))
        result.onSuccess { transcript ->
            if (voiceText.isBlank()) {
                voiceText = transcript
            }
            isVoiceTranscribing = false
            voiceTranscriptionMessage = if (transcript.isBlank()) {
                "未识别到可用文字，请手动补充。"
            } else {
                "转写完成，可直接编辑结果。"
            }
        }.onFailure { error ->
            isVoiceTranscribing = false
            voiceTranscriptionMessage = error.message ?: "设备端转写失败，可手动填写文字。"
        }
    }

    LaunchedEffect(wordLemma, activeType) {
        if (activeType != TYPE_WORD) {
            return@LaunchedEffect
        }
        val cleaned = wordLemma.trim()
        if (parseClipboardWord(cleaned) == null) {
            return@LaunchedEffect
        }
        delay(450)
        viewModel.lookupWord(
            cleaned,
            silent = true,
            showPreview = false,
        ) { preview ->
            val filled = applyDictionaryPreview(preview)
            if (filled.isNotEmpty()) {
                coroutineScope.launch {
                    snackbarHostState.showSnackbar("已自动填入${filled.joinToString("、")}")
                }
            }
        }
    }

    LaunchedEffect(uiState.message) {
        uiState.message?.let { message ->
            val result = snackbarHostState.showSnackbar(
                message = message,
                actionLabel = if (
                    uiState.undoMemo != null &&
                    (message.contains("已保存") || message.contains("已收藏"))
                ) {
                    "撤销"
                } else {
                    null
                },
            )
            if (result == SnackbarResult.ActionPerformed) {
                viewModel.undoLastSave()
            } else {
                viewModel.clearMessage()
            }
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

    LaunchedEffect(activeType) {
        if (activeType == TYPE_RESOURCE) viewModel.loadQuickAccess()
    }

    if (showVault) {
        VaultScreen(viewModel = vaultViewModel, onClose = { showVault = false })
        return
    }

    val isHome = !showAllMemos && !showReview && !showTrash && !showInbox
    val inboxCount = remember(memos) { memos.count { it.status == "inbox" } }
    fun showHome() {
        showAllMemos = false
        showReview = false
        showTrash = false
        showInbox = false
        searchQuery = ""
    }
    // 收件箱、回收站、资料库和回顾里按返回先回首页，不再直接退出应用。
    BackHandler(enabled = !isHome) { showHome() }
    // 各页面共用同一个列表，切换页面或首页类型时回到顶部，不停在上一页的滚动位置。
    val listState = rememberLazyListState()
    LaunchedEffect(showAllMemos, showReview, showTrash, showInbox, activeType, libraryTypeFilter) {
        listState.scrollToItem(0)
    }

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        containerColor = WarmMist,
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            MemoTopBar(
                title = when {
                    showInbox -> "收件箱"
                    showTrash -> "回收站"
                    showReview -> "今日回顾"
                    showAllMemos -> "资料库"
                    else -> "MemoIsle"
                },
                subtitle = when {
                    showInbox -> "${inboxMemos.size} 条待整理"
                    showTrash -> "${trashMemos.size} 条 · 保留 30 天后永久删除"
                    else -> null
                },
                brand = isHome,
                navigationIcon = if (showInbox || showTrash) {
                    {
                        IconButton(onClick = ::showHome) {
                            Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "返回首页")
                        }
                    }
                } else {
                    null
                },
            ) {
                TopBarActions(
                    inboxCount = inboxCount,
                    showInboxAction = !showInbox,
                    showTrashAction = !showTrash,
                    isRefreshing = uiState.isRefreshing,
                    isSaving = uiState.isSaving,
                    isExporting = uiState.isExporting,
                    onShowInbox = {
                        showInbox = true
                        showTrash = false
                        showReview = false
                        showAllMemos = false
                        selectedMemo = null
                    },
                    onShowTrash = {
                        showTrash = true
                        showInbox = false
                        showReview = false
                        showAllMemos = false
                        selectedMemo = null
                    },
                    onRefresh = viewModel::refresh,
                    onExport = { exportLauncher.launch("memoisle-export.json") },
                    onLogout = ::requestLogout,
                )
            }
        },
        bottomBar = {
            MemoBottomNavigation(
                showAllMemos = showAllMemos,
                showReview = showReview,
                showTrash = showTrash,
                showInbox = showInbox,
                onShowHome = ::showHome,
                onShowLibrary = {
                    showAllMemos = true
                    showReview = false
                    showTrash = false
                    showInbox = false
                },
                onShowReview = {
                    showReview = true
                    showAllMemos = false
                    showTrash = false
                    showInbox = false
                    searchQuery = ""
                    showReviewAnswer = false
                },
                vaultReminderCount = vaultViewModel.lastReminderCount,
                onShowVault = { showVault = true },
            )
        },
        floatingActionButton = {
            FloatingActionButton(
                onClick = {
                    if (activeType == TYPE_IMAGE) {
                        imagePickerLauncher.launch(
                            PickVisualMediaRequest(
                                ActivityResultContracts.PickVisualMedia.ImageOnly,
                            ),
                        )
                        return@FloatingActionButton
                    }
                    if (activeType == TYPE_RESOURCE) {
                        activeType = TYPE_IDEA
                    }
                    if (activeType == TYPE_WORD) {
                        fillWordFromClipboard(overwrite = wordLemma.isBlank())
                    }
                    sharedResourcePending = false
                    showCreateDialog = true
                },
                containerColor = DeepTeal,
                contentColor = Color.White,
                shape = RoundedCornerShape(18.dp),
            ) {
                Icon(Icons.Outlined.Add, contentDescription = "新建", modifier = Modifier.size(26.dp))
            }
        },
    ) { innerPadding ->
        LazyColumn(
            state = listState,
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .imePadding(),
            contentPadding = PaddingValues(
                start = 16.dp,
                top = 4.dp,
                end = 16.dp,
                bottom = 104.dp,
            ),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            if (!showReview) item {
                MemoSearchField(
                    value = searchQuery,
                    onValueChange = { value ->
                        searchQuery = value
                        if (value.isNotBlank() && !showTrash && !showInbox) {
                            showAllMemos = true
                        }
                    },
                    onClear = { searchQuery = "" },
                )
            }
            if (showInbox) {
                if (inboxMemos.isEmpty()) {
                    item {
                        EmptyState(
                            icon = Icons.Outlined.Inbox,
                            title = if (normalizedSearchQuery.isNotEmpty()) "收件箱里没有匹配内容" else "收件箱是空的",
                            message = "快速记下的灵感会先放在这里，整理完成或归档后移出。",
                        )
                    }
                } else {
                    items(items = inboxMemos, key = Memo::clientId) { memo ->
                        InboxMemoRow(
                            memo = memo,
                            isSaving = uiState.isSaving,
                            onOpen = { openMemo(memo) },
                            onOrganize = {
                                viewModel.organizeIdea(memo, memo.title, memo.body) {}
                            },
                            onArchive = { viewModel.archiveIdea(memo) {} },
                        )
                    }
                }
            } else if (showTrash) {
                if (trashMemos.isEmpty()) {
                    item {
                        EmptyState(
                            icon = Icons.Outlined.DeleteOutline,
                            title = if (normalizedSearchQuery.isNotEmpty()) "回收站里没有匹配内容" else "回收站是空的",
                            message = "删除的内容会在这里保留 30 天，期间可以恢复。",
                        )
                    }
                } else {
                    items(items = trashMemos, key = Memo::clientId) { memo ->
                        TrashMemoRow(
                            memo = memo,
                            isSaving = uiState.isSaving,
                            onRestore = { viewModel.restoreMemo(memo) },
                            onPermanentDelete = { pendingPermanentDelete = memo },
                        )
                    }
                }
            } else if (showReview) {
                item {
                    ReviewSession(
                        current = currentReview,
                        wordCount = reviewCounts.wordCount,
                        resourceCount = reviewCounts.resourceCount,
                        ideaCount = reviewCounts.ideaCount,
                        remainingCount = filteredReviewItems.size,
                        dailyLimit = reviewLimit,
                        filter = reviewFilter,
                        onFilterChange = { reviewFilter = it },
                        onOpenSettings = { showReviewSettingsDialog = true },
                        showAnswer = showReviewAnswer,
                        isSaving = uiState.isSaving,
                        onShowAnswer = { showReviewAnswer = true },
                        onSkip = {
                            currentReview?.let { memo ->
                                viewModel.skipReview(memo) { showReviewAnswer = false }
                            }
                        },
                        onReviewWord = { feedback ->
                            currentReview?.let { memo ->
                                viewModel.reviewWord(memo, feedback) { showReviewAnswer = false }
                            }
                        },
                        onOpenResource = {
                            currentReview?.sourceUrl?.let(uriHandler::openUri)
                            currentReview?.let { memo ->
                                viewModel.recordResourceOpen(memo)
                                viewModel.markResourceOpened(memo) { showReviewAnswer = false }
                            }
                        },
                        onStarResource = {
                            currentReview?.let(viewModel::toggleStar)
                        },
                        onOrganizeIdea = {
                            currentReview?.let { memo ->
                                viewModel.organizeIdea(memo, memo.title, memo.body) {
                                    showReviewAnswer = false
                                }
                            }
                        },
                        onArchiveIdea = {
                            currentReview?.let { memo ->
                                viewModel.archiveIdea(memo) { showReviewAnswer = false }
                            }
                        },
                    )
                }
            } else if (!showAllMemos && normalizedSearchQuery.isEmpty()) {
                item {
                    ReviewCard(
                        wordCount = reviewCounts.wordCount,
                        resourceCount = reviewCounts.resourceCount,
                        ideaCount = reviewCounts.ideaCount,
                        onStart = {
                            showReview = true
                            showReviewAnswer = false
                        },
                    )
                }
                item {
                    QuickActions(
                        activeType = activeType,
                        isUploadingImage = uiState.isUploadingImage,
                        onSelectWord = {
                            fillWordFromClipboard(overwrite = wordLemma.isBlank())
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
                            viewModel.clearWordLookup()
                            activeType = TYPE_RESOURCE
                            showAllMemos = false
                            showCreateDialog = false
                        },
                        onSelectVoice = { showVoiceDialog = true },
                        onSelectImage = {
                            activeType = TYPE_IMAGE
                            showAllMemos = false
                            showCreateDialog = false
                            imagePickerLauncher.launch(
                                PickVisualMediaRequest(
                                    ActivityResultContracts.PickVisualMedia.ImageOnly,
                                ),
                            )
                        },
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
                    } else if (activeType == TYPE_IMAGE) {
                        ImageComposerCard(
                            isUploading = uiState.isUploadingImage,
                            onPickImage = {
                                imagePickerLauncher.launch(
                                    PickVisualMediaRequest(
                                        ActivityResultContracts.PickVisualMedia.ImageOnly,
                                    ),
                                )
                            },
                        )
                    } else {
                        WordComposer(
                            lemma = wordLemma,
                            phonetic = wordPhonetic,
                            meaning = wordMeaning,
                            example = wordExample,
                            isSaving = uiState.isSaving,
                            isLookingUp = uiState.isLookingUpWord,
                            lookup = uiState.wordLookup,
                            showLookupPreview = !showCreateDialog,
                            onLemmaChange = {
                                wordLemma = it
                                viewModel.clearWordLookup()
                            },
                            onPhoneticChange = { wordPhonetic = it },
                            onMeaningChange = { wordMeaning = it },
                            onExampleChange = { wordExample = it },
                            onFillClipboard = { fillWordFromClipboard(overwrite = true) },
                            onLookup = { viewModel.lookupWord(wordLemma) },
                            onClearLookup = viewModel::clearWordLookup,
                            onApplyLookup = ::applyWordLookup,
                            onSave = {
                                viewModel.createWord(
                                    wordLemma,
                                    wordPhonetic,
                                    wordMeaning,
                                    wordExample,
                                ) {
                                    viewModel.clearWordLookup()
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
                    if (normalizedSearchQuery.isEmpty() && viewModel.quickAccessLoaded) {
                        item {
                            QuickAccessSection(
                                entries = viewModel.quickAccess,
                                onOpen = { memo ->
                                    memo.sourceUrl?.let(uriHandler::openUri)
                                    viewModel.recordResourceOpen(memo)
                                },
                                onRemove = { memo ->
                                    viewModel.setQuickAccessHidden(memo, true) { succeeded ->
                                        coroutineScope.launch {
                                            if (!succeeded) {
                                                snackbarHostState.showSnackbar("暂时无法移除，请检查网络后重试")
                                                return@launch
                                            }
                                            val result = snackbarHostState.showSnackbar(
                                                message = "已从快速访问移除「${memo.title}」",
                                                actionLabel = "撤销",
                                            )
                                            if (result == SnackbarResult.ActionPerformed) {
                                                viewModel.setQuickAccessHidden(memo, false)
                                            }
                                        }
                                    }
                                },
                            )
                        }
                    }
                    item {
                        ResourceCategoryFilter(
                            selected = resourceCategoryFilter,
                            onSelect = { resourceCategoryFilter = it },
                        )
                    }
                }
            }
            if (showAllMemos && !showReview && !showTrash && !showInbox) {
                item {
                    LibraryTypeFilter(
                        selected = libraryTypeFilter,
                        onSelect = { value ->
                            libraryTypeFilter = value
                            if (value.isNotEmpty()) {
                                showAllMemos = true
                            }
                        },
                    )
                }
            }
            if (!showReview && !showTrash && !showInbox) item {
                SectionHeader(
                    title = when {
                        normalizedSearchQuery.isNotEmpty() -> "搜索结果"
                        showAllMemos -> "全部内容"
                        activeType == TYPE_RESOURCE -> "网页资料"
                        activeType == TYPE_WORD -> "单词"
                        activeType == TYPE_IMAGE -> "图片"
                        else -> "最近灵感"
                    },
                    trailing = when {
                            normalizedSearchQuery.isNotEmpty() -> "${visibleMemos.size} 条内容"
                            showAllMemos && libraryTypeFilter == TYPE_IMAGE ->
                                "${visibleMemos.size} 张图片"
                            showAllMemos -> "${visibleMemos.size} 条内容"
                            activeType == TYPE_IDEA -> "${visibleMemos.size} 条灵感"
                            activeType == TYPE_RESOURCE -> "${visibleMemos.size} 条资料"
                            activeType == TYPE_IMAGE -> "${visibleMemos.size} 张图片"
                        else -> "${visibleMemos.size} 个单词"
                    },
                )
            }
            if (!showReview && !showTrash && !showInbox) {
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
                    MemoRow(
                        memo = memo,
                        onClick = { openMemo(memo) },
                        imageThumbnail = viewModel.imageThumbnail(memo),
                        imageLoading = viewModel.isImageLoading(memo, thumbnail = true),
                        onRequestThumbnail = { viewModel.requestImageThumbnail(memo) },
                    )
                }
            }
            }
        }
    }

    selectedMemo?.let { memo ->
        if (memo.type == TYPE_RESOURCE) {
            ResourceDetailDialog(
                memo = memo,
                        onDismiss = { selectedMemo = null },
                onMoveToTrash = { pendingMoveToTrash = memo },
                isSaving = uiState.isSaving,
                onArchive = {
                    viewModel.archiveMemo(memo) { selectedMemo = null }
                },
                onOpen = {
                    memo.sourceUrl?.let(uriHandler::openUri)
                    viewModel.recordResourceOpen(memo)
                },
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
        } else if (memo.type == TYPE_IMAGE) {
            ImageDetailDialog(
                memo = memo,
                isSaving = uiState.isSaving,
                thumbnail = viewModel.imageThumbnail(memo),
                fullImage = viewModel.imageFullImage(memo),
                isLoadingThumbnail = viewModel.isImageLoading(memo, thumbnail = true),
                isLoadingFull = viewModel.isImageLoading(memo, thumbnail = false),
                onDismiss = {
                    viewModel.releaseFullImage(memo)
                    selectedMemo = null
                },
                onMoveToTrash = { pendingMoveToTrash = memo },
                onRequestThumbnail = { viewModel.requestImageThumbnail(memo) },
                onRequestFull = { viewModel.requestFullImage(memo) },
                onShare = {
                    // 项目没有文件分享的 FileProvider，这里只分享标题与备注文字。
                    val shareIntent = Intent(Intent.ACTION_SEND).apply {
                        type = "text/plain"
                        putExtra(
                            Intent.EXTRA_TEXT,
                            listOfNotNull(
                                memo.title,
                                memo.body.takeIf { it.isNotBlank() },
                            ).joinToString("\n"),
                        )
                    }
                    context.startActivity(Intent.createChooser(shareIntent, "分享图片收藏"))
                },
            )
        } else {
            EditMemoDialog(
                memo = memo,
                isSaving = uiState.isSaving,
                onDismiss = { selectedMemo = null },
                onMoveToTrash = { pendingMoveToTrash = memo },
                onSave = { title, body, phonetic, meaning, example ->
                    viewModel.updateMemo(
                        memo,
                        title,
                        body,
                        null,
                        phonetic,
                        meaning,
                        example,
                        onSuccess = { selectedMemo = null },
                        onConflict = { currentMemo ->
                            // 保留编辑器中的本地字段，等待用户决定采用哪一个版本。
                            selectedMemo = currentMemo
                            pendingConflictMemo = currentMemo
                            resetEditorToServerMemo = null
                        },
                    )
                },
                onReview = { feedback ->
                    viewModel.reviewWord(memo, feedback) {
                        selectedMemo = null
                    }
                },
                onPlayAudio = {
                    viewModel.playAudio(memo)
                },
                resetToServerMemo = resetEditorToServerMemo,
            )
        }
    }

    pendingConflictMemo?.let { serverMemo ->
        ConflictResolutionDialog(
            serverMemo = serverMemo,
            onKeepLocal = {
                pendingConflictMemo = null
                selectedMemo = serverMemo
                resetEditorToServerMemo = null
            },
            onUseServer = {
                viewModel.resolveConflictWithServer(serverMemo)
                pendingConflictMemo = null
                selectedMemo = serverMemo
                resetEditorToServerMemo = serverMemo
            },
            onLater = {
                pendingConflictMemo = null
                selectedMemo = null
                resetEditorToServerMemo = null
            },
        )
    }

    if (showLogoutDialog) {
        val unsyncedCount = viewModel.unsyncedCount()
        AlertDialog(
            onDismissRequest = {
                if (!isPreparingLogout) {
                    showLogoutDialog = false
                }
            },
            title = { Text("还有内容尚未同步") },
            text = {
                Text(
                    "当前有 $unsyncedCount 条内容等待同步或处理。先完成同步再退出，避免本机录音和编辑内容被清理。",
                )
            },
            confirmButton = {
                Button(
                    onClick = ::syncAndLogout,
                    enabled = !isPreparingLogout && !uiState.isRefreshing,
                    colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
                ) {
                    Text(if (isPreparingLogout) "同步中…" else "同步并退出")
                }
            },
            dismissButton = {
                OutlinedButton(
                    onClick = { showLogoutDialog = false },
                    enabled = !isPreparingLogout,
                ) {
                    Text("继续编辑")
                }
            },
            containerColor = SurfaceWhite,
            shape = RoundedCornerShape(14.dp),
        )
    }

    if (showReviewSettingsDialog) {
        ReviewSettingsDialog(
            settings = uiState.reviewSettings,
            isSaving = uiState.isSaving,
            onDismiss = { if (!uiState.isSaving) showReviewSettingsDialog = false },
            onSave = { dailyLimit, intervalsDays ->
                viewModel.saveReviewSettings(dailyLimit, intervalsDays)
                showReviewSettingsDialog = false
            },
        )
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
                viewModel.createSharedResource(
                    url = resourceUrl,
                    title = resourceTitle,
                    note = resourceNote,
                ) {
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
            isLookingUp = uiState.isLookingUpWord,
            lookup = uiState.wordLookup,
            onLemmaChange = {
                wordLemma = it
                viewModel.clearWordLookup()
            },
            onPhoneticChange = { wordPhonetic = it },
            onMeaningChange = { wordMeaning = it },
            onExampleChange = { wordExample = it },
            onFillClipboard = { fillWordFromClipboard(overwrite = true) },
            onLookup = { viewModel.lookupWord(wordLemma) },
            onClearLookup = viewModel::clearWordLookup,
            onApplyLookup = ::applyWordLookup,
            onDismiss = {
                viewModel.clearWordLookup()
                showCreateDialog = false
            },
            onSave = {
                viewModel.createWord(
                    wordLemma,
                    wordPhonetic,
                    wordMeaning,
                    wordExample,
                ) {
                    viewModel.clearWordLookup()
                    wordLemma = ""
                    wordPhonetic = ""
                    wordMeaning = ""
                    wordExample = ""
                    showCreateDialog = false
                }
            },
        )
    }
    uiState.duplicateWord?.let { existing ->
        AlertDialog(
            onDismissRequest = { viewModel.clearDuplicate() },
            title = { Text("已收藏相同词形") },
            text = {
                Text("“${existing.title}”已经在资料库中。可以把新例句合并进去，或仍然另外保存。")
            },
            confirmButton = {
                Button(
                    onClick = {
                        viewModel.mergeWord(
                            existing,
                            newLocalWord(wordLemma, wordPhonetic, wordMeaning, wordExample),
                        ) {
                            wordLemma = ""
                            wordPhonetic = ""
                            wordMeaning = ""
                            wordExample = ""
                            showCreateDialog = false
                        }
                    },
                ) { Text("合并例句") }
            },
            dismissButton = {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(
                        onClick = {
                            selectedMemo = existing
                            viewModel.clearDuplicate()
                            showCreateDialog = false
                        },
                    ) { Text("查看") }
                    TextButton(
                        onClick = {
                            viewModel.createWord(
                                wordLemma,
                                wordPhonetic,
                                wordMeaning,
                                wordExample,
                                allowDuplicate = true,
                            ) {
                                wordLemma = ""
                                wordPhonetic = ""
                                wordMeaning = ""
                                wordExample = ""
                                showCreateDialog = false
                            }
                        },
                    ) { Text("仍然保存") }
                }
            },
        )
    }
    uiState.duplicateResource?.let { existing ->
        AlertDialog(
            onDismissRequest = { viewModel.clearDuplicateResource() },
            title = { Text("已收藏相同网址") },
            text = {
                Text("“${existing.title}”已经在资料库中。可以查看已有资料，或仍然另外保存。")
            },
            confirmButton = {
                Button(
                    onClick = {
                        selectedMemo = existing
                        viewModel.clearDuplicateResource()
                        sharedResourcePending = false
                        showCreateDialog = false
                    },
                ) { Text("查看已有") }
            },
            dismissButton = {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(onClick = { viewModel.clearDuplicateResource() }) {
                        Text("稍后")
                    }
                    TextButton(
                        onClick = {
                            viewModel.createSharedResource(
                                url = resourceUrl,
                                title = resourceTitle,
                                note = resourceNote,
                                allowDuplicate = true,
                            ) {
                                resourceUrl = ""
                                resourceTitle = ""
                                resourceNote = ""
                                sharedResourcePending = false
                                showCreateDialog = false
                            }
                        },
                    ) { Text("仍然保存") }
                }
            },
        )
    }
    if (showVoiceDialog) {
        VoiceCaptureDialog(
            text = voiceText,
            isRecording = isVoiceRecording,
            isPaused = isVoicePaused,
            recording = voiceRecording,
            // 传读取函数而不是值：计时（250ms）和音量（100ms）只让对话框重组，
            // 不再带着整个首页一起重组。
            elapsedMs = { voiceElapsedMs },
            amplitudePercent = { voiceAmplitude },
            isTranscribing = isVoiceTranscribing,
            transcriptionMessage = voiceTranscriptionMessage,
            isSaving = uiState.isSaving,
            permissionDenied = voicePermissionDenied,
            onTextChange = { voiceText = it },
            onStart = {
                voicePermissionDenied = false
                voiceTranscriptionMessage = null
                val permission = ContextCompat.checkSelfPermission(
                    context,
                    Manifest.permission.RECORD_AUDIO,
                )
                if (permission == PackageManager.PERMISSION_GRANTED) {
                    if (voiceRecorder.start()) {
                        voiceRecording = null
                        voiceElapsedMs = 0
                        voiceAmplitude = 0
                        isVoicePaused = false
                        isVoiceRecording = true
                    }
                } else {
                    microphonePermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                }
            },
            onStop = {
                voiceRecording = voiceRecorder.stop()
                isVoiceRecording = false
                isVoicePaused = false
                voiceAmplitude = 0
                voiceElapsedMs = voiceRecording?.durationMs ?: 0
                if (voiceRecording == null) {
                    voiceTranscriptionMessage = "录音没有保存成功，请重试。"
                }
            },
            onReset = {
                resetVoiceRecording()
            },
            onTogglePause = {
                if (isVoicePaused) {
                    if (voiceRecorder.resume()) {
                        isVoicePaused = false
                    } else {
                        voiceTranscriptionMessage = "当前设备暂不支持继续录音，请结束当前录音。"
                    }
                } else if (voiceRecorder.pause()) {
                    isVoicePaused = true
                    voiceAmplitude = 0
                } else {
                    voiceTranscriptionMessage = "当前设备暂不支持暂停录音，请直接结束录音。"
                }
            },
            onRequestDismiss = ::requestVoiceDismiss,
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

    if (showVoiceDiscardConfirm) {
        AlertDialog(
            onDismissRequest = { showVoiceDiscardConfirm = false },
            title = { Text("放弃这段记录？") },
            text = { Text("录音和当前文字不会保存，确定要放弃吗？") },
            confirmButton = {
                Button(
                    onClick = ::discardVoiceCapture,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.error,
                    ),
                ) { Text("放弃记录") }
            },
            dismissButton = {
                TextButton(onClick = { showVoiceDiscardConfirm = false }) {
                    Text("继续编辑")
                }
            },
        )
    }

    pendingMoveToTrash?.let { memo ->
        AlertDialog(
            onDismissRequest = { pendingMoveToTrash = null },
            title = { Text("移入回收站") },
            text = {
                Text("「${memo.title}」将移入回收站，30 天后永久删除。继续吗？")
            },
            confirmButton = {
                Button(
                    onClick = {
                        pendingMoveToTrash = null
                        selectedMemo = null
                        viewModel.releaseFullImage(memo)
                        viewModel.moveToTrash(memo)
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFB84A4A)),
                ) {
                    Text("移入回收站")
                }
            },
            dismissButton = {
                OutlinedButton(onClick = { pendingMoveToTrash = null }) {
                    Text("取消")
                }
            },
            containerColor = SurfaceWhite,
            shape = RoundedCornerShape(14.dp),
        )
    }

    pendingPermanentDelete?.let { memo ->
        AlertDialog(
            onDismissRequest = { pendingPermanentDelete = null },
            title = { Text("永久删除") },
            text = {
                Text("将永久删除「${memo.title}」，此操作不可恢复。确定继续吗？")
            },
            confirmButton = {
                Button(
                    onClick = {
                        pendingPermanentDelete = null
                        viewModel.permanentlyDeleteMemo(memo)
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFB84A4A)),
                ) {
                    Text("永久删除")
                }
            },
            dismissButton = {
                OutlinedButton(onClick = { pendingPermanentDelete = null }) {
                    Text("取消")
                }
            },
            containerColor = SurfaceWhite,
            shape = RoundedCornerShape(14.dp),
        )
    }
}

/** 顶栏右侧：收件箱（带待整理数）、同步，以及收纳回收站、导出和退出的菜单。 */
@Composable
private fun TopBarActions(
    inboxCount: Int,
    showInboxAction: Boolean,
    showTrashAction: Boolean,
    isRefreshing: Boolean,
    isSaving: Boolean,
    isExporting: Boolean,
    onShowInbox: () -> Unit,
    onShowTrash: () -> Unit,
    onRefresh: () -> Unit,
    onExport: () -> Unit,
    onLogout: () -> Unit,
) {
    if (showInboxAction) {
        IconButton(onClick = onShowInbox) {
            BadgedBox(
                badge = {
                    if (inboxCount > 0) {
                        Badge(containerColor = WarmAmberText) { Text(if (inboxCount > 99) "99+" else "$inboxCount") }
                    }
                },
            ) {
                Icon(Icons.Outlined.Inbox, contentDescription = "收件箱，$inboxCount 条待整理")
            }
        }
    }
    IconButton(onClick = onRefresh, enabled = !isRefreshing) {
        if (isRefreshing) {
            CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp, color = DeepTeal)
        } else {
            Icon(Icons.Outlined.Sync, contentDescription = "同步")
        }
    }
    var menuOpen by remember { mutableStateOf(false) }
    Box {
        IconButton(onClick = { menuOpen = true }) {
            if (isExporting) {
                CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp, color = DeepTeal)
            } else {
                Icon(Icons.Outlined.MoreVert, contentDescription = "更多操作")
            }
        }
        DropdownMenu(
            expanded = menuOpen,
            onDismissRequest = { menuOpen = false },
            containerColor = SurfaceWhite,
            shape = RoundedCornerShape(14.dp),
        ) {
            if (showTrashAction) {
                DropdownMenuItem(
                    text = { Text("回收站") },
                    leadingIcon = { Icon(Icons.Outlined.DeleteOutline, contentDescription = null) },
                    onClick = {
                        menuOpen = false
                        onShowTrash()
                    },
                )
            }
            DropdownMenuItem(
                text = { Text(if (isExporting) "导出中…" else "导出数据") },
                leadingIcon = { Icon(Icons.Outlined.FileDownload, contentDescription = null) },
                enabled = !isRefreshing && !isSaving && !isExporting,
                onClick = {
                    menuOpen = false
                    onExport()
                },
            )
            HorizontalDivider(color = Border)
            DropdownMenuItem(
                text = { Text("退出登录") },
                leadingIcon = { Icon(Icons.AutoMirrored.Outlined.Logout, contentDescription = null) },
                onClick = {
                    menuOpen = false
                    onLogout()
                },
            )
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
        placeholder = { Text("搜索标题、正文、网址、释义或标签") },
        leadingIcon = { Icon(Icons.Outlined.Search, contentDescription = null, tint = TextMuted) },
        trailingIcon = if (value.isNotEmpty()) {
            {
                IconButton(onClick = onClear) {
                    Icon(Icons.Outlined.Close, contentDescription = "清除搜索")
                }
            }
        } else {
            null
        },
        shape = RoundedCornerShape(14.dp),
        colors = OutlinedTextFieldDefaults.colors(
            unfocusedContainerColor = SurfaceWhite,
            focusedContainerColor = SurfaceWhite,
            unfocusedBorderColor = Border,
            focusedBorderColor = DeepTeal,
        ),
    )
}

/** 空列表时的居中提示。 */
@Composable
internal fun EmptyState(
    icon: ImageVector,
    title: String,
    message: String,
    accent: Color = DeepTeal,
    soft: Color = TealSoft,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 28.dp, horizontal = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Box(
            modifier = Modifier
                .size(56.dp)
                .background(soft, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, contentDescription = null, tint = accent, modifier = Modifier.size(28.dp))
        }
        Spacer(Modifier.height(4.dp))
        Text(title, style = MaterialTheme.typography.titleMedium)
        Text(
            message,
            color = TextMuted,
            style = MaterialTheme.typography.bodySmall,
            textAlign = TextAlign.Center,
        )
    }
}

@Composable
private fun MemoBottomNavigation(
    showAllMemos: Boolean,
    showReview: Boolean,
    showTrash: Boolean,
    showInbox: Boolean,
    onShowHome: () -> Unit,
    onShowLibrary: () -> Unit,
    onShowReview: () -> Unit,
    vaultReminderCount: Int,
    onShowVault: () -> Unit,
) {
    val homeSelected = !showAllMemos && !showReview && !showTrash && !showInbox
    val librarySelected = showAllMemos && !showReview && !showTrash && !showInbox
    NavigationBar(containerColor = SurfaceWhite, tonalElevation = 0.dp) {
        NavigationBarItem(
            selected = homeSelected,
            onClick = onShowHome,
            icon = { Icon(if (homeSelected) Icons.Filled.Home else Icons.Outlined.Home, contentDescription = null) },
            label = { Text("首页") },
            colors = memoNavigationColors(),
        )
        NavigationBarItem(
            selected = librarySelected,
            onClick = onShowLibrary,
            icon = {
                Icon(
                    if (librarySelected) Icons.Filled.CollectionsBookmark else Icons.Outlined.CollectionsBookmark,
                    contentDescription = null,
                )
            },
            label = { Text("资料库") },
            colors = memoNavigationColors(),
        )
        NavigationBarItem(
            selected = showReview,
            onClick = onShowReview,
            icon = { Icon(Icons.Outlined.Autorenew, contentDescription = null) },
            label = { Text("回顾") },
            colors = memoNavigationColors(),
        )
        NavigationBarItem(
            selected = false,
            onClick = onShowVault,
            icon = {
                // 角标是上次解锁时需要处理的提醒数，锁定后仍然显示。
                BadgedBox(badge = { if (vaultReminderCount > 0) Badge { Text("$vaultReminderCount") } }) {
                    Icon(Icons.Outlined.Lock, contentDescription = null)
                }
            },
            label = { Text("密码库") },
            colors = memoNavigationColors(),
        )
    }
}

@Composable
private fun memoNavigationColors() = NavigationBarItemDefaults.colors(
    selectedIconColor = DeepTealHover,
    selectedTextColor = DeepTealHover,
    unselectedIconColor = TextMuted,
    unselectedTextColor = TextMuted,
    indicatorColor = TealSoft,
    disabledIconColor = TextMuted.copy(alpha = 0.42f),
    disabledTextColor = TextMuted.copy(alpha = 0.42f),
)

internal fun formatTime(value: String): String {
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
