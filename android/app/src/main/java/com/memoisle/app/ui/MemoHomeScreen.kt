package com.memoisle.app.ui

import android.Manifest
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
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
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.Logout
import androidx.compose.material.icons.automirrored.outlined.OpenInNew
import androidx.compose.material.icons.automirrored.outlined.VolumeUp
import androidx.compose.material.icons.filled.CollectionsBookmark
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Archive
import androidx.compose.material.icons.outlined.Autorenew
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.CloseFullscreen
import androidx.compose.material.icons.outlined.CloudUpload
import androidx.compose.material.icons.outlined.CollectionsBookmark
import androidx.compose.material.icons.outlined.ContentCopy
import androidx.compose.material.icons.outlined.ContentPaste
import androidx.compose.material.icons.outlined.DeleteForever
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.FileDownload
import androidx.compose.material.icons.outlined.HealthAndSafety
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.Inbox
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Lightbulb
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.Mic
import androidx.compose.material.icons.outlined.Pause
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.OpenInFull
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material.icons.outlined.Psychology
import androidx.compose.material.icons.outlined.Restore
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.SearchOff
import androidx.compose.material.icons.outlined.Share
import androidx.compose.material.icons.outlined.StarBorder
import androidx.compose.material.icons.outlined.Sync
import androidx.compose.material.icons.outlined.TaskAlt
import androidx.compose.material.icons.outlined.Tune
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LocalContentColor
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
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.memoisle.app.MemoIsleApplication
import com.memoisle.app.MemoViewModel
import com.memoisle.app.VaultViewModel
import com.memoisle.app.audio.SherpaOnnxSpeechToText
import com.memoisle.app.audio.VoiceRecorder
import com.memoisle.app.audio.VoiceRecording
import com.memoisle.app.audio.WordPronouncer
import com.memoisle.app.data.Memo
import com.memoisle.app.data.SyncState
import com.memoisle.app.data.TYPE_IDEA
import com.memoisle.app.data.TYPE_IMAGE
import com.memoisle.app.data.TYPE_RESOURCE
import com.memoisle.app.data.TYPE_WORD
import com.memoisle.app.data.assignedCategoryCodes
import com.memoisle.app.data.formatFileSize
import com.memoisle.app.data.hasUploadedImage
import com.memoisle.app.data.imageDimensionsLabel
import com.memoisle.app.data.imageOcrSourceLabel
import com.memoisle.app.data.imageOcrStatusLabel
import com.memoisle.app.data.isDueWord
import com.memoisle.app.data.isInTrash
import com.memoisle.app.data.isInboxIdea
import com.memoisle.app.data.isUnreadResource
import com.memoisle.app.data.isVisibleInLibrary
import com.memoisle.app.data.linkHealthLabel
import com.memoisle.app.data.matchesQuery
import com.memoisle.app.data.newLocalWord
import com.memoisle.app.data.normalizeResourceUrl
import com.memoisle.app.data.parseClipboardWord
import com.memoisle.app.data.resourceCategoryLabel
import com.memoisle.app.data.resourceHost
import com.memoisle.app.data.todayReviewCounts
import com.memoisle.app.data.todayReviewItems
import com.memoisle.app.data.trashDaysRemaining
import com.memoisle.app.network.QuickAccessEntry
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
private fun EmptyState(
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
private fun ReviewCard(
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
private fun ImageComposerCard(
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
private fun ResourceReadOnlyCard() {
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
            MemoFilterChip(label = label, selected = selected == value, onClick = { onSelect(value) })
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

/** 网页资料的简介：优先用大模型写的用途简介，其次网页自带描述，最后备注；备注只是网址时不算。 */
private fun resourceSummary(memo: Memo): String? =
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
        ).joinToString("  ").ifBlank { "等待补充释义" }
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
                            contentDescription = "星标",
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
                            resourceCategoryLabel(memo.resourceCategory, memo.resourceCategoryLabel),
                            color = ResourceAccent,
                            background = ResourceSoft,
                        )
                        isWord -> InfoPill(
                            "熟悉度 ${memo.familiarity}/5",
                            color = WordAccent,
                            background = WordSoft,
                        )
                        isImage -> imageMimeLabel(memo.imageMimeType)?.let {
                            InfoPill(it, color = ImageAccent, background = ImageSoft)
                        }
                        memo.audioMimeType != null -> InfoPill(
                            memo.audioDurationMs?.takeIf { it > 0 }?.let { "语音 ${it / 1_000} 秒" } ?: "语音",
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
private fun InboxMemoRow(
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
                        "${kind.label} · ${formatTime(memo.updatedAt)}",
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
                    Text("归档")
                }
                TextButton(onClick = onOrganize, enabled = !isSaving) {
                    Icon(Icons.Outlined.TaskAlt, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("整理完成")
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
                        "${kind.label} · ${memo.trashDaysRemaining()} 天后永久删除",
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
                    Text("永久删除")
                }
                TextButton(onClick = onRestore, enabled = !isSaving && memo.id != null) {
                    Icon(Icons.Outlined.Restore, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("恢复")
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
        SyncState.PENDING -> Triple("待同步", TextMuted, Icons.Outlined.CloudUpload)
        SyncState.FAILED -> Triple("同步失败", DangerRed, Icons.Outlined.ErrorOutline)
        SyncState.CONFLICT -> Triple("有冲突", WarmAmberText, Icons.Outlined.ErrorOutline)
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(14.dp))
        Spacer(Modifier.width(3.dp))
        Text(label, color = color, style = MaterialTheme.typography.labelSmall)
    }
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
            hasQuery -> "没有找到匹配内容"
            isLibrary -> "资料库还是空的"
            activeType == TYPE_RESOURCE -> "还没有收藏网页资料"
            activeType == TYPE_WORD -> "从第一个英语单词开始"
            activeType == TYPE_IMAGE -> "还没有收藏图片"
            else -> "第一条灵感正在等你"
        },
        message = when {
            hasQuery -> "换个关键词，或清除搜索后浏览全部收藏。"
            isLibrary -> "从灵感、英语单词、图片或网页资料开始收藏第一条内容。"
            activeType == TYPE_RESOURCE -> "可在 Web 端收藏，或从手机浏览器分享链接到 MemoIsle。"
            activeType == TYPE_WORD -> "保存词形、释义和例句，稍后按计划复习。"
            activeType == TYPE_IMAGE -> "从相册选择图片，原图与缩略图会同步到 Web。"
            else -> "保存后会进入本地资料库，并在联网时同步到 Web。"
        },
    )
}

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
            OutlinedButton(
                onClick = onPlayAudio,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(48.dp),
                enabled = memo.id != null,
                shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = IdeaAccent),
            ) {
                Icon(Icons.Outlined.PlayArrow, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text(if (seconds > 0) "播放原始录音 · ${seconds} 秒" else "播放原始录音")
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
private fun VoiceCaptureDialog(
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
        shape = RoundedCornerShape(12.dp),
    ) {
        Icon(Icons.AutoMirrored.Outlined.VolumeUp, contentDescription = null, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
        Text(if (playing) "播放中…" else "朗读例句 / 内容")
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

@Composable
private fun QuickAccessSection(
    entries: List<QuickAccessEntry>,
    onOpen: (Memo) -> Unit,
    onRemove: (Memo) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        SectionHeader("快速访问", trailing = "按打开次数排列")
        if (entries.isEmpty()) {
            Text(
                "还没有打开记录。点开网页资料的「打开原网页」后，常用的网页会按打开次数出现在这里。",
                color = TextMuted,
                style = MaterialTheme.typography.bodySmall,
            )
            return@Column
        }
        // 横向滑动、宽度一致的卡片，不再像换行排列那样长短不齐。
        LazyRow(
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            contentPadding = PaddingValues(end = 4.dp),
        ) {
            items(entries, key = { it.memo.clientId }) { entry ->
                val memo = entry.memo
                val host = quickAccessHost(memo.sourceUrl)
                val summary = resourceSummary(memo)
                Card(
                    onClick = { onOpen(memo) },
                    modifier = Modifier.width(176.dp),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
                    border = BorderStroke(1.dp, Border),
                ) {
                    Column(Modifier.padding(start = 12.dp, top = 12.dp, bottom = 12.dp, end = 4.dp)) {
                        Row(verticalAlignment = Alignment.Top) {
                            SiteAvatar(host.ifBlank { memo.title }, size = 34.dp)
                            Spacer(Modifier.weight(1f))
                            IconButton(
                                onClick = { onRemove(memo) },
                                modifier = Modifier.size(28.dp),
                            ) {
                                Icon(
                                    Icons.Outlined.Close,
                                    contentDescription = "从快速访问移除「${memo.title}」",
                                    tint = TextMuted,
                                    modifier = Modifier.size(16.dp),
                                )
                            }
                        }
                        Spacer(Modifier.height(10.dp))
                        Text(
                            memo.title,
                            style = MaterialTheme.typography.titleSmall,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.padding(end = 8.dp),
                        )
                        // 固定两行高度，有无简介的卡片都一样高。
                        Text(
                            summary ?: "暂无简介",
                            color = if (summary == null) TextMuted.copy(alpha = 0.6f) else TextMuted,
                            style = MaterialTheme.typography.bodySmall,
                            minLines = 2,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.padding(top = 2.dp, end = 8.dp),
                        )
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "${entry.openCount} 次 · $host",
                            color = TextMuted,
                            style = MaterialTheme.typography.labelSmall,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.padding(end = 8.dp),
                        )
                    }
                }
            }
        }
    }
}
