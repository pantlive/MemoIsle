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
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.material.icons.outlined.ContentCopy
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.Key
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.NotificationsActive
import androidx.compose.material.icons.outlined.Password
import androidx.compose.material.icons.outlined.Pin
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Shield
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material.icons.outlined.VisibilityOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
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
import com.memoisle.app.data.VAULT_AUTH_KEY
import com.memoisle.app.data.VAULT_AUTH_PASSWORD
import com.memoisle.app.data.VAULT_BILLING_LABELS
import com.memoisle.app.data.VAULT_BILLING_OPTIONS
import com.memoisle.app.data.VAULT_CURRENCY_CNY
import com.memoisle.app.data.VAULT_CURRENCY_USD
import com.memoisle.app.data.VAULT_KIND_LABELS
import com.memoisle.app.data.VAULT_KIND_LOGIN
import com.memoisle.app.data.VAULT_KIND_RECOVERY
import com.memoisle.app.data.VAULT_KIND_SECRET
import com.memoisle.app.data.VAULT_KIND_SERVER
import com.memoisle.app.data.VAULT_KIND_SUBSCRIPTION
import com.memoisle.app.data.VAULT_PROVIDER_LABELS
import com.memoisle.app.data.VAULT_PROVIDER_OPTIONS
import com.memoisle.app.data.VAULT_PROVIDER_OTHER
import com.memoisle.app.data.VAULT_ROTATE_OPTIONS
import com.memoisle.app.data.VaultEntry
import com.memoisle.app.data.VaultItemData
import com.memoisle.app.data.VaultReminder
import com.memoisle.app.data.collectVaultReminders
import com.memoisle.app.data.daysSince
import com.memoisle.app.data.defaultSubscriptionTitle
import com.memoisle.app.data.formatVaultMoney
import com.memoisle.app.data.generateVaultPassword
import com.memoisle.app.data.isWeakVaultPassword
import com.memoisle.app.data.lastChangedAt
import com.memoisle.app.data.normalizeVaultDate
import com.memoisle.app.data.normalizeVaultMoney
import com.memoisle.app.data.normalizeVaultProvider
import com.memoisle.app.data.parseRecoveryCodes
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeParseException
import java.time.temporal.ChronoUnit
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private const val CLIPBOARD_CLEAR_MS = 30_000L
private const val REMINDER_PREVIEW_LIMIT = 4
private const val FILTER_ALL = "all"
private const val FILTER_REMINDERS = "reminders"

private fun subtitle(data: VaultItemData): String = when (data.kind) {
    VAULT_KIND_LOGIN -> data.username.ifBlank { data.url.ifBlank { "未填写用户名" } }
    VAULT_KIND_SECRET -> if (data.secret.isNotEmpty()) "${data.secret.length} 个字符" else "未填写密钥"
    VAULT_KIND_SERVER -> {
        if (data.host.isBlank()) {
            "未填写主机"
        } else {
            val target = (if (data.username.isNotBlank()) "${data.username}@" else "") + data.host
            val port = if (data.port.isNotBlank() && data.port != "22") ":${
                data.port
            }" else ""
            "$target$port · ${if (data.authMethod == VAULT_AUTH_KEY) "私钥" else "密码"}"
        }
    }
    VAULT_KIND_SUBSCRIPTION -> {
        val providerLabel = VAULT_PROVIDER_LABELS[normalizeVaultProvider(data.provider)].orEmpty()
        val name = if (data.plan.isNotBlank()) "$providerLabel ${data.plan}" else providerLabel
        buildList {
            add(name)
            if (data.balance.isNotBlank()) add("余额 ${formatVaultMoney(data.currency, data.balance)}")
            if (data.expiresOn.isNotBlank()) add("${data.expiresOn} 到期")
        }.joinToString(" · ")
    }
    else -> {
        val remaining = data.codes.count { !it.used }
        (if (data.account.isNotBlank()) "${data.account} · " else "") + "剩余 $remaining / ${data.codes.size} 个可用"
    }
}

// 只按名称、用户名、网址、账号、套餐和备注搜索，不匹配密码和密钥本身。
private fun VaultItemData.matches(query: String): Boolean {
    if (query.isBlank()) return true
    val subscriptionBits = if (kind == VAULT_KIND_SUBSCRIPTION) {
        listOf(plan, provider, VAULT_PROVIDER_LABELS[provider].orEmpty())
    } else {
        emptyList()
    }
    val fields = if (kind == VAULT_KIND_SUBSCRIPTION) {
        listOf(title, notes, account) + subscriptionBits
    } else {
        listOf(title, notes, username, url, account, host, port)
    }
    val haystack = fields.joinToString(" ")
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
        topBar = {
            MemoTopBar(
                title = "密码库",
                subtitle = "端到端加密 · 服务器只保存密文",
                navigationIcon = {
                    IconButton(onClick = onClose) {
                        Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = "返回")
                    }
                },
            ) {
                if (state.phase == VaultPhase.UNLOCKED) {
                    TextButton(onClick = viewModel::lock) {
                        Icon(Icons.Outlined.Lock, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("锁定")
                    }
                }
            }
        },
        floatingActionButton = {
            if (state.phase == VaultPhase.UNLOCKED) {
                FloatingActionButton(
                    onClick = { choosingKind = true },
                    containerColor = DeepTeal,
                    contentColor = Color.White,
                    shape = RoundedCornerShape(18.dp),
                ) { Icon(Icons.Outlined.Add, contentDescription = "新建条目", modifier = Modifier.size(26.dp)) }
            }
        },
    ) { innerPadding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .imePadding(),
            contentPadding = PaddingValues(start = 16.dp, top = 4.dp, end = 16.dp, bottom = 104.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            when (state.phase) {
                VaultPhase.LOADING -> item {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 32.dp),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = DeepTeal)
                        Spacer(Modifier.width(10.dp))
                        Text("正在读取密码库……", color = TextMuted)
                    }
                }
                VaultPhase.ERROR -> item {
                    VaultGate(icon = Icons.Outlined.CloudOff, title = "暂时无法读取密码库") {
                        Text(state.error ?: "请检查网络后重试。", color = TextMuted, textAlign = TextAlign.Center)
                        OutlinedButton(onClick = viewModel::load, shape = RoundedCornerShape(12.dp)) { Text("重试") }
                    }
                }
                VaultPhase.NOT_CONFIGURED -> item {
                    VaultGate(icon = Icons.Outlined.Shield, title = "还没有密码库") {
                        Text(
                            "请先在 MemoIsle 网页端设置主密码。之后在手机上输入同一个主密码即可解锁使用。",
                            color = TextMuted,
                            textAlign = TextAlign.Center,
                        )
                    }
                }
                VaultPhase.LOCKED -> item {
                    var showPassword by remember { mutableStateOf(false) }
                    VaultGate(icon = Icons.Outlined.Lock, title = "密码库已锁定") {
                        Text(
                            "输入主密码解锁" + (if (state.itemCount > 0) "，共 ${state.itemCount} 条" else "") +
                                "。解锁在手机上完成，主密码不会发送到服务器。",
                            color = TextMuted,
                            style = MaterialTheme.typography.bodyMedium,
                            textAlign = TextAlign.Center,
                        )
                        OutlinedTextField(
                            value = password,
                            onValueChange = { password = it },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text("主密码") },
                            visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                            shape = RoundedCornerShape(12.dp),
                            trailingIcon = {
                                IconButton(onClick = { showPassword = !showPassword }) {
                                    Icon(
                                        if (showPassword) Icons.Outlined.VisibilityOff else Icons.Outlined.Visibility,
                                        contentDescription = if (showPassword) "隐藏主密码" else "显示主密码",
                                    )
                                }
                            },
                        )
                        Button(
                            onClick = {
                                viewModel.unlock(password)
                                password = ""
                            },
                            enabled = !state.busy && password.isNotEmpty(),
                            modifier = Modifier.fillMaxWidth().height(48.dp),
                            shape = RoundedCornerShape(14.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
                        ) {
                            if (state.busy) {
                                CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = Color.White)
                                Spacer(Modifier.width(8.dp))
                                Text("解锁中…")
                            } else {
                                Text("解锁", style = MaterialTheme.typography.titleSmall)
                            }
                        }
                        Text(
                            "忘记主密码、更改主密码和加密备份请在网页端操作。",
                            color = TextMuted,
                            style = MaterialTheme.typography.bodySmall,
                            textAlign = TextAlign.Center,
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
                            placeholder = { Text("按名称、用户名、网址或备注搜索") },
                            leadingIcon = { Icon(Icons.Outlined.Search, contentDescription = null, tint = TextMuted) },
                            trailingIcon = if (query.isNotEmpty()) {
                                {
                                    IconButton(onClick = { query = "" }) {
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
                    item {
                        KindFilters(
                            selected = filter,
                            entries = state.entries,
                            reminderCount = remindersByEntry.size,
                            onSelect = { filter = it },
                        )
                    }
                    if (state.brokenCount > 0) {
                        item {
                            InfoPill(
                                "有 ${state.brokenCount} 条无法解密，可能已损坏或被篡改，已跳过显示。",
                                color = DangerRed,
                                background = DangerSoft,
                                icon = Icons.Outlined.ErrorOutline,
                            )
                        }
                    }
                    if (state.entries.isEmpty()) {
                        item {
                            VaultGate(icon = Icons.Outlined.Key, title = "密码库还是空的") {
                                Text(
                                    "点右下角的 + 保存网站账号密码、API Key、服务器或两步验证的恢复码。",
                                    color = TextMuted,
                                    textAlign = TextAlign.Center,
                                )
                            }
                        }
                    } else if (visible.isEmpty()) {
                        item {
                            Text(
                                if (filter == FILTER_REMINDERS && query.isBlank()) "提醒都处理完了。" else "没有匹配的条目。",
                                color = TextMuted,
                                modifier = Modifier.fillMaxWidth().padding(vertical = 24.dp),
                                textAlign = TextAlign.Center,
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
            title = { Text("新建条目") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    listOf(
                        VAULT_KIND_LOGIN,
                        VAULT_KIND_SUBSCRIPTION,
                        VAULT_KIND_SECRET,
                        VAULT_KIND_SERVER,
                        VAULT_KIND_RECOVERY,
                    ).forEach { kind ->
                        val style = vaultKindStyle(kind)
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(12.dp))
                                .clickable {
                                    choosingKind = false
                                    editor = null to VaultItemData.empty(kind)
                                }
                                .padding(horizontal = 4.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            KindAvatar(style, size = 40.dp)
                            Spacer(Modifier.width(12.dp))
                            Column {
                                Text(style.label, style = MaterialTheme.typography.titleSmall)
                                Text(vaultKindHint(kind), color = TextMuted, style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
            },
            confirmButton = {},
            dismissButton = { TextButton(onClick = { choosingKind = false }) { Text("取消") } },
            containerColor = SurfaceWhite,
            shape = RoundedCornerShape(18.dp),
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

/** 密码库条目的图标和配色，列表、新建选择和编辑页共用。 */
internal fun vaultKindStyle(kind: String): MemoKindStyle = when (kind) {
    VAULT_KIND_SECRET -> MemoKindStyle(Icons.Outlined.Key, VAULT_KIND_LABELS.getValue(kind), WordAccent, WordSoft)
    VAULT_KIND_SERVER -> MemoKindStyle(Icons.Outlined.Dns, VAULT_KIND_LABELS.getValue(kind), IdeaAccent, IdeaSoft)
    VAULT_KIND_RECOVERY -> MemoKindStyle(Icons.Outlined.Pin, VAULT_KIND_LABELS.getValue(kind), ImageAccent, ImageSoft)
    VAULT_KIND_SUBSCRIPTION -> MemoKindStyle(
        Icons.Outlined.AutoAwesome,
        VAULT_KIND_LABELS.getValue(kind),
        Color(0xFF5B4B8A),
        Color(0xFFEEEAF6),
    )
    else -> MemoKindStyle(Icons.Outlined.Password, VAULT_KIND_LABELS.getValue(VAULT_KIND_LOGIN), DeepTeal, TealSoft)
}

private fun vaultKindHint(kind: String): String = when (kind) {
    VAULT_KIND_SECRET -> "API Key、SSH 私钥、令牌"
    VAULT_KIND_SERVER -> "主机、端口和登录方式"
    VAULT_KIND_RECOVERY -> "两步验证的备用恢复码"
    VAULT_KIND_SUBSCRIPTION -> "Claude、ChatGPT、Grok 订阅"
    else -> "网站或应用的用户名和密码"
}

/** 锁定、未设置、出错等状态的居中卡片。 */
@Composable
private fun VaultGate(
    icon: ImageVector,
    title: String,
    content: @Composable ColumnScope.() -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = BorderStroke(1.dp, Border),
        shape = RoundedCornerShape(20.dp),
    ) {
        Column(
            Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Box(
                modifier = Modifier.size(56.dp).background(TealSoft, CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Icon(icon, contentDescription = null, tint = DeepTeal, modifier = Modifier.size(28.dp))
            }
            Text(title, style = MaterialTheme.typography.titleMedium)
            content()
        }
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
        shape = RoundedCornerShape(18.dp),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Outlined.NotificationsActive, contentDescription = null, tint = DangerRed, modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text("密码提醒", style = MaterialTheme.typography.titleSmall)
                Spacer(Modifier.width(8.dp))
                Text("$entryCount 条需要处理", color = TextMuted, style = MaterialTheme.typography.bodySmall)
            }
            reminders.take(REMINDER_PREVIEW_LIMIT).forEach { reminder ->
                // 名称在前、标签在后，与条目列表一致；标签宽度不同时名称仍左对齐。
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(10.dp))
                        .clickable { onOpen(reminder) }
                        .padding(vertical = 4.dp),
                    verticalArrangement = Arrangement.spacedBy(2.dp),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(
                            reminder.title,
                            modifier = Modifier.weight(1f, fill = false),
                            style = MaterialTheme.typography.titleSmall,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        ReminderBadge(reminder)
                    }
                    Text(reminder.message, color = TextMuted, style = MaterialTheme.typography.bodySmall)
                }
            }
            if (reminders.size > REMINDER_PREVIEW_LIMIT) {
                TextButton(onClick = onShowAll) { Text("查看全部 ${reminders.size} 项提醒") }
            }
        }
    }
}

@Composable
private fun KindFilters(
    selected: String,
    entries: List<VaultEntry>,
    reminderCount: Int,
    onSelect: (String) -> Unit,
) {
    val options = buildList {
        add(FILTER_ALL to "全部 ${entries.size}")
        listOf(
            VAULT_KIND_LOGIN,
            VAULT_KIND_SUBSCRIPTION,
            VAULT_KIND_SECRET,
            VAULT_KIND_SERVER,
            VAULT_KIND_RECOVERY,
        ).forEach { kind ->
            add(kind to "${VAULT_KIND_LABELS.getValue(kind)} ${entries.count { it.data.kind == kind }}")
        }
        // 没有提醒时不显示；正在看这一栏时保留，避免按钮突然消失。
        if (reminderCount > 0 || selected == FILTER_REMINDERS) add(FILTER_REMINDERS to "需处理 $reminderCount")
    }
    Row(
        modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        options.forEach { (value, label) ->
            MemoFilterChip(
                label = label,
                selected = selected == value,
                onClick = { onSelect(value) },
                leadingIcon = when (value) {
                    FILTER_ALL -> null
                    FILTER_REMINDERS -> Icons.Outlined.NotificationsActive
                    else -> vaultKindStyle(value).icon
                },
            )
        }
    }
}

/** 条目卡片上的复制按钮：小号描边按钮，带复制图标。 */
@Composable
private fun CopyButton(label: String, enabled: Boolean, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        shape = RoundedCornerShape(10.dp),
        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp),
        modifier = Modifier.height(36.dp),
    ) {
        Icon(Icons.Outlined.ContentCopy, contentDescription = null, modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(6.dp))
        Text(label, style = MaterialTheme.typography.labelLarge)
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
    val style = vaultKindStyle(data.kind)
    Card(
        modifier = Modifier.fillMaxWidth(),
        onClick = onOpen,
        colors = CardDefaults.cardColors(containerColor = SurfaceWhite),
        border = BorderStroke(1.dp, Border),
        shape = RoundedCornerShape(16.dp),
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                if (data.kind == VAULT_KIND_SUBSCRIPTION) {
                    val letter = if (normalizeVaultProvider(data.provider) == VAULT_PROVIDER_OTHER) {
                        "AI"
                    } else {
                        VAULT_PROVIDER_LABELS.getValue(normalizeVaultProvider(data.provider)).take(1)
                    }
                    Box(
                        modifier = Modifier
                            .size(40.dp)
                            .background(style.soft, RoundedCornerShape(12.dp)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Text(letter, color = style.accent, fontWeight = FontWeight.Bold)
                    }
                } else {
                    KindAvatar(style)
                }
                Column(Modifier.weight(1f)) {
                    FlowRow(
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Text(data.title, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        reminders.forEach { ReminderBadge(it) }
                    }
                    Text(
                        text = if (showReminderText && reminders.isNotEmpty()) {
                            reminders.joinToString(" ") { it.message }
                        } else {
                            "${style.label} · ${subtitle(data)}"
                        },
                        color = TextMuted,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                when (data.kind) {
                    VAULT_KIND_LOGIN -> {
                        CopyButton("用户名", data.username.isNotEmpty()) { onCopy(data.username, "用户名") }
                        CopyButton("密码", data.password.isNotEmpty()) { onCopy(data.password, "密码") }
                    }
                    VAULT_KIND_SECRET -> CopyButton("密钥", data.secret.isNotEmpty()) { onCopy(data.secret, "密钥") }
                    // 与 Web 端一致：主机、密码或私钥，以及可直接粘贴到终端的 ssh 命令。
                    VAULT_KIND_SERVER -> {
                        val useKey = data.authMethod == VAULT_AUTH_KEY
                        val credential = if (useKey) data.privateKey else data.password
                        CopyButton("主机", data.host.isNotEmpty()) { onCopy(data.host, "主机") }
                        CopyButton(if (useKey) "私钥" else "密码", credential.isNotEmpty()) {
                            onCopy(credential, if (useKey) "私钥" else "密码")
                        }
                        CopyButton("ssh", data.host.isNotEmpty()) {
                            val port = if (data.port.isNotBlank() && data.port != "22") " -p ${data.port}" else ""
                            val user = if (data.username.isNotBlank()) "${data.username}@" else ""
                            onCopy("ssh$port $user${data.host}", "ssh 命令")
                        }
                    }
                    VAULT_KIND_SUBSCRIPTION -> {
                        CopyButton("账号", data.account.isNotEmpty()) { onCopy(data.account, "账号") }
                    }
                    else -> CopyButton(
                        if (nextCode != null) "未用的恢复码" else "恢复码已用完",
                        nextCode != null,
                    ) { nextCode?.let { onCopy(it.code, "恢复码") } }
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
    val startedInvalid = draft.kind == VAULT_KIND_SUBSCRIPTION &&
        draft.startedOn.isNotBlank() &&
        normalizeVaultDate(draft.startedOn).isEmpty()
    val priceInvalid = draft.kind == VAULT_KIND_SUBSCRIPTION &&
        draft.price.isNotBlank() &&
        normalizeVaultMoney(draft.price).isEmpty()
    val balanceInvalid = draft.kind == VAULT_KIND_SUBSCRIPTION &&
        draft.balance.isNotBlank() &&
        normalizeVaultMoney(draft.balance).isEmpty()
    val currencyInvalid = draft.kind == VAULT_KIND_SUBSCRIPTION &&
        draft.currency.isNotBlank() &&
        !Regex("^[A-Z]{3}$").matches(draft.currency)
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

    DetailScreen(
        kind = vaultKindStyle(draft.kind),
        onClose = ::requestDismiss,
        closeEnabled = !busy,
        bottomBar = {
            if (!isNew) {
                TextButton(
                    onClick = { confirmDelete = true },
                    enabled = !busy,
                    colors = ButtonDefaults.textButtonColors(contentColor = DangerRed),
                ) {
                    Icon(Icons.Outlined.DeleteOutline, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(6.dp))
                    Text("删除")
                }
            }
            Spacer(Modifier.weight(1f))
            Button(
                onClick = {
                    val title = draft.title.trim().ifBlank {
                        if (draft.kind == VAULT_KIND_SUBSCRIPTION) {
                            defaultSubscriptionTitle(draft.provider, draft.plan)
                        } else {
                            draft.title.trim()
                        }
                    }
                    onSave(
                        draft.copy(
                            title = title,
                            currency = if (draft.kind == VAULT_KIND_SUBSCRIPTION && draft.currency.isBlank()) {
                                VAULT_CURRENCY_USD
                            } else {
                                draft.currency
                            },
                        ),
                    )
                },
                enabled = !busy &&
                    (draft.title.isNotBlank() || draft.kind == VAULT_KIND_SUBSCRIPTION) &&
                    !expiryInvalid &&
                    !startedInvalid &&
                    !priceInvalid &&
                    !balanceInvalid &&
                    !currencyInvalid &&
                    (dirty || isNew),
                modifier = Modifier.height(48.dp),
                shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
            ) { Text(if (busy) "加密保存中…" else "保存", style = MaterialTheme.typography.titleSmall) }
        },
    ) {
                Text(
                    if (isNew) "新建${VAULT_KIND_LABELS.getValue(draft.kind)}" else draft.title.ifBlank { "未命名" },
                    style = MaterialTheme.typography.headlineSmall,
                )
                reminders.forEach { reminder ->
                    val tone = if (reminder.danger) DangerRed else WarmAmberText
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(if (reminder.danger) DangerSoft else WarmAmberSoft, RoundedCornerShape(12.dp))
                            .padding(12.dp),
                        verticalAlignment = Alignment.Top,
                    ) {
                        Icon(Icons.Outlined.NotificationsActive, contentDescription = null, tint = tone, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(8.dp))
                        Column {
                            Text(reminder.type.label, style = MaterialTheme.typography.titleSmall, color = tone)
                            Text(reminder.message, color = tone, style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
                if (draft.kind == VAULT_KIND_SUBSCRIPTION) {
                    Text("服务商", style = MaterialTheme.typography.labelMedium)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        VAULT_PROVIDER_OPTIONS.forEach { provider ->
                            MemoFilterChip(
                                label = VAULT_PROVIDER_LABELS.getValue(provider),
                                selected = draft.provider == provider,
                                onClick = {
                                    val previousTitle = defaultSubscriptionTitle(draft.provider, draft.plan)
                                    val title = if (draft.title.isBlank() || draft.title == previousTitle) {
                                        defaultSubscriptionTitle(provider, draft.plan)
                                    } else {
                                        draft.title
                                    }
                                    update(draft.copy(provider = provider, title = title))
                                },
                            )
                        }
                    }
                    OutlinedTextField(
                        value = draft.plan,
                        onValueChange = { plan ->
                            val previousTitle = defaultSubscriptionTitle(draft.provider, draft.plan)
                            val title = if (draft.title.isBlank() || draft.title == previousTitle) {
                                defaultSubscriptionTitle(draft.provider, plan)
                            } else {
                                draft.title
                            }
                            update(draft.copy(plan = plan.take(80), title = title))
                        },
                        modifier = Modifier.fillMaxWidth(),
                        singleLine = true,
                        label = { Text("套餐") },
                        placeholder = { Text("如 Pro、Max、Plus、SuperGrok") },
                    )
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
                            trailingIcon = {
                                IconButton(onClick = { onCopy(draft.username, "用户名") }, enabled = draft.username.isNotEmpty()) {
                                    Icon(Icons.Outlined.ContentCopy, contentDescription = "复制用户名", modifier = Modifier.size(18.dp))
                                }
                            },
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
                            FieldAction(if (secretVisible) Icons.Outlined.VisibilityOff else Icons.Outlined.Visibility, if (secretVisible) "隐藏" else "显示") { secretVisible = !secretVisible }
                            FieldAction(Icons.Outlined.AutoAwesome, "生成") { update(draft.copy(password = generateVaultPassword())) }
                            FieldAction(Icons.Outlined.ContentCopy, "复制", enabled = draft.password.isNotEmpty()) { onCopy(draft.password, "密码") }
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
                            FieldAction(if (secretVisible) Icons.Outlined.VisibilityOff else Icons.Outlined.Visibility, if (secretVisible) "隐藏" else "显示") { secretVisible = !secretVisible }
                            FieldAction(Icons.Outlined.ContentCopy, "复制", enabled = draft.secret.isNotEmpty()) { onCopy(draft.secret, "密钥") }
                        }
                    }
                    VAULT_KIND_SERVER -> {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedTextField(
                                value = draft.host,
                                onValueChange = { update(draft.copy(host = it)) },
                                modifier = Modifier.weight(1f),
                                singleLine = true,
                                label = { Text("主机") },
                                placeholder = { Text("203.0.113.10") },
                            )
                            OutlinedTextField(
                                value = draft.port,
                                onValueChange = { value ->
                                    update(draft.copy(port = value.filter { it.isDigit() }.take(5)))
                                },
                                modifier = Modifier.width(110.dp),
                                singleLine = true,
                                label = { Text("端口") },
                                placeholder = { Text("22") },
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            )
                        }
                        OutlinedTextField(
                            value = draft.username,
                            onValueChange = { update(draft.copy(username = it)) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text("登录用户") },
                            placeholder = { Text("root") },
                            trailingIcon = {
                                IconButton(onClick = { onCopy(draft.username, "用户名") }, enabled = draft.username.isNotEmpty()) {
                                    Icon(Icons.Outlined.ContentCopy, contentDescription = "复制用户名", modifier = Modifier.size(18.dp))
                                }
                            },
                        )
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            MemoFilterChip(
                                label = "密码",
                                selected = draft.authMethod == VAULT_AUTH_PASSWORD,
                                onClick = { update(draft.copy(authMethod = VAULT_AUTH_PASSWORD)) },
                            )
                            MemoFilterChip(
                                label = "SSH 私钥",
                                selected = draft.authMethod == VAULT_AUTH_KEY,
                                onClick = { update(draft.copy(authMethod = VAULT_AUTH_KEY)) },
                            )
                        }
                        if (draft.authMethod == VAULT_AUTH_KEY) {
                            OutlinedTextField(
                                value = draft.privateKey,
                                onValueChange = { update(draft.copy(privateKey = it)) },
                                modifier = Modifier.fillMaxWidth(),
                                minLines = if (secretVisible) 4 else 1,
                                label = { Text("SSH 私钥") },
                                textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                                visualTransformation = if (secretVisible) VisualTransformation.None else PasswordVisualTransformation(),
                            )
                            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                FieldAction(if (secretVisible) Icons.Outlined.VisibilityOff else Icons.Outlined.Visibility, if (secretVisible) "隐藏" else "显示") { secretVisible = !secretVisible }
                                FieldAction(Icons.Outlined.ContentCopy, "复制", enabled = draft.privateKey.isNotEmpty()) { onCopy(draft.privateKey, "私钥") }
                            }
                            OutlinedTextField(
                                value = draft.keyPassphrase,
                                onValueChange = { update(draft.copy(keyPassphrase = it)) },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                label = { Text("私钥口令（可选）") },
                                textStyle = MaterialTheme.typography.bodyLarge.copy(fontFamily = FontFamily.Monospace),
                                visualTransformation = if (secretVisible) VisualTransformation.None else PasswordVisualTransformation(),
                            )
                        } else {
                            OutlinedTextField(
                                value = draft.password,
                                onValueChange = { update(draft.copy(password = it)) },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                label = { Text("登录密码") },
                                textStyle = MaterialTheme.typography.bodyLarge.copy(fontFamily = FontFamily.Monospace),
                                visualTransformation = if (secretVisible) VisualTransformation.None else PasswordVisualTransformation(),
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                            )
                            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                FieldAction(if (secretVisible) Icons.Outlined.VisibilityOff else Icons.Outlined.Visibility, if (secretVisible) "隐藏" else "显示") { secretVisible = !secretVisible }
                                FieldAction(Icons.Outlined.AutoAwesome, "生成") { update(draft.copy(password = generateVaultPassword())) }
                                FieldAction(Icons.Outlined.ContentCopy, "复制", enabled = draft.password.isNotEmpty()) { onCopy(draft.password, "密码") }
                            }
                        }
                    }
                    VAULT_KIND_SUBSCRIPTION -> {
                        OutlinedTextField(
                            value = draft.account,
                            onValueChange = { update(draft.copy(account = it)) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text("订阅账号") },
                            trailingIcon = {
                                IconButton(onClick = { onCopy(draft.account, "账号") }, enabled = draft.account.isNotEmpty()) {
                                    Icon(Icons.Outlined.ContentCopy, contentDescription = "复制账号", modifier = Modifier.size(18.dp))
                                }
                            },
                        )
                        OutlinedTextField(
                            value = draft.startedOn,
                            onValueChange = { update(draft.copy(startedOn = it.trim().take(10))) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text("订阅开始日期") },
                            placeholder = { Text("例如 2026-01-15") },
                            isError = startedInvalid,
                            supportingText = {
                                Text(if (startedInvalid) "请按 年-月-日 填写，例如 2026-01-15" else "留空表示不记录开始日期")
                            },
                        )
                        OutlinedTextField(
                            value = draft.expiresOn,
                            onValueChange = { update(draft.copy(expiresOn = it.trim().take(10))) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text("到期 / 续费日期") },
                            placeholder = { Text("例如 2026-11-30") },
                            isError = expiryInvalid,
                            supportingText = {
                                Text(
                                    when {
                                        expiryInvalid -> "请按 年-月-日 填写，例如 2026-11-30"
                                        expiresIn == null -> "留空表示不提醒到期"
                                        expiresIn < 0 -> "已过期 ${-expiresIn} 天"
                                        expiresIn == 0L -> "今天到期"
                                        else -> "还有 $expiresIn 天到期，到期前 14 天开始提醒"
                                    },
                                )
                            },
                        )
                        Text("计费周期", style = MaterialTheme.typography.labelMedium)
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            VAULT_BILLING_OPTIONS.forEach { cycle ->
                                MemoFilterChip(
                                    label = VAULT_BILLING_LABELS.getValue(cycle),
                                    selected = draft.billingCycle == cycle,
                                    onClick = { update(draft.copy(billingCycle = cycle)) },
                                )
                            }
                        }
                        OutlinedTextField(
                            value = draft.price,
                            onValueChange = { update(draft.copy(price = it.trim().take(12))) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text("每期费用") },
                            placeholder = { Text("如 20 或 20.00") },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                            isError = priceInvalid,
                            supportingText = {
                                if (priceInvalid) Text("只接受最多 9 位整数、2 位小数的非负数")
                            },
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.Top) {
                            OutlinedTextField(
                                value = draft.balance,
                                onValueChange = { update(draft.copy(balance = it.trim().take(12))) },
                                modifier = Modifier.weight(1f),
                                singleLine = true,
                                label = { Text("账户余额") },
                                placeholder = { Text("如 12.50") },
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                                isError = balanceInvalid,
                                supportingText = {
                                    if (balanceInvalid) Text("只接受最多 9 位整数、2 位小数的非负数")
                                },
                            )
                            OutlinedTextField(
                                value = draft.currency,
                                onValueChange = { value ->
                                    update(draft.copy(currency = value.filter { it.isLetter() }.uppercase().take(3)))
                                },
                                modifier = Modifier.width(110.dp),
                                singleLine = true,
                                label = { Text("币种") },
                                placeholder = { Text("USD") },
                                isError = currencyInvalid,
                                supportingText = {
                                    Text(
                                        when {
                                            currencyInvalid -> "须为 3 位字母，例如 USD"
                                            draft.currency.isBlank() -> "留空则保存为 USD"
                                            else -> ""
                                        },
                                    )
                                },
                            )
                        }
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            MemoFilterChip(
                                label = "USD $",
                                selected = draft.currency == VAULT_CURRENCY_USD,
                                onClick = { update(draft.copy(currency = VAULT_CURRENCY_USD)) },
                            )
                            MemoFilterChip(
                                label = "CNY ¥",
                                selected = draft.currency == VAULT_CURRENCY_CNY,
                                onClick = { update(draft.copy(currency = VAULT_CURRENCY_CNY)) },
                            )
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
                        FieldAction(Icons.Outlined.Add, "添加恢复码", enabled = pastedCodes.isNotBlank()) {
                            update(draft.copy(codes = parseRecoveryCodes(pastedCodes, draft.codes)))
                            pastedCodes = ""
                        }
                    }
                }
                if (draft.kind == VAULT_KIND_LOGIN ||
                    draft.kind == VAULT_KIND_SECRET ||
                    draft.kind == VAULT_KIND_SERVER
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .background(SurfaceSubtle, RoundedCornerShape(12.dp))
                            .padding(12.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text("提醒", style = MaterialTheme.typography.titleSmall)
                        Text(
                            "${
                                when (draft.kind) {
                                    VAULT_KIND_LOGIN -> "密码"
                                    VAULT_KIND_SERVER -> "登录凭据"
                                    else -> "密钥"
                                }
                            }上次更换：$changedLabel",
                            color = TextMuted,
                            style = MaterialTheme.typography.bodySmall,
                        )
                        Text("定期更换", style = MaterialTheme.typography.labelMedium)
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            VAULT_ROTATE_OPTIONS.forEach { days ->
                                MemoFilterChip(
                                    label = rotateLabel(days),
                                    selected = draft.rotateDays == days,
                                    onClick = { update(draft.copy(rotateDays = days)) },
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
            .background(SurfaceSubtle, RoundedCornerShape(12.dp))
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
        IconButton(onClick = onCopy, enabled = !code.used) {
            Icon(Icons.Outlined.ContentCopy, contentDescription = "复制恢复码", modifier = Modifier.size(18.dp))
        }
        IconButton(onClick = onRemove) {
            Icon(Icons.Outlined.Close, contentDescription = "删除这个恢复码", tint = DangerRed, modifier = Modifier.size(18.dp))
        }
    }
}

/** 字段下方的小操作：显示、生成、复制等，带图标的浅色按钮。 */
@Composable
private fun FieldAction(
    icon: ImageVector,
    label: String,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    FilledTonalButton(
        onClick = onClick,
        enabled = enabled,
        shape = RoundedCornerShape(10.dp),
        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 6.dp),
        colors = ButtonDefaults.filledTonalButtonColors(containerColor = SurfaceSubtle, contentColor = TextStrong),
    ) {
        Icon(icon, contentDescription = null, modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(6.dp))
        Text(label, style = MaterialTheme.typography.labelLarge)
    }
}
