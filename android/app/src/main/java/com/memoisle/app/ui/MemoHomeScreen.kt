package com.memoisle.app.ui

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FloatingActionButton
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.memoisle.app.MemoIsleApplication
import com.memoisle.app.MemoViewModel
import com.memoisle.app.VaultViewModel
import com.memoisle.app.audio.VoiceRecorder
import com.memoisle.app.audio.VoiceRecording
import com.memoisle.app.audio.WordPronouncer
import com.memoisle.app.audio.SherpaOnnxSpeechToText
import com.memoisle.app.data.Memo
import com.memoisle.app.data.SyncState
import com.memoisle.app.data.TYPE_IDEA
import com.memoisle.app.data.TYPE_IMAGE
import com.memoisle.app.data.TYPE_RESOURCE
import com.memoisle.app.data.TYPE_WORD
import com.memoisle.app.data.formatFileSize
import com.memoisle.app.data.hasUploadedImage
import com.memoisle.app.network.QuickAccessEntry
import com.memoisle.app.data.imageDimensionsLabel
import com.memoisle.app.data.imageOcrSourceLabel
import com.memoisle.app.data.imageOcrStatusLabel
import com.memoisle.app.data.isDueWord
import com.memoisle.app.data.isInboxIdea
import com.memoisle.app.data.isUnreadResource
import com.memoisle.app.data.isInTrash
import com.memoisle.app.data.isVisibleInLibrary
import com.memoisle.app.data.linkHealthLabel
import com.memoisle.app.data.trashDaysRemaining
import com.memoisle.app.data.matchesQuery
import com.memoisle.app.data.newLocalWord
import com.memoisle.app.data.normalizeResourceUrl
import com.memoisle.app.data.parseClipboardWord
import com.memoisle.app.data.assignedCategoryCodes
import com.memoisle.app.data.resourceCategoryLabel
import com.memoisle.app.data.resourceHost
import com.memoisle.app.data.todayReviewCounts
import com.memoisle.app.data.todayReviewItems
import com.memoisle.app.network.ReviewSettings
import com.memoisle.app.network.WordLookupResponse
import com.memoisle.app.network.WordLookupSense
import java.nio.file.Paths
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale
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
    val visibleMemos = memos.filter { memo ->
        val typeMatches = showAllMemos || normalizedSearchQuery.isNotEmpty() ||
            memo.type == activeType
        val libraryTypeMatches = !showAllMemos || libraryTypeFilter.isEmpty() ||
            memo.type == libraryTypeFilter
        val categoryMatches = showAllMemos || normalizedSearchQuery.isNotEmpty() ||
            activeType != TYPE_RESOURCE || resourceCategoryFilter.isEmpty() ||
            memo.assignedCategoryCodes().contains(resourceCategoryFilter)
        memo.isVisibleInLibrary() && typeMatches && libraryTypeMatches && categoryMatches &&
            memo.matchesQuery(normalizedSearchQuery)
    }
    val libraryMemos = memos.filter { it.isVisibleInLibrary() }
    val trashMemos = memos.filter { memo ->
        memo.isInTrash() && memo.matchesQuery(normalizedSearchQuery)
    }
    val inboxMemos = memos.filter { memo ->
        memo.status == "inbox" && memo.matchesQuery(normalizedSearchQuery)
    }
    val reviewCounts = libraryMemos.todayReviewCounts()
    val reviewLimit = uiState.reviewSettings.dailyLimit
    val reviewItems = libraryMemos.todayReviewItems(limit = reviewLimit)
    val filteredReviewItems = when (reviewFilter) {
        TYPE_WORD -> libraryMemos.filter { it.isDueWord() }.take(reviewLimit)
        TYPE_RESOURCE -> libraryMemos.filter { it.isUnreadResource() }.take(reviewLimit)
        TYPE_IDEA -> libraryMemos.filter { it.isInboxIdea() }.take(reviewLimit)
        else -> reviewItems
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

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        containerColor = WarmMist,
        snackbarHost = { SnackbarHost(snackbarHostState) },
        bottomBar = {
            MemoBottomNavigation(
                showAllMemos = showAllMemos,
                showReview = showReview,
                showTrash = showTrash,
                showInbox = showInbox,
                onShowHome = {
                    showAllMemos = false
                    showReview = false
                    showTrash = false
                    showInbox = false
                    searchQuery = ""
                },
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
                    isSaving = uiState.isSaving,
                    isExporting = uiState.isExporting,
                    onRefresh = viewModel::refresh,
                    onExport = { exportLauncher.launch("memoisle-export.json") },
                    onLogout = ::requestLogout,
                    showTrash = showTrash,
                    showInbox = showInbox,
                    onShowTrash = {
                        showTrash = true
                        showInbox = false
                        showReview = false
                        showAllMemos = false
                        selectedMemo = null
                    },
                    onShowInbox = {
                        showInbox = true
                        showTrash = false
                        showReview = false
                        showAllMemos = false
                        selectedMemo = null
                    },
                )
            }
            item {
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
                item {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = "收件箱",
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Spacer(Modifier.weight(1f))
                        Text(
                            text = "${inboxMemos.size} 条待整理",
                            color = TextMuted,
                            style = MaterialTheme.typography.labelMedium,
                        )
                    }
                }
                if (inboxMemos.isEmpty()) {
                    item {
                        Text(
                            text = if (normalizedSearchQuery.isNotEmpty()) {
                                "收件箱里没有匹配内容"
                            } else {
                                "收件箱是空的。快速记下的灵感会先到这里。"
                            },
                            color = TextMuted,
                            style = MaterialTheme.typography.bodyMedium,
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
                item {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            text = "回收站",
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Spacer(Modifier.weight(1f))
                        Text(
                            text = "${trashMemos.size} 条 · 保留 30 天",
                            color = TextMuted,
                            style = MaterialTheme.typography.labelMedium,
                        )
                    }
                }
                if (trashMemos.isEmpty()) {
                    item {
                        Text(
                            text = if (normalizedSearchQuery.isNotEmpty()) {
                                "回收站里没有匹配内容"
                            } else {
                                "回收站是空的。删除的内容会在这里保留 30 天。"
                            },
                            color = TextMuted,
                            style = MaterialTheme.typography.bodyMedium,
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
            if (!showReview) item {
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
                            normalizedSearchQuery.isNotEmpty() -> "${visibleMemos.size} 条内容"
                            showAllMemos && libraryTypeFilter == TYPE_IMAGE ->
                                "${visibleMemos.size} 张图片"
                            showAllMemos -> "${visibleMemos.size} 条内容"
                            activeType == TYPE_IDEA -> "${visibleMemos.size} 条灵感"
                            activeType == TYPE_RESOURCE -> "${visibleMemos.size} 条资料"
                            activeType == TYPE_IMAGE -> "${visibleMemos.size} 张图片"
                            else -> "${visibleMemos.size} 个单词"
                        },
                        color = TextMuted,
                        style = MaterialTheme.typography.labelMedium,
                    )
                }
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
            elapsedMs = voiceElapsedMs,
            amplitudePercent = voiceAmplitude,
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

@Composable
private fun MemoHeader(
    isRefreshing: Boolean,
    isSaving: Boolean,
    isExporting: Boolean,
    onRefresh: () -> Unit,
    onExport: () -> Unit,
    onLogout: () -> Unit,
    showTrash: Boolean,
    showInbox: Boolean,
    onShowTrash: () -> Unit,
    onShowInbox: () -> Unit,
) {
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
        TextButton(onClick = onShowInbox) {
            Text(if (showInbox) "收件箱中" else "收件箱")
        }
        TextButton(onClick = onShowTrash) {
            Text(if (showTrash) "回收站中" else "回收站")
        }
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
        // 导出和退出不常用，收进菜单；五个按钮并排时窄屏会把「退出」挤出屏幕。
        var menuOpen by remember { mutableStateOf(false) }
        Box {
            TextButton(
                onClick = { menuOpen = true },
                modifier = Modifier.semantics { contentDescription = "更多操作" },
            ) {
                if (isExporting) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(18.dp),
                        strokeWidth = 2.dp,
                    )
                } else {
                    Text("⋯", fontWeight = FontWeight.Bold)
                }
            }
            DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                DropdownMenuItem(
                    text = { Text(if (isExporting) "导出中" else "导出数据") },
                    enabled = !isRefreshing && !isSaving && !isExporting,
                    onClick = {
                        menuOpen = false
                        onExport()
                    },
                )
                DropdownMenuItem(
                    text = { Text("退出登录") },
                    onClick = {
                        menuOpen = false
                        onLogout()
                    },
                )
            }
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
private fun ReviewCard(
    wordCount: Int,
    resourceCount: Int,
    ideaCount: Int,
    onStart: () -> Unit,
) {
    val totalCount = wordCount + resourceCount + ideaCount
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
                        if (totalCount == 0) {
                            "今天没有需要回顾的内容"
                        } else {
                            "$wordCount 个单词、$resourceCount 篇待读、$ideaCount 条待整理"
                        },
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
                onClick = onStart,
                modifier = Modifier.fillMaxWidth(),
                enabled = totalCount > 0,
                colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
            ) {
                Text(if (totalCount == 0) "今天已完成" else "开始回顾")
            }
        }
    }
}

@Composable
private fun ReviewSettingsDialog(
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
private fun ReviewSession(
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
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("今日回顾", fontWeight = FontWeight.SemiBold, fontSize = 22.sp)
            Spacer(Modifier.weight(1f))
            TextButton(onClick = onOpenSettings) {
                Text("复习计划")
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(
                "all" to "混合",
                TYPE_WORD to "单词",
                TYPE_RESOURCE to "待读",
                TYPE_IDEA to "待整理",
            ).forEach { (value, label) ->
                val selected = filter == value
                OutlinedButton(
                    onClick = { onFilterChange(value) },
                    colors = ButtonDefaults.outlinedButtonColors(
                        containerColor = if (selected) TealSoft else SurfaceWhite,
                    ),
                ) {
                    Text(label, color = if (selected) DeepTeal else TextMuted)
                }
            }
        }
        Text(
            "$remainingCount / $dailyLimit 条今日计划 · " +
                "$wordCount 个单词 · $resourceCount 篇待读 · $ideaCount 条待整理",
            color = TextMuted,
            style = MaterialTheme.typography.bodySmall,
        )
        if (current == null) {
            Card(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(14.dp),
                colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
                border = CardDefaults.outlinedCardBorder(),
            ) {
                Column(
                    modifier = Modifier.padding(24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("◷", color = DeepTeal, fontSize = 28.sp)
                    Text("今天的回顾已经完成", fontWeight = FontWeight.SemiBold)
                    Text("到期单词、待读资料和待整理灵感会显示在这里。", color = TextMuted)
                }
            }
        } else {
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
                Text(
                    when (current.type) {
                        TYPE_WORD -> "单词复习 · 还剩 $remainingCount 条"
                        TYPE_RESOURCE -> "待阅读 · 还剩 $remainingCount 条"
                        else -> "待整理灵感 · 还剩 $remainingCount 条"
                    },
                    color = TextMuted,
                    style = MaterialTheme.typography.labelMedium,
                )
                Text(current.title, fontWeight = FontWeight.SemiBold, fontSize = 22.sp)
                when (current.type) {
                    TYPE_WORD -> {
                        ClickablePhonetic(
                            lemma = current.title,
                            phonetic = current.wordPhonetic,
                        )
                        current.wordExample?.takeIf { it.isNotBlank() }?.let {
                            Text("“$it”", color = TextMuted)
                        }
                        Text(
                            "上次 ${current.lastReviewAt?.let(::formatTime) ?: "尚未复习"} · 下次 ${current.nextReviewAt?.let(::formatTime) ?: "待安排"}",
                            color = TextMuted,
                            style = MaterialTheme.typography.labelSmall,
                        )
                        if (!showAnswer) {
                            OutlinedButton(
                                onClick = onShowAnswer,
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Text("显示答案")
                            }
                        } else {
                            Text(current.wordMeaning ?: current.body)
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                OutlinedButton(
                                    onClick = { onReviewWord("forgot") },
                                    modifier = Modifier.weight(1f),
                                    enabled = !isSaving,
                                ) { Text("忘记") }
                                OutlinedButton(
                                    onClick = { onReviewWord("fuzzy") },
                                    modifier = Modifier.weight(1f),
                                    enabled = !isSaving,
                                ) { Text("模糊") }
                                Button(
                                    onClick = { onReviewWord("remembered") },
                                    modifier = Modifier.weight(1f),
                                    enabled = !isSaving,
                                    colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
                                ) { Text("记得") }
                            }
                        }
                    }
                    TYPE_RESOURCE -> {
                        Text(
                            listOfNotNull(
                                current.sourceUrl?.let(::resourceHost),
                                resourceCategoryLabel(
                                    current.resourceCategory,
                                    current.resourceCategoryLabel,
                                ),
                            ).joinToString(" · "),
                            color = TextMuted,
                        )
                        current.resourceDescription?.takeIf { it.isNotBlank() }?.let {
                            Text(it)
                        }
                        Button(
                            onClick = onOpenResource,
                            modifier = Modifier.fillMaxWidth(),
                            enabled = !isSaving && !current.sourceUrl.isNullOrBlank(),
                            colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
                        ) { Text("打开原网页") }
                        OutlinedButton(
                            onClick = onStarResource,
                            modifier = Modifier.fillMaxWidth(),
                            enabled = !isSaving,
                        ) { Text(if (current.starred) "取消星标" else "星标") }
                    }
                    else -> {
                        Text(current.body)
                        Button(
                            onClick = onOrganizeIdea,
                            modifier = Modifier.fillMaxWidth(),
                            enabled = !isSaving,
                            colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
                        ) { Text("整理完成") }
                        OutlinedButton(
                            onClick = onArchiveIdea,
                            modifier = Modifier.fillMaxWidth(),
                            enabled = !isSaving,
                        ) { Text("归档") }
                    }
                }
                TextButton(onClick = onSkip, enabled = !isSaving) {
                    Text("跳过")
                }
            }
        }
        }
    }
}

@Composable
private fun QuickActions(
    activeType: String,
    isUploadingImage: Boolean,
    onSelectWord: () -> Unit,
    onSelectIdea: () -> Unit,
    onBrowseResource: () -> Unit,
    onSelectVoice: () -> Unit,
    onSelectImage: () -> Unit,
) {
    val actions = listOf(
        "Aa" to "记单词",
        "↗" to "看资料",
        "✦" to "写灵感",
        "●" to "语音记录",
        "▣" to "图片",
    )
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        actions.forEach { (icon, label) ->
            val uploading = label == "图片" && isUploadingImage
            val selected = (label == "写灵感" && activeType == TYPE_IDEA) ||
                (label == "看资料" && activeType == TYPE_RESOURCE) ||
                (label == "记单词" && activeType == TYPE_WORD) ||
                (label == "图片" && activeType == TYPE_IMAGE)
            Column(
                modifier = Modifier.clickable {
                    when (label) {
                        "记单词" -> onSelectWord()
                        "写灵感" -> onSelectIdea()
                        "看资料" -> onBrowseResource()
                        "图片" -> onSelectImage()
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
                    if (uploading) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            strokeWidth = 2.dp,
                        )
                    } else {
                        Text(icon, color = if (selected) DeepTeal else TextMuted)
                    }
                }
                Spacer(Modifier.height(6.dp))
                Text(
                    text = if (uploading) "上传中" else label,
                    color = TextMuted,
                    fontSize = 11.sp,
                )
            }
        }
    }
}

@Composable
private fun LibraryTypeFilter(
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
            if (selected == value) {
                Button(
                    onClick = { onSelect(value) },
                    contentPadding = PaddingValues(horizontal = 14.dp, vertical = 2.dp),
                ) { Text(label, fontSize = 12.sp) }
            } else {
                OutlinedButton(
                    onClick = { onSelect(value) },
                    contentPadding = PaddingValues(horizontal = 14.dp, vertical = 2.dp),
                ) { Text(label, fontSize = 12.sp) }
            }
        }
    }
}

@Composable
private fun ImageComposerCard(
    isUploading: Boolean,
    onPickImage: () -> Unit,
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
            Text("收藏图片", fontWeight = FontWeight.SemiBold)
            Text(
                "从相册选择一张图片，会自动创建图片收藏并上传原图；" +
                    "标题取自文件名，稍后可在 Web 端补充备注。",
                color = TextMuted,
                style = MaterialTheme.typography.bodySmall,
            )
            Button(
                onClick = onPickImage,
                modifier = Modifier.fillMaxWidth(),
                enabled = !isUploading,
                colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
            ) {
                Text(if (isUploading) "上传中…" else "从相册选择图片")
            }
        }
    }
}

@Composable
private fun WordLookupControls(
    lemma: String,
    isSaving: Boolean,
    isLookingUp: Boolean,
    lookup: WordLookupResponse?,
    onLookup: () -> Unit,
    onClearLookup: () -> Unit,
    onApplyLookup: (List<WordLookupSense>) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedButton(
                onClick = onLookup,
                enabled = lemma.isNotBlank() && !isSaving && !isLookingUp,
            ) {
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
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceSubtle),
        border = CardDefaults.outlinedCardBorder(),
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Column {
                    Text("词典预览", fontWeight = FontWeight.SemiBold)
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
                                    color = DeepTeal,
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
                    colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
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
private fun WordComposer(
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
            Text(
                if (isLookingUp) {
                    "正在填入中文释义、音标和例句…"
                } else {
                    "输入单词后自动填入中文释义、音标和例句"
                },
                color = TextMuted,
                style = MaterialTheme.typography.bodySmall,
            )
            TextButton(onClick = onFillClipboard, enabled = !isSaving) {
                Text("从剪贴板填入")
            }
            OutlinedTextField(
                value = lemma,
                onValueChange = onLemmaChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("单词或短语") },
                placeholder = { Text("输入后自动填入中文释义") },
                singleLine = true,
                shape = RoundedCornerShape(10.dp),
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
                shape = RoundedCornerShape(10.dp),
            )
            OutlinedTextField(
                value = example,
                onValueChange = onExampleChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("例句（自动填入）") },
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
private fun MemoRow(
    memo: Memo,
    onClick: () -> Unit,
    imageThumbnail: ByteArray? = null,
    imageLoading: Boolean = false,
    onRequestThumbnail: () -> Unit = {},
) {
    val isResource = memo.type == TYPE_RESOURCE
    val isWord = memo.type == TYPE_WORD
    val isImage = memo.type == TYPE_IMAGE
    val isVoice = memo.audioMimeType != null
    if (isImage) {
        LaunchedEffect(memo.clientId, memo.version, imageThumbnail == null) {
            if (imageThumbnail == null) {
                onRequestThumbnail()
            }
        }
    }
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
            if (isImage) {
                MemoImage(
                    bytes = imageThumbnail,
                    loading = imageLoading && imageThumbnail == null,
                    modifier = Modifier.size(56.dp),
                    maxDimension = 320,
                    contentScale = ContentScale.Crop,
                    contentDescription = memo.title,
                )
            } else {
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
                        isImage -> imageRowSubtitle(memo)
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
                            "熟悉度 ${memo.familiarity}/5 · 下次 ${memo.nextReviewAt?.let(::formatTime) ?: "待安排"}",
                            color = TextMuted,
                            fontSize = 11.sp,
                        )
                        Spacer(Modifier.width(8.dp))
                    }
                    if (isResource) {
                        Text(
                            resourceCategoryLabel(
                                memo.resourceCategory,
                                memo.resourceCategoryLabel,
                            ),
                            color = DeepTeal,
                            fontSize = 11.sp,
                        )
                        Spacer(Modifier.width(8.dp))
                    }
                    if (isImage) {
                        Text(
                            imageMimeLabel(memo.imageMimeType) ?: "图片收藏",
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

private fun imageRowSubtitle(memo: Memo): String {
    val metadata = listOfNotNull(
        imageDimensionsLabel(memo.imageWidth, memo.imageHeight),
        formatFileSize(memo.imageSizeBytes),
    ).joinToString(" · ")
    return when {
        metadata.isNotBlank() -> metadata
        memo.body.isNotBlank() -> memo.body
        memo.hasUploadedImage() -> "图片收藏"
        else -> "图片待上传"
    }
}

private fun imageMimeLabel(mimeType: String?): String? = when (mimeType) {
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
private fun MemoImage(
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
            else -> Text("▣", color = TextMuted)
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
private fun InboxMemoRow(
    memo: Memo,
    isSaving: Boolean,
    onOpen: () -> Unit,
    onOrganize: () -> Unit,
    onArchive: () -> Unit,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onOpen),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = CardDefaults.outlinedCardBorder(),
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(memo.title, fontWeight = FontWeight.SemiBold, maxLines = 2)
            if (memo.body.isNotBlank() && memo.body != memo.title) {
                Text(
                    text = memo.body,
                    color = TextMuted,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 3,
                )
            }
            Text(
                text = if (memo.audioMimeType != null) "语音灵感 · 待整理" else "灵感 · 待整理",
                color = TextMuted,
                style = MaterialTheme.typography.labelSmall,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = onOrganize,
                    enabled = !isSaving,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
                ) {
                    Text("整理完成")
                }
                OutlinedButton(
                    onClick = onArchive,
                    enabled = !isSaving,
                    modifier = Modifier.weight(1f),
                ) {
                    Text("归档")
                }
            }
        }
    }
}

@Composable
private fun TrashMemoRow(
    memo: Memo,
    isSaving: Boolean,
    onRestore: () -> Unit,
    onPermanentDelete: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = CardDefaults.outlinedCardBorder(),
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(memo.title, fontWeight = FontWeight.SemiBold, maxLines = 2)
            Text(
                text = when (memo.type) {
                    TYPE_WORD -> "单词 · 还剩 ${memo.trashDaysRemaining()} 天"
                    TYPE_RESOURCE -> "网页资料 · 还剩 ${memo.trashDaysRemaining()} 天"
                    TYPE_IMAGE -> "图片收藏 · 还剩 ${memo.trashDaysRemaining()} 天"
                    else -> "灵感 · 还剩 ${memo.trashDaysRemaining()} 天"
                },
                color = TextMuted,
                style = MaterialTheme.typography.bodySmall,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = onRestore,
                    enabled = !isSaving && memo.id != null,
                    modifier = Modifier.weight(1f),
                ) {
                    Text("恢复")
                }
                Button(
                    onClick = onPermanentDelete,
                    enabled = !isSaving && memo.id != null,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFB84A4A)),
                ) {
                    Text("永久删除")
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
        SyncState.CONFLICT -> "待处理冲突" to WarmAmberText
    }
    Text(
        text = label,
        color = color,
        fontSize = 11.sp,
        fontWeight = FontWeight.Medium,
    )
}

@Composable
private fun ConflictResolutionDialog(
    serverMemo: Memo,
    onKeepLocal: () -> Unit,
    onUseServer: () -> Unit,
    onLater: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onLater,
        title = { Text("发现编辑冲突", fontWeight = FontWeight.SemiBold) },
        text = {
            Text(
                "其他设备已更新「${serverMemo.title}」。你的本地修改已经保留，请选择要使用的版本。",
            )
        },
        confirmButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = onUseServer) {
                    Text("采用服务端版本")
                }
                Button(
                    onClick = onKeepLocal,
                    colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
                ) {
                    Text("保留我的修改")
                }
            }
        },
        dismissButton = {
            TextButton(onClick = onLater) {
                Text("稍后处理")
            }
        },
        containerColor = SurfaceWhite,
        shape = RoundedCornerShape(14.dp),
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
    val isImage = activeType == TYPE_IMAGE
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
                isImage -> "▣"
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
                isImage -> "还没有收藏图片"
                else -> "第一条灵感正在等你"
            },
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            when {
                hasQuery -> "换个关键词，或清除搜索后浏览全部收藏。"
                isLibrary -> "从灵感、英语单词、图片或网页资料开始收藏第一条内容。"
                isResource -> "可在 Web 端收藏，或从手机浏览器分享链接到 MemoIsle。"
                isWord -> "保存词形、释义和例句，稍后按计划复习。"
                isImage -> "点击「从相册选择图片」，原图与缩略图会同步到 Web。"
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
    isSaving: Boolean,
    onDismiss: () -> Unit,
    onMoveToTrash: () -> Unit,
    onArchive: () -> Unit,
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
                        resourceCategoryLabel(
                            memo.resourceCategory,
                            memo.resourceCategoryLabel,
                        ),
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
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        "巡检：${linkHealthLabel(memo.linkHealthStatus)}",
                        modifier = Modifier
                            .background(SurfaceSubtle, RoundedCornerShape(20.dp))
                            .padding(horizontal = 10.dp, vertical = 5.dp),
                        color = TextMuted,
                        fontSize = 11.sp,
                    )
                    memo.linkLastCheckedAt?.let { checkedAt ->
                        Text(
                            "最近检查 ${formatTime(checkedAt)}",
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
                enabled = memo.sourceUrl != null && !isSaving,
                colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
            ) { Text("打开原网页") }
        },
        dismissButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                TextButton(onClick = onCopy, enabled = memo.sourceUrl != null && !isSaving) {
                    Text("复制")
                }
                TextButton(onClick = onShare, enabled = memo.sourceUrl != null && !isSaving) {
                    Text("分享")
                }
                TextButton(onClick = onArchive, enabled = !isSaving) {
                    Text("归档")
                }
                TextButton(onClick = onMoveToTrash, enabled = !isSaving) {
                    Text("回收站", color = Color(0xFFB84A4A))
                }
                OutlinedButton(onClick = onDismiss, enabled = !isSaving) { Text("关闭") }
            }
        },
        containerColor = SurfaceWhite,
        shape = RoundedCornerShape(14.dp),
    )
}

@Composable
private fun ImageDetailDialog(
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
    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("图片收藏", color = DeepTeal, fontSize = 12.sp)
                Text(
                    memo.title,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                MemoImage(
                    bytes = displayBytes,
                    loading = displayBytes == null && (isLoadingThumbnail || isLoadingFull),
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(if (expanded) 320.dp else 200.dp)
                        .clickable { expanded = !expanded },
                    maxDimension = if (expanded) 2_048 else 1_280,
                    contentScale = if (expanded) ContentScale.Fit else ContentScale.Crop,
                    contentDescription = memo.title,
                )
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(
                        if (expanded) "点击图片可收起" else "点击图片查看原图",
                        color = TextMuted,
                        style = MaterialTheme.typography.labelSmall,
                    )
                    if (memo.id != null) {
                        TextButton(
                            onClick = { expanded = !expanded },
                            enabled = !isSaving,
                        ) {
                            Text(if (expanded) "收起原图" else "查看原图")
                        }
                    }
                }
                memo.body.takeIf { it.isNotBlank() }?.let { note ->
                    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        Text("备注", color = TextMuted, fontSize = 11.sp)
                        Text(note, style = MaterialTheme.typography.bodyMedium)
                    }
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    imageDimensionsLabel(memo.imageWidth, memo.imageHeight)?.let { dimensions ->
                        ImageMetaChip(dimensions)
                    }
                    formatFileSize(memo.imageSizeBytes)?.let { size -> ImageMetaChip(size) }
                    imageMimeLabel(memo.imageMimeType)?.let { label -> ImageMetaChip(label) }
                }
                ImageOcrSection(memo)
                if (memo.id == null || !memo.hasUploadedImage()) {
                    Text(
                        "图片尚未上传完成；联网后会自动重试。",
                        color = WarmAmberText,
                        style = MaterialTheme.typography.labelSmall,
                    )
                }
                Text(
                    "服务端版本 ${memo.version}",
                    color = TextMuted,
                    style = MaterialTheme.typography.labelSmall,
                )
            }
        },
        confirmButton = {
            Button(
                onClick = onMoveToTrash,
                enabled = !isSaving,
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFB84A4A)),
            ) { Text("移入回收站") }
        },
        dismissButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                TextButton(onClick = onShare, enabled = !isSaving) { Text("分享") }
                OutlinedButton(onClick = onDismiss, enabled = !isSaving) { Text("关闭") }
            }
        },
        containerColor = SurfaceWhite,
        shape = RoundedCornerShape(14.dp),
    )
}

@Composable
private fun ImageMetaChip(label: String) {
    Text(
        label,
        modifier = Modifier
            .background(TealSoft, RoundedCornerShape(20.dp))
            .padding(horizontal = 10.dp, vertical = 5.dp),
        color = DeepTeal,
        fontSize = 11.sp,
    )
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
private fun EditMemoDialog(
    memo: Memo,
    isSaving: Boolean,
    onDismiss: () -> Unit,
    onMoveToTrash: () -> Unit,
    onSave: (String, String, String?, String?, String?) -> Unit,
    onReview: (String) -> Unit,
    onPlayAudio: () -> Unit,
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
                if (!memo.transcript.isNullOrBlank()) {
                    OutlinedTextField(
                        value = memo.transcript,
                        onValueChange = {},
                        readOnly = true,
                        label = { Text("会议转写（我 / 对方）") },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 3,
                        maxLines = 8,
                        shape = RoundedCornerShape(10.dp),
                    )
                }
                OutlinedTextField(
                    value = title,
                    onValueChange = { title = it },
                    label = { Text(if (isWord) "单词或短语" else "标题") },
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(10.dp),
                )
                if (isWord) {
                    Text(
                        "上次 ${memo.lastReviewAt?.let(::formatTime) ?: "尚未复习"} · 下次 ${memo.nextReviewAt?.let(::formatTime) ?: "待安排"}",
                        color = TextMuted,
                        style = MaterialTheme.typography.labelSmall,
                    )
                    PhoneticPlayField(
                        lemma = title,
                        phonetic = wordPhonetic,
                        onPhoneticChange = { wordPhonetic = it },
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
                        SentencePronunciationButton(text = wordExample)
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
                    SentencePronunciationButton(text = body)
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
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = onMoveToTrash, enabled = !isSaving) {
                    Text("移入回收站", color = Color(0xFFB84A4A))
                }
                OutlinedButton(onClick = onDismiss, enabled = !isSaving) {
                    Text("取消")
                }
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
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("收藏英语单词", fontWeight = FontWeight.SemiBold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    if (isLookingUp) {
                        "正在填入中文释义、音标和例句…"
                    } else {
                        "输入单词后自动填入中文释义、音标和例句"
                    },
                    color = TextMuted,
                    style = MaterialTheme.typography.bodySmall,
                )
                TextButton(onClick = onFillClipboard, enabled = !isSaving) {
                    Text("从剪贴板填入")
                }
                OutlinedTextField(
                    value = lemma,
                    onValueChange = onLemmaChange,
                    label = { Text("单词或短语") },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("输入后自动填入中文释义") },
                    singleLine = true,
                    shape = RoundedCornerShape(10.dp),
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
                    shape = RoundedCornerShape(10.dp),
                )
                OutlinedTextField(
                    value = example,
                    onValueChange = onExampleChange,
                    label = { Text("例句（自动填入）") },
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
    isPaused: Boolean,
    recording: VoiceRecording?,
    elapsedMs: Int,
    amplitudePercent: Int,
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
    val seconds = elapsedMs / 1_000
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
                        Text("${amplitudePercent}%", color = TextMuted, fontSize = 12.sp)
                    }
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(8.dp)
                            .background(TealSoft, RoundedCornerShape(99.dp)),
                    ) {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth((amplitudePercent / 100f).coerceIn(0f, 1f))
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
    NavigationBar(containerColor = SurfaceWhite) {
        NavigationBarItem(
            selected = !showAllMemos && !showReview && !showTrash && !showInbox,
            onClick = onShowHome,
            icon = { Text("⌂", fontSize = 17.sp) },
            label = { Text("首页", fontSize = 11.sp) },
            colors = memoNavigationColors(),
        )
        NavigationBarItem(
            selected = showAllMemos && !showReview && !showTrash && !showInbox,
            onClick = onShowLibrary,
            icon = { Text("□", fontSize = 17.sp) },
            label = { Text("资料库", fontSize = 11.sp) },
            colors = memoNavigationColors(),
        )
        NavigationBarItem(
            selected = showReview,
            onClick = onShowReview,
            icon = { Text("◷", fontSize = 17.sp) },
            label = { Text("回顾", fontSize = 11.sp) },
            colors = memoNavigationColors(),
        )
        NavigationBarItem(
            selected = false,
            onClick = onShowVault,
            icon = {
                // 角标是上次解锁时需要处理的提醒数，锁定后仍然显示。
                BadgedBox(badge = { if (vaultReminderCount > 0) Badge { Text("$vaultReminderCount") } }) {
                    Text("◈", fontSize = 17.sp)
                }
            },
            label = { Text("密码库", fontSize = 11.sp) },
            colors = memoNavigationColors(),
        )
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
private fun SentencePronunciationButton(text: String) {
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
    ) {
        Text(if (playing) "句子播放中…" else "▶ 播放例句/内容")
    }
}

@Composable
private fun PhoneticPlayField(
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
        label = { Text("音标（点右侧播放）") },
        placeholder = { Text("输入单词后自动填入") },
        supportingText = {
            Text(if (canPlay) "点击音标旁的 ▶美 / ▶英 播放读音" else "先输入单词再播放读音")
        },
        singleLine = true,
        shape = RoundedCornerShape(10.dp),
        trailingIcon = {
            Row {
                TextButton(
                    onClick = { play("us") },
                    enabled = canPlay,
                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp),
                ) {
                    Text(
                        if (playingTag == "us") "播放中" else "▶美",
                        color = if (canPlay) DeepTeal else TextMuted,
                        fontSize = 13.sp,
                    )
                }
                TextButton(
                    onClick = { play("uk") },
                    enabled = canPlay,
                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 0.dp),
                ) {
                    Text(
                        if (playingTag == "uk") "播放中" else "▶英",
                        color = if (canPlay) DeepTeal else TextMuted,
                        fontSize = 13.sp,
                    )
                }
            }
        },
    )
}

@Composable
private fun ClickablePhonetic(
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
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        TextButton(
            onClick = { play("us") },
            enabled = canPlay,
            contentPadding = PaddingValues(horizontal = 8.dp, vertical = 4.dp),
        ) {
            Text(
                if (playingTag == "us") "播放中… $display" else display,
                color = if (canPlay) DeepTeal else TextMuted,
                fontSize = 20.sp,
                fontWeight = FontWeight.Medium,
            )
        }
        TextButton(
            onClick = { play("us") },
            enabled = canPlay,
            contentPadding = PaddingValues(horizontal = 6.dp, vertical = 0.dp),
        ) {
            Text("▶美", color = if (canPlay) DeepTeal else TextMuted, fontSize = 13.sp)
        }
        TextButton(
            onClick = { play("uk") },
            enabled = canPlay,
            contentPadding = PaddingValues(horizontal = 6.dp, vertical = 0.dp),
        ) {
            Text(
                if (playingTag == "uk") "播放中" else "▶英",
                color = if (canPlay) DeepTeal else TextMuted,
                fontSize = 13.sp,
            )
        }
    }
}

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

private fun quickAccessHost(url: String?): String {
    return url?.let { runCatching { java.net.URI(it).host?.removePrefix("www.") }.getOrNull() }.orEmpty()
}

// 由站点名算出固定色相，同一站点每次显示同一种颜色；不加载站点图标，避免向第三方暴露访问记录。
private fun quickAccessAvatarColor(text: String): Color {
    var hash = 0
    for (char in text) hash = (hash * 31 + char.code) % 360
    return Color.hsl(hash.toFloat(), 0.45f, 0.42f)
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun QuickAccessSection(
    entries: List<QuickAccessEntry>,
    onOpen: (Memo) -> Unit,
    onRemove: (Memo) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("快速访问", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.width(8.dp))
            Text("按打开次数排列", color = TextMuted, style = MaterialTheme.typography.labelMedium)
        }
        if (entries.isEmpty()) {
            Text(
                "还没有打开记录。点开网页资料的「打开原网页」后，常用的网页会按打开次数出现在这里。",
                color = TextMuted,
                style = MaterialTheme.typography.bodySmall,
            )
            return@Column
        }
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            entries.forEach { entry ->
                val memo = entry.memo
                val host = quickAccessHost(memo.sourceUrl)
                val name = host.ifBlank { memo.title }
                Row(
                    modifier = Modifier
                        .widthIn(max = 220.dp)
                        .background(SurfaceWhite, RoundedCornerShape(12.dp))
                        .border(1.dp, Border, RoundedCornerShape(12.dp))
                        .clickable { onOpen(memo) }
                        .padding(start = 8.dp, top = 6.dp, bottom = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(
                        modifier = Modifier
                            .size(28.dp)
                            .background(quickAccessAvatarColor(name), RoundedCornerShape(8.dp)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(
                            name.trim().firstOrNull()?.uppercase() ?: "?",
                            color = Color.White,
                            fontWeight = FontWeight.Bold,
                            fontSize = 13.sp,
                        )
                    }
                    Spacer(Modifier.width(8.dp))
                    Column(Modifier.weight(1f, fill = false)) {
                        Text(
                            memo.title,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Text(
                            "${entry.openCount} 次 · $host",
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            color = TextMuted,
                            style = MaterialTheme.typography.labelSmall,
                        )
                    }
                    TextButton(
                        onClick = { onRemove(memo) },
                        modifier = Modifier.size(36.dp),
                        contentPadding = PaddingValues(0.dp),
                    ) { Text("×", color = TextMuted) }
                }
            }
        }
    }
}
