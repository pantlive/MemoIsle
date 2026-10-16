package com.memoisle.app.ui

import android.app.Activity
import android.content.ClipData
import android.content.ClipDescription
import android.content.ClipboardManager
import android.content.Context
import android.os.Build
import android.os.PersistableBundle
import android.view.WindowManager
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.memoisle.app.VaultPhase
import com.memoisle.app.VaultViewModel
import com.memoisle.app.data.RecoveryCode
import com.memoisle.app.data.VAULT_KIND_LABELS
import com.memoisle.app.data.VAULT_KIND_LOGIN
import com.memoisle.app.data.VAULT_KIND_RECOVERY
import com.memoisle.app.data.VAULT_KIND_SECRET
import com.memoisle.app.data.VAULT_ROTATE_OPTIONS
import com.memoisle.app.data.VaultEntry
import com.memoisle.app.data.VaultItemData
import com.memoisle.app.data.VaultReminder
import com.memoisle.app.data.collectVaultReminders
import com.memoisle.app.data.daysSince
import com.memoisle.app.data.generateVaultPassword
import com.memoisle.app.data.isWeakVaultPassword
import com.memoisle.app.data.lastChangedAt
import com.memoisle.app.data.parseRecoveryCodes
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeParseException
import java.time.temporal.ChronoUnit
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private const val CLIPBOARD_CLEAR_MS = 30_000L
private const val REMINDER_PREVIEW_LIMIT = 4
private val DangerRed = Color(0xFFB84A4A)
private val DangerSoft = Color(0xFFF8E9E9)
private const val FILTER_ALL = "all"
private const val FILTER_REMINDERS = "reminders"

private val kindIcons = mapOf(VAULT_KIND_LOGIN to "账", VAULT_KIND_SECRET to "钥", VAULT_KIND_RECOVERY to "码")

private fun subtitle(data: VaultItemData): String = when (data.kind) {
    VAULT_KIND_LOGIN -> data.username.ifBlank { data.url.ifBlank { "未填写用户名" } }
    VAULT_KIND_SECRET -> if (data.secret.isNotEmpty()) "${data.secret.length} 个字符" else "未填写密钥"
    else -> {
        val remaining = data.codes.count { !it.used }
        (if (data.account.isNotBlank()) "${data.account} · " else "") + "剩余 $remaining / ${data.codes.size} 个可用"
    }
}

// 只按名称、用户名、网址、账号和备注搜索，不匹配密码和密钥本身。
private fun VaultItemData.matches(query: String): Boolean {
    if (query.isBlank()) return true
    val haystack = listOf(title, notes, username, url, account).joinToString(" ")
    return haystack.contains(query.trim(), ignoreCase = true)
}

@Composable
fun VaultScreen(
    viewModel: VaultViewModel,
    onClose: () -> Unit,
) {
    val state = viewModel.uiState
    val context = LocalContext.current
    val snackbarHostState = remember { SnackbarHostState() }
    val coroutineScope = rememberCoroutineScope()
    val lifecycleOwner = LocalLifecycleOwner.current
    var password by remember { mutableStateOf("") }
    var query by remember { mutableStateOf("") }
    var filter by remember { mutableStateOf(FILTER_ALL) }
    var editor by remember { mutableStateOf<Pair<VaultEntry?, VaultItemData>?>(null) }
    var choosingKind by remember { mutableStateOf(false) }

    BackHandler(onBack = onClose)
    LaunchedEffect(Unit) { viewModel.load() }

    // 密码库页面禁止截屏和在最近任务里显示内容；App 退到后台立刻锁定。
    DisposableEffect(lifecycleOwner) {
        val window = (context as? Activity)?.window
        window?.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP) viewModel.lock()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            window?.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
        }
    }

    LaunchedEffect(state.message, state.error) {
        val text = state.error ?: state.message ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(text)
        viewModel.clearMessage()
    }

    fun copy(value: String, label: String) {
        if (value.isEmpty()) return
        val clipboard = context.getSystemService(ClipboardManager::class.java) ?: return
        val clip = ClipData.newPlainText("MemoIsle", value)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            // 标记为敏感内容，系统不会在剪贴板预览里显示明文。
            clip.description.extras = PersistableBundle().apply {
                putBoolean(ClipDescription.EXTRA_IS_SENSITIVE, true)
            }
        }
        clipboard.setPrimaryClip(clip)
        viewModel.touch()
        viewModel.showMessage("已复制$label，${CLIPBOARD_CLEAR_MS / 1000} 秒后清空剪贴板。")
        coroutineScope.launch {
            delay(CLIPBOARD_CLEAR_MS)
            clearClipboardIfUnchanged(context, value)
        }
    }

    val reminders = remember(state.entries) { collectVaultReminders(state.entries) }
    val remindersByEntry = remember(reminders) { reminders.groupBy { it.entryId } }
    LaunchedEffect(remindersByEntry, state.phase) {
        if (state.phase == VaultPhase.UNLOCKED) viewModel.rememberReminderCount(remindersByEntry.size)
    }
    val visible = state.entries
        .filter { entry ->
            when (filter) {
                FILTER_ALL -> true
                FILTER_REMINDERS -> remindersByEntry.containsKey(entry.id)
                else -> entry.data.kind == filter
            }
        }
        .filter { it.data.matches(query) }
        .sortedBy { it.data.title }

    Scaffold(
        modifier = Modifier.fillMaxSize(),
        containerColor = WarmMist,
        snackbarHost = { SnackbarHost(snackbarHostState) },
        floatingActionButton = {
            if (state.phase == VaultPhase.UNLOCKED) {
                FloatingActionButton(
                    onClick = { choosingKind = true },
                    containerColor = DeepTeal,
                    contentColor = Color.White,
                    shape = RoundedCornerShape(18.dp),
                ) { Text("＋", fontSize = 24.sp) }
            }
        },
    ) { innerPadding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .imePadding(),
            contentPadding = PaddingValues(start = 16.dp, top = 12.dp, end = 16.dp, bottom = 104.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = onClose) { Text("‹ 返回") }
                    Column(Modifier.weight(1f)) {
                        Text("密码库", fontSize = 22.sp, fontWeight = FontWeight.Bold, color = DeepTealHover)
                        Text("端到端加密 · 服务器只保存密文", color = TextMuted, style = MaterialTheme.typography.bodySmall)
                    }
                    if (state.phase == VaultPhase.UNLOCKED) {
                        TextButton(onClick = viewModel::lock) { Text("锁定") }
                    }
                }
            }
            when (state.phase) {
                VaultPhase.LOADING -> item { Text("正在读取密码库……", color = TextMuted) }
                VaultPhase.ERROR -> item {
                    VaultCard {
                        Text(state.error ?: "暂时无法读取密码库。")
                        OutlinedButton(onClick = viewModel::load) { Text("重试") }
                    }
                }
                VaultPhase.NOT_CONFIGURED -> item {
                    VaultCard {
                        Text("还没有密码库", fontWeight = FontWeight.SemiBold)
                        Text(
                            "请先在 MemoIsle 网页端设置主密码。之后在手机上输入同一个主密码即可解锁使用。",
                            color = TextMuted,
                        )
                    }
                }
                VaultPhase.LOCKED -> item {
                    VaultCard {
                        Text("密码库已锁定", fontWeight = FontWeight.SemiBold, fontSize = 18.sp)
                        Text(
                            "输入主密码解锁" + (if (state.itemCount > 0) "，共 ${state.itemCount} 条" else "") +
                                "。解锁在手机上完成，主密码不会发送到服务器。",
                            color = TextMuted,
                        )
                        OutlinedTextField(
                            value = password,
                            onValueChange = { password = it },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text("主密码") },
                            visualTransformation = PasswordVisualTransformation(),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        )
                        Button(
                            onClick = {
                                viewModel.unlock(password)
                                password = ""
                            },
                            enabled = !state.busy && password.isNotEmpty(),
                            colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
                        ) {
                            if (state.busy) {
                                CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = Color.White)
                                Spacer(Modifier.width(8.dp))
                                Text("解锁中…")
                            } else {
                                Text("解锁")
                            }
                        }
                        Text(
                            "忘记主密码、更改主密码和加密备份请在网页端操作。",
                            color = TextMuted,
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
                VaultPhase.UNLOCKED -> {
                    if (reminders.isNotEmpty() && filter != FILTER_REMINDERS && query.isBlank()) {
                        item {
                            ReminderCard(
                                reminders = reminders,
                                entryCount = remindersByEntry.size,
                                onOpen = { reminder ->
                                    state.entries.firstOrNull { it.id == reminder.entryId }?.let { entry ->
                                        editor = entry to entry.data
                                    }
                                },
                                onShowAll = { filter = FILTER_REMINDERS },
                            )
                        }
                    }
                    item {
                        OutlinedTextField(
                            value = query,
                            onValueChange = { query = it },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text("按名称、用户名、网址或备注搜索") },
                        )
                    }
                    item {
                        KindFilters(
                            selected = filter,
                            entries = state.entries,
                            reminderCount = remindersByEntry.size,
                            onSelect = { filter = it },
                        )
                    }
                    if (state.brokenCount > 0) {
                        item { Text("有 ${state.brokenCount} 条无法解密，可能已损坏或被篡改，已跳过显示。", color = DangerRed) }
                    }
                    if (state.entries.isEmpty()) {
                        item {
                            VaultCard {
                                Text("密码库还是空的", fontWeight = FontWeight.SemiBold)
                                Text("点右下角 ＋ 保存网站账号密码、API Key 或两步验证的恢复码。", color = TextMuted)
                            }
                        }
                    } else if (visible.isEmpty()) {
                        item {
                            Text(
                                if (filter == FILTER_REMINDERS && query.isBlank()) "提醒都处理完了。" else "没有匹配的条目。",
                                color = TextMuted,
                            )
                        }
                    }
                    items(visible, key = { it.id }) { entry ->
                        VaultRow(
                            entry = entry,
                            reminders = remindersByEntry[entry.id].orEmpty(),
                            showReminderText = filter == FILTER_REMINDERS,
                            onOpen = {
                                viewModel.touch()
                                editor = entry to entry.data
                            },
                            onCopy = ::copy,
                        )
                    }
                }
            }
        }
    }

    if (choosingKind) {
        AlertDialog(
            onDismissRequest = { choosingKind = false },
            title = { Text("新建") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(VAULT_KIND_LOGIN, VAULT_KIND_SECRET, VAULT_KIND_RECOVERY).forEach { kind ->
                        OutlinedButton(
                            onClick = {
                                choosingKind = false
                                editor = null to VaultItemData.empty(kind)
                            },
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text(VAULT_KIND_LABELS.getValue(kind)) }
                    }
                }
            },
            confirmButton = {},
            dismissButton = { TextButton(onClick = { choosingKind = false }) { Text("取消") } },
        )
    }

    editor?.let { (entry, initial) ->
        VaultItemEditor(
            entry = entry,
            initial = initial,
            reminders = entry?.let { remindersByEntry[it.id] }.orEmpty(),
            busy = state.busy,
            onTouch = viewModel::touch,
            onCopy = ::copy,
            onDismiss = { editor = null },
            onSave = { data -> viewModel.save(entry, data) { editor = null } },
            onDelete = { entry?.let { viewModel.delete(it) { editor = null } } },
        )
    }
}

private fun clearClipboardIfUnchanged(context: Context, value: String) {
    val clipboard = context.getSystemService(ClipboardManager::class.java) ?: return
    // 读得到剪贴板时只在内容没变时清空，避免覆盖用户之后复制的其他内容。
    val current = runCatching {
        clipboard.primaryClip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(context)?.toString()
    }.getOrNull()
    if (current != null && current != value) return
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
        clipboard.clearPrimaryClip()
    } else {
        clipboard.setPrimaryClip(ClipData.newPlainText("", ""))
    }
}

@Composable
private fun VaultCard(content: @Composable () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = BorderStroke(1.dp, Border),
        shape = RoundedCornerShape(14.dp),
    ) {
        Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) { content() }
    }
}

@Composable
private fun ReminderBadge(reminder: VaultReminder) {
    Text(
        text = reminder.type.label,
        modifier = Modifier
            .background(if (reminder.danger) DangerSoft else WarmAmberSoft, RoundedCornerShape(999.dp))
            .padding(horizontal = 8.dp, vertical = 2.dp),
        color = if (reminder.danger) DangerRed else WarmAmberText,
        fontSize = 11.sp,
        fontWeight = FontWeight.Bold,
        maxLines = 1,
    )
}

@Composable
private fun ReminderCard(
    reminders: List<VaultReminder>,
    entryCount: Int,
    onOpen: (VaultReminder) -> Unit,
    onShowAll: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color(0xFFFCF6F6)),
        border = BorderStroke(1.dp, Color(0xFFEBCFCF)),
        shape = RoundedCornerShape(14.dp),
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("密码提醒", fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.width(8.dp))
                Text("$entryCount 条需要处理", color = TextMuted, style = MaterialTheme.typography.bodySmall)
            }
            reminders.take(REMINDER_PREVIEW_LIMIT).forEach { reminder ->
                // 名称在前、标签在后，与条目列表一致；标签宽度不同时名称仍左对齐。
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable { onOpen(reminder) }
                        .padding(vertical = 4.dp),
                    verticalArrangement = Arrangement.spacedBy(2.dp),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(
                            reminder.title,
                            modifier = Modifier.weight(1f, fill = false),
                            fontWeight = FontWeight.SemiBold,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        ReminderBadge(reminder)
                    }
                    Text(reminder.message, color = TextMuted, style = MaterialTheme.typography.bodySmall)
                }
            }
            if (reminders.size > REMINDER_PREVIEW_LIMIT) {
                OutlinedButton(onClick = onShowAll) { Text("查看全部 ${reminders.size} 项提醒") }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun KindFilters(
    selected: String,
    entries: List<VaultEntry>,
    reminderCount: Int,
    onSelect: (String) -> Unit,
) {
    val options = buildList {
        add(FILTER_ALL to "全部 ${entries.size}")
        listOf(VAULT_KIND_LOGIN, VAULT_KIND_SECRET, VAULT_KIND_RECOVERY).forEach { kind ->
            add(kind to "${VAULT_KIND_LABELS.getValue(kind)} ${entries.count { it.data.kind == kind }}")
        }
        // 没有提醒时不显示；正在看这一栏时保留，避免按钮突然消失。
        if (reminderCount > 0 || selected == FILTER_REMINDERS) add(FILTER_REMINDERS to "需处理 $reminderCount")
    }
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        options.forEach { (value, label) ->
            FilterChip(selected = selected == value, onClick = { onSelect(value) }, label = { Text(label) })
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun VaultRow(
    entry: VaultEntry,
    reminders: List<VaultReminder>,
    showReminderText: Boolean,
    onOpen: () -> Unit,
    onCopy: (String, String) -> Unit,
) {
    val data = entry.data
    val nextCode = data.codes.firstOrNull { !it.used }
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = BorderStroke(1.dp, Border),
        shape = RoundedCornerShape(12.dp),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth().clickable(onClick = onOpen),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Box(
                    modifier = Modifier.size(34.dp).background(TealSoft, RoundedCornerShape(9.dp)),
                    contentAlignment = Alignment.Center,
                ) { Text(kindIcons.getValue(data.kind), color = DeepTeal, fontWeight = FontWeight.Bold) }
                Column(Modifier.weight(1f)) {
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Text(data.title, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        reminders.forEach { ReminderBadge(it) }
                    }
                    Text(
                        text = if (showReminderText && reminders.isNotEmpty()) {
                            reminders.joinToString(" ") { it.message }
                        } else {
                            "${VAULT_KIND_LABELS.getValue(data.kind)} · ${subtitle(data)}"
                        },
                        color = TextMuted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                when (data.kind) {
                    VAULT_KIND_LOGIN -> {
                        OutlinedButton(onClick = { onCopy(data.username, "用户名") }, enabled = data.username.isNotEmpty()) { Text("复制用户名") }
                        OutlinedButton(onClick = { onCopy(data.password, "密码") }, enabled = data.password.isNotEmpty()) { Text("复制密码") }
                    }
                    VAULT_KIND_SECRET -> OutlinedButton(onClick = { onCopy(data.secret, "密钥") }, enabled = data.secret.isNotEmpty()) { Text("复制密钥") }
                    else -> OutlinedButton(onClick = { nextCode?.let { onCopy(it.code, "恢复码") } }, enabled = nextCode != null) {
                        Text(if (nextCode != null) "复制未用的恢复码" else "恢复码已用完")
                    }
                }
            }
        }
    }
}

private fun rotateLabel(days: Int): String = when (days) {
    0 -> "不提醒"
    365 -> "每年"
    else -> "每 $days 天"
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun VaultItemEditor(
    entry: VaultEntry?,
    initial: VaultItemData,
    reminders: List<VaultReminder>,
    busy: Boolean,
    onTouch: () -> Unit,
    onCopy: (String, String) -> Unit,
    onDismiss: () -> Unit,
    onSave: (VaultItemData) -> Unit,
    onDelete: () -> Unit,
) {
    var draft by remember(initial) { mutableStateOf(initial) }
    var secretVisible by remember { mutableStateOf(false) }
    var pastedCodes by remember { mutableStateOf("") }
    var confirmDiscard by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    val dirty = draft != initial
    val isNew = entry == null
    fun update(next: VaultItemData) {
        draft = next
        onTouch()
    }
    fun requestDismiss() {
        if (dirty) confirmDiscard = true else onDismiss()
    }
    val expiresIn = draft.expiresOn.takeIf { it.isNotBlank() }?.let { text ->
        try {
            ChronoUnit.DAYS.between(LocalDate.now(), LocalDate.parse(text))
        } catch (error: DateTimeParseException) {
            null
        }
    }
    val expiryInvalid = draft.expiresOn.isNotBlank() && expiresIn == null
    val secretChanged = draft.secretValue.isNotEmpty() && draft.secretValue != initial.secretValue
    val changedLabel = when {
        secretChanged -> "保存后记为今天"
        entry == null || entry.data.secretValue.isEmpty() -> "还没有填写"
        else -> {
            val iso = lastChangedAt(entry)
            val days = daysSince(iso, LocalDate.now(), ZoneId.systemDefault())
            val date = iso.take(10)
            "$date（${if (days == 0L) "今天" else "$days 天前"}）"
        }
    }

    Dialog(onDismissRequest = ::requestDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(modifier = Modifier.fillMaxSize(), color = SurfaceWhite) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .imePadding()
                    .verticalScroll(rememberScrollState())
                    .padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(VAULT_KIND_LABELS.getValue(draft.kind), color = DeepTeal, style = MaterialTheme.typography.labelMedium)
                        Text(
                            if (isNew) "新建${VAULT_KIND_LABELS.getValue(draft.kind)}" else draft.title.ifBlank { "未命名" },
                            fontSize = 20.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                    }
                    TextButton(onClick = ::requestDismiss, enabled = !busy) { Text("关闭") }
                }
                reminders.forEach { reminder ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(if (reminder.danger) DangerSoft else WarmAmberSoft, RoundedCornerShape(9.dp))
                            .padding(10.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text(reminder.type.label, fontWeight = FontWeight.Bold, color = if (reminder.danger) DangerRed else WarmAmberText)
                        Text(reminder.message, color = if (reminder.danger) DangerRed else WarmAmberText)
                    }
                }
                OutlinedTextField(
                    value = draft.title,
                    onValueChange = { update(draft.copy(title = it.take(200))) },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text("名称") },
                )
                when (draft.kind) {
                    VAULT_KIND_LOGIN -> {
                        OutlinedTextField(
                            value = draft.username,
                            onValueChange = { update(draft.copy(username = it)) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text("用户名或邮箱") },
                            trailingIcon = { TextButton(onClick = { onCopy(draft.username, "用户名") }) { Text("复制") } },
                        )
                        OutlinedTextField(
                            value = draft.password,
                            onValueChange = { update(draft.copy(password = it)) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text("密码") },
                            textStyle = MaterialTheme.typography.bodyLarge.copy(fontFamily = FontFamily.Monospace),
                            visualTransformation = if (secretVisible) VisualTransformation.None else PasswordVisualTransformation(),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        )
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(onClick = { secretVisible = !secretVisible }) { Text(if (secretVisible) "隐藏" else "显示") }
                            OutlinedButton(onClick = { update(draft.copy(password = generateVaultPassword())) }) { Text("生成") }
                            OutlinedButton(onClick = { onCopy(draft.password, "密码") }, enabled = draft.password.isNotEmpty()) { Text("复制") }
                        }
                        if (!draft.skipChecks && isWeakVaultPassword(draft.password)) {
                            Text("密码偏弱：至少 12 位并混合大小写、数字和符号更安全，也可以点「生成」。", color = DangerRed, style = MaterialTheme.typography.bodySmall)
                        }
                        OutlinedTextField(
                            value = draft.url,
                            onValueChange = { update(draft.copy(url = it)) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text("网址") },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                        )
                    }
                    VAULT_KIND_SECRET -> {
                        OutlinedTextField(
                            value = draft.secret,
                            onValueChange = { update(draft.copy(secret = it)) },
                            modifier = Modifier.fillMaxWidth(),
                            minLines = if (secretVisible) 4 else 1,
                            label = { Text("密钥内容") },
                            textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                            visualTransformation = if (secretVisible) VisualTransformation.None else PasswordVisualTransformation(),
                        )
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedButton(onClick = { secretVisible = !secretVisible }) { Text(if (secretVisible) "隐藏" else "显示") }
                            OutlinedButton(onClick = { onCopy(draft.secret, "密钥") }, enabled = draft.secret.isNotEmpty()) { Text("复制") }
                        }
                    }
                    else -> {
                        OutlinedTextField(
                            value = draft.account,
                            onValueChange = { update(draft.copy(account = it)) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text("对应账号") },
                        )
                        if (draft.codes.isNotEmpty()) {
                            Text("剩余 ${draft.codes.count { !it.used }} / ${draft.codes.size} 个可用", color = TextMuted, style = MaterialTheme.typography.bodySmall)
                        }
                        draft.codes.forEachIndexed { index, code ->
                            RecoveryCodeRow(
                                code = code,
                                onToggle = {
                                    update(draft.copy(codes = draft.codes.mapIndexed { current, item ->
                                        if (current == index) item.copy(used = !item.used) else item
                                    }))
                                },
                                onCopy = { onCopy(code.code, "恢复码") },
                                onRemove = { update(draft.copy(codes = draft.codes.filterIndexed { current, _ -> current != index })) },
                            )
                        }
                        OutlinedTextField(
                            value = pastedCodes,
                            onValueChange = { pastedCodes = it },
                            modifier = Modifier.fillMaxWidth(),
                            minLines = 2,
                            label = { Text("添加恢复码") },
                            placeholder = { Text("把网站给的恢复码整段粘贴进来，按空格、换行或逗号自动拆分") },
                        )
                        OutlinedButton(
                            onClick = {
                                update(draft.copy(codes = parseRecoveryCodes(pastedCodes, draft.codes)))
                                pastedCodes = ""
                            },
                            enabled = pastedCodes.isNotBlank(),
                        ) { Text("添加恢复码") }
                    }
                }
                if (draft.kind == VAULT_KIND_LOGIN || draft.kind == VAULT_KIND_SECRET) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(SurfaceSubtle, RoundedCornerShape(12.dp))
                            .padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text("提醒", fontWeight = FontWeight.SemiBold)
                        Text(
                            "${if (draft.kind == VAULT_KIND_LOGIN) "密码" else "密钥"}上次更换：$changedLabel",
                            color = TextMuted,
                            style = MaterialTheme.typography.bodySmall,
                        )
                        Text("定期更换", style = MaterialTheme.typography.labelMedium)
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            VAULT_ROTATE_OPTIONS.forEach { days ->
                                FilterChip(
                                    selected = draft.rotateDays == days,
                                    onClick = { update(draft.copy(rotateDays = days)) },
                                    label = { Text(rotateLabel(days)) },
                                )
                            }
                        }
                        OutlinedTextField(
                            value = draft.expiresOn,
                            onValueChange = { update(draft.copy(expiresOn = it.trim().take(10))) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text("到期日（可选）") },
                            placeholder = { Text("例如 2027-01-31") },
                            isError = expiryInvalid,
                            supportingText = {
                                Text(
                                    when {
                                        expiryInvalid -> "请按 年-月-日 填写，例如 2027-01-31"
                                        expiresIn == null -> "留空表示不会过期"
                                        expiresIn < 0 -> "已过期 ${-expiresIn} 天"
                                        expiresIn == 0L -> "今天到期"
                                        else -> "还有 $expiresIn 天到期，到期前 14 天开始提醒"
                                    },
                                )
                            },
                        )
                        if (draft.kind == VAULT_KIND_LOGIN) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Checkbox(checked = draft.skipChecks, onCheckedChange = { update(draft.copy(skipChecks = it)) })
                                Text("不检查这条的密码强度和是否与其他条目重复", style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
                OutlinedTextField(
                    value = draft.notes,
                    onValueChange = { update(draft.copy(notes = it.take(10_000))) },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 3,
                    label = { Text("备注") },
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (!isNew) {
                        OutlinedButton(onClick = { confirmDelete = true }, enabled = !busy) { Text("删除", color = DangerRed) }
                    }
                    Spacer(Modifier.weight(1f))
                    Button(
                        onClick = { onSave(draft.copy(title = draft.title.trim())) },
                        enabled = !busy && draft.title.isNotBlank() && !expiryInvalid && (dirty || isNew),
                        colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
                    ) { Text(if (busy) "加密保存中…" else "保存") }
                }
            }
        }
    }

    if (confirmDiscard) {
        AlertDialog(
            onDismissRequest = { confirmDiscard = false },
            text = { Text("有未保存的修改，确定放弃吗？") },
            confirmButton = {
                TextButton(onClick = {
                    confirmDiscard = false
                    onDismiss()
                }) { Text("放弃修改") }
            },
            dismissButton = { TextButton(onClick = { confirmDiscard = false }) { Text("继续编辑") } },
        )
    }
    if (confirmDelete) {
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            text = { Text("永久删除「${initial.title}」？删除后无法恢复。") },
            confirmButton = {
                TextButton(onClick = {
                    confirmDelete = false
                    onDelete()
                }) { Text("删除", color = DangerRed) }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("取消") } },
        )
    }
}

@Composable
private fun RecoveryCodeRow(
    code: RecoveryCode,
    onToggle: () -> Unit,
    onCopy: () -> Unit,
    onRemove: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(SurfaceSubtle, RoundedCornerShape(8.dp))
            .padding(horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Checkbox(checked = code.used, onCheckedChange = { onToggle() })
        // 勾选表示已用；文字跟着状态变，未用的码不会被读成“已用”。
        Text(
            if (code.used) "已用" else "可用",
            color = if (code.used) TextMuted else DeepTeal,
            style = MaterialTheme.typography.bodySmall,
        )
        Spacer(Modifier.width(8.dp))
        Text(
            code.code,
            modifier = Modifier.weight(1f),
            fontFamily = FontFamily.Monospace,
            color = if (code.used) TextMuted else TextStrong,
            textDecoration = if (code.used) TextDecoration.LineThrough else null,
        )
        TextButton(onClick = onCopy, enabled = !code.used) { Text("复制") }
        TextButton(onClick = onRemove) { Text("×", color = DangerRed) }
    }
}
