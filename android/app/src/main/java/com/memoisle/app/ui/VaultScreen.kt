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
import androidx.annotation.StringRes
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
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
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
import com.memoisle.app.R
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
import com.memoisle.app.data.credentialIdentity
import com.memoisle.app.data.daysSince
import com.memoisle.app.data.defaultSubscriptionTitle
import com.memoisle.app.data.effectiveSecret
import com.memoisle.app.data.formatVaultMoney
import com.memoisle.app.data.generateVaultPassword
import com.memoisle.app.data.isWeakVaultPassword
import com.memoisle.app.data.lastChangedAt
import com.memoisle.app.data.normalizeVaultDate
import com.memoisle.app.data.normalizeVaultMoney
import com.memoisle.app.data.normalizeVaultProvider
import com.memoisle.app.data.parseRecoveryCodes
import com.memoisle.app.data.resolvePrivateKey
import com.memoisle.app.data.serversReferencingKey
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

@Composable
private fun subtitle(data: VaultItemData, entries: List<VaultEntry>): String = when (data.kind) {
    VAULT_KIND_LOGIN -> data.username.ifBlank { data.url.ifBlank { stringResource(R.string.vault_no_username) } }
    VAULT_KIND_SECRET -> if (data.secret.isNotEmpty()) {
        pluralStringResource(R.plurals.vault_secret_chars, data.secret.length, data.secret.length)
    } else {
        stringResource(R.string.vault_no_secret)
    }
    VAULT_KIND_SERVER -> {
        if (data.host.isBlank()) {
            stringResource(R.string.vault_no_host)
        } else {
            val target = (if (data.username.isNotBlank()) "${data.username}@" else "") + data.host
            val port = if (data.port.isNotBlank() && data.port != "22") ":${
                data.port
            }" else ""
            "$target$port · ${serverCredentialLabel(data, entries)}"
        }
    }
    VAULT_KIND_SUBSCRIPTION -> {
        val providerLabel = stringResource(VAULT_PROVIDER_LABELS.getValue(normalizeVaultProvider(data.provider)))
        val name = if (data.plan.isNotBlank()) "$providerLabel ${data.plan}" else providerLabel
        buildList {
            add(name)
            if (data.balance.isNotBlank()) add(stringResource(R.string.vault_balance_value, formatVaultMoney(data.currency, data.balance)))
            if (data.expiresOn.isNotBlank()) add(stringResource(R.string.vault_expires_on, data.expiresOn))
        }.joinToString(" · ")
    }
    else -> {
        val remaining = data.codes.count { !it.used }
        (if (data.account.isNotBlank()) "${data.account} · " else "") +
            stringResource(R.string.vault_codes_remaining, remaining, data.codes.size)
    }
}

@Composable
private fun serverCredentialLabel(data: VaultItemData, entries: List<VaultEntry>): String {
    if (data.authMethod != VAULT_AUTH_KEY) return stringResource(R.string.auth_password_label)
    if (data.privateKeyRef.isEmpty()) return stringResource(R.string.vault_private_key)
    val resolved = data.resolvePrivateKey(entries)
    return if (resolved.missing) {
        stringResource(R.string.vault_private_key_ref_missing)
    } else {
        stringResource(R.string.vault_private_key_ref, resolved.refTitle)
    }
}

// 只按名称、用户名、网址、账号、套餐和备注搜索，不匹配密码和密钥本身。
private fun VaultItemData.matches(query: String): Boolean {
    if (query.isBlank()) return true
    val subscriptionBits = if (kind == VAULT_KIND_SUBSCRIPTION) {
        listOf(plan, provider, defaultSubscriptionTitle(provider, ""))
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
    val resources = LocalResources.current
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
        snackbarHostState.showSnackbar(text.resolve(resources))
        viewModel.clearMessage()
    }

    fun copy(value: String, @StringRes label: Int) {
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
        viewModel.showMessage(UiText.res(R.string.vault_copied, UiText.res(label), CLIPBOARD_CLEAR_MS / 1000))
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
                title = stringResource(R.string.home_nav_vault),
                subtitle = stringResource(R.string.vault_subtitle),
                navigationIcon = {
                    IconButton(onClick = onClose) {
                        Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = stringResource(R.string.common_back))
                    }
                },
            ) {
                if (state.phase == VaultPhase.UNLOCKED) {
                    TextButton(onClick = viewModel::lock) {
                        Icon(Icons.Outlined.Lock, contentDescription = null, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.vault_lock))
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
                ) { Icon(Icons.Outlined.Add, contentDescription = stringResource(R.string.vault_new_entry), modifier = Modifier.size(26.dp)) }
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
                        Text(stringResource(R.string.vault_loading), color = TextMuted)
                    }
                }
                VaultPhase.ERROR -> item {
                    VaultGate(icon = Icons.Outlined.CloudOff, title = stringResource(R.string.vault_load_failed)) {
                        Text(state.error?.asString() ?: stringResource(R.string.vault_check_network), color = TextMuted, textAlign = TextAlign.Center)
                        OutlinedButton(onClick = viewModel::load, shape = RoundedCornerShape(12.dp)) { Text(stringResource(R.string.update_retry)) }
                    }
                }
                VaultPhase.IP_BLOCKED -> item {
                    VaultGate(icon = Icons.Outlined.Shield, title = stringResource(R.string.vault_ip_blocked_title)) {
                        Text(
                            state.error?.asString() ?: stringResource(R.string.vault_ip_blocked_hint),
                            color = TextMuted,
                            textAlign = TextAlign.Center,
                        )
                        OutlinedButton(onClick = viewModel::load, shape = RoundedCornerShape(12.dp)) { Text(stringResource(R.string.update_retry)) }
                    }
                }
                VaultPhase.STEP_UP -> item {
                    var code by remember { mutableStateOf("") }
                    var useTotp by remember { mutableStateOf(false) }
                    VaultGate(icon = Icons.Outlined.Pin, title = stringResource(R.string.vault_step_up_title)) {
                        Text(
                            pluralStringResource(R.plurals.vault_step_up_hint, state.accessHours, state.accessHours),
                            color = TextMuted,
                            style = MaterialTheme.typography.bodyMedium,
                            textAlign = TextAlign.Center,
                        )
                        if (state.totpEnabled) {
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                OutlinedButton(
                                    onClick = { useTotp = false },
                                    shape = RoundedCornerShape(12.dp),
                                ) { Text(if (!useTotp) stringResource(R.string.vault_email_code_current) else stringResource(R.string.auth_code_label)) }
                                OutlinedButton(
                                    onClick = { useTotp = true },
                                    shape = RoundedCornerShape(12.dp),
                                ) { Text(if (useTotp) stringResource(R.string.vault_authenticator_current) else stringResource(R.string.vault_authenticator)) }
                            }
                        }
                        if (!useTotp) {
                            OutlinedButton(
                                onClick = viewModel::requestAccessCode,
                                enabled = !state.busy,
                                shape = RoundedCornerShape(12.dp),
                            ) { Text(if (state.busy) stringResource(R.string.relay_ui_sending) else stringResource(R.string.auth_send_code)) }
                        }
                        OutlinedTextField(
                            value = code,
                            onValueChange = { code = it },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text(if (useTotp) stringResource(R.string.vault_totp_code) else stringResource(R.string.vault_code)) },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            shape = RoundedCornerShape(12.dp),
                        )
                        Button(
                            onClick = {
                                viewModel.submitAccessCode(code, useTotp && state.totpEnabled)
                                code = ""
                            },
                            enabled = !state.busy && code.trim().length >= 6,
                            modifier = Modifier.fillMaxWidth().height(48.dp),
                            shape = RoundedCornerShape(14.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
                        ) { Text(if (state.busy) stringResource(R.string.vault_verifying) else stringResource(R.string.vault_verify)) }
                    }
                }
                VaultPhase.NOT_CONFIGURED -> item {
                    VaultGate(icon = Icons.Outlined.Shield, title = stringResource(R.string.vault_not_set_up)) {
                        Text(
                            stringResource(R.string.vault_setup_on_web),
                            color = TextMuted,
                            textAlign = TextAlign.Center,
                        )
                    }
                }
                VaultPhase.LOCKED -> item {
                    var showPassword by remember { mutableStateOf(false) }
                    VaultGate(icon = Icons.Outlined.Lock, title = stringResource(R.string.vault_locked)) {
                        Text(
                            if (state.itemCount > 0) {
                                pluralStringResource(R.plurals.vault_unlock_hint_count, state.itemCount, state.itemCount)
                            } else {
                                stringResource(R.string.vault_unlock_hint)
                            },
                            color = TextMuted,
                            style = MaterialTheme.typography.bodyMedium,
                            textAlign = TextAlign.Center,
                        )
                        OutlinedTextField(
                            value = password,
                            onValueChange = { password = it },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text(stringResource(R.string.vault_master_password)) },
                            visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                            shape = RoundedCornerShape(12.dp),
                            trailingIcon = {
                                IconButton(onClick = { showPassword = !showPassword }) {
                                    Icon(
                                        if (showPassword) Icons.Outlined.VisibilityOff else Icons.Outlined.Visibility,
                                        contentDescription = if (showPassword) stringResource(R.string.vault_hide_master) else stringResource(R.string.vault_show_master),
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
                                Text(stringResource(R.string.vault_unlocking))
                            } else {
                                Text(stringResource(R.string.vault_unlock), style = MaterialTheme.typography.titleSmall)
                            }
                        }
                        Text(
                            stringResource(R.string.vault_manage_on_web),
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
                            placeholder = { Text(stringResource(R.string.vault_search_placeholder)) },
                            leadingIcon = { Icon(Icons.Outlined.Search, contentDescription = null, tint = TextMuted) },
                            trailingIcon = if (query.isNotEmpty()) {
                                {
                                    IconButton(onClick = { query = "" }) {
                                        Icon(Icons.Outlined.Close, contentDescription = stringResource(R.string.home_clear_search))
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
                                pluralStringResource(R.plurals.vault_broken_count, state.brokenCount, state.brokenCount),
                                color = DangerRed,
                                background = DangerSoft,
                                icon = Icons.Outlined.ErrorOutline,
                            )
                        }
                    }
                    if (state.entries.isEmpty()) {
                        item {
                            VaultGate(icon = Icons.Outlined.Key, title = stringResource(R.string.vault_empty)) {
                                Text(
                                    stringResource(R.string.vault_empty_hint),
                                    color = TextMuted,
                                    textAlign = TextAlign.Center,
                                )
                            }
                        }
                    } else if (visible.isEmpty()) {
                        item {
                            Text(
                                if (filter == FILTER_REMINDERS && query.isBlank()) stringResource(R.string.vault_reminders_done) else stringResource(R.string.vault_no_match),
                                color = TextMuted,
                                modifier = Modifier.fillMaxWidth().padding(vertical = 24.dp),
                                textAlign = TextAlign.Center,
                            )
                        }
                    }
                    items(visible, key = { it.id }) { entry ->
                        VaultRow(
                            entry = entry,
                            entries = state.entries,
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
            title = { Text(stringResource(R.string.vault_new_entry)) },
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
                                Text(stringResource(style.label), style = MaterialTheme.typography.titleSmall)
                                Text(stringResource(vaultKindHint(kind)), color = TextMuted, style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
            },
            confirmButton = {},
            dismissButton = { TextButton(onClick = { choosingKind = false }) { Text(stringResource(R.string.common_cancel)) } },
            containerColor = SurfaceWhite,
            shape = RoundedCornerShape(18.dp),
        )
    }

    editor?.let { (entry, initial) ->
        VaultItemEditor(
            entry = entry,
            initial = initial,
            entries = state.entries,
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

private fun vaultKindHint(kind: String): Int = when (kind) {
    VAULT_KIND_SECRET -> R.string.vault_hint_secret
    VAULT_KIND_SERVER -> R.string.vault_hint_server
    VAULT_KIND_RECOVERY -> R.string.vault_hint_recovery
    VAULT_KIND_SUBSCRIPTION -> R.string.vault_hint_subscription
    else -> R.string.vault_hint_login
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
        text = stringResource(reminder.type.label),
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
                Text(stringResource(R.string.vault_password_reminders), style = MaterialTheme.typography.titleSmall)
                Spacer(Modifier.width(8.dp))
                Text(pluralStringResource(R.plurals.vault_reminders_entry_count, entryCount, entryCount), color = TextMuted, style = MaterialTheme.typography.bodySmall)
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
                    Text(reminder.message.asString(), color = TextMuted, style = MaterialTheme.typography.bodySmall)
                }
            }
            if (reminders.size > REMINDER_PREVIEW_LIMIT) {
                TextButton(onClick = onShowAll) { Text(pluralStringResource(R.plurals.vault_view_all_reminders, reminders.size, reminders.size)) }
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
        add(FILTER_ALL to stringResource(R.string.vault_filter_count, stringResource(R.string.ledger_filter_all), entries.size))
        listOf(
            VAULT_KIND_LOGIN,
            VAULT_KIND_SUBSCRIPTION,
            VAULT_KIND_SECRET,
            VAULT_KIND_SERVER,
            VAULT_KIND_RECOVERY,
        ).forEach { kind ->
            add(
                kind to stringResource(
                    R.string.vault_filter_count,
                    stringResource(VAULT_KIND_LABELS.getValue(kind)),
                    entries.count { it.data.kind == kind },
                ),
            )
        }
        // 没有提醒时不显示；正在看这一栏时保留，避免按钮突然消失。
        if (reminderCount > 0 || selected == FILTER_REMINDERS) add(
            FILTER_REMINDERS to stringResource(
                R.string.vault_filter_count,
                stringResource(R.string.vault_filter_needs_action),
                reminderCount,
            ),
        )
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
    entries: List<VaultEntry>,
    reminders: List<VaultReminder>,
    showReminderText: Boolean,
    onOpen: () -> Unit,
    onCopy: (String, Int) -> Unit,
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
                        stringResource(VAULT_PROVIDER_LABELS.getValue(normalizeVaultProvider(data.provider))).take(1)
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
                            reminders.map { it.message.asString() }.joinToString(" ")
                        } else {
                            "${stringResource(style.label)} · ${subtitle(data, entries)}"
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
                        CopyButton(stringResource(R.string.vault_field_username), data.username.isNotEmpty()) { onCopy(data.username, R.string.vault_field_username) }
                        CopyButton(stringResource(R.string.auth_password_label), data.password.isNotEmpty()) { onCopy(data.password, R.string.auth_password_label) }
                    }
                    VAULT_KIND_SECRET -> CopyButton(stringResource(R.string.vault_kind_secret), data.secret.isNotEmpty()) { onCopy(data.secret, R.string.vault_kind_secret) }
                    // 与 Web 端一致：主机、密码或私钥，以及可直接粘贴到终端的 ssh 命令。
                    VAULT_KIND_SERVER -> {
                        val useKey = data.authMethod == VAULT_AUTH_KEY
                        val credential = if (useKey) data.resolvePrivateKey(entries).value else data.password
                        CopyButton(stringResource(R.string.vault_field_host), data.host.isNotEmpty()) { onCopy(data.host, R.string.vault_field_host) }
                        CopyButton(if (useKey) stringResource(R.string.vault_private_key) else stringResource(R.string.auth_password_label), credential.isNotEmpty()) {
                            onCopy(credential, if (useKey) R.string.vault_private_key else R.string.auth_password_label)
                        }
                        CopyButton("ssh", data.host.isNotEmpty()) {
                            val port = if (data.port.isNotBlank() && data.port != "22") " -p ${data.port}" else ""
                            val user = if (data.username.isNotBlank()) "${data.username}@" else ""
                            onCopy("ssh$port $user${data.host}", R.string.vault_copy_ssh_command)
                        }
                    }
                    VAULT_KIND_SUBSCRIPTION -> {
                        CopyButton(stringResource(R.string.vault_field_account), data.account.isNotEmpty()) { onCopy(data.account, R.string.vault_field_account) }
                    }
                    else -> CopyButton(
                        if (nextCode != null) stringResource(R.string.vault_unused_code) else stringResource(R.string.vault_codes_used_up),
                        nextCode != null,
                    ) { nextCode?.let { onCopy(it.code, R.string.vault_kind_recovery) } }
                }
            }
        }
    }
}

@Composable
private fun rotateLabel(days: Int): String = when (days) {
    0 -> stringResource(R.string.vault_rotate_none)
    365 -> stringResource(R.string.vault_billing_yearly)
    else -> pluralStringResource(R.plurals.vault_rotate_every, days, days)
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun VaultItemEditor(
    entry: VaultEntry?,
    initial: VaultItemData,
    entries: List<VaultEntry>,
    reminders: List<VaultReminder>,
    busy: Boolean,
    onTouch: () -> Unit,
    onCopy: (String, Int) -> Unit,
    onDismiss: () -> Unit,
    onSave: (VaultItemData) -> Unit,
    onDelete: () -> Unit,
) {
    var draft by remember(initial) { mutableStateOf(initial) }
    var secretVisible by remember { mutableStateOf(false) }
    var pastedCodes by remember { mutableStateOf("") }
    var confirmDiscard by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    var useKeyRef by remember(initial) { mutableStateOf(initial.privateKeyRef.isNotEmpty()) }
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
    val needsKeySelection = draft.kind == VAULT_KIND_SERVER &&
        draft.authMethod == VAULT_AUTH_KEY &&
        useKeyRef &&
        draft.privateKeyRef.isEmpty()
    val secretChanged = draft.credentialIdentity().isNotEmpty() && draft.credentialIdentity() != initial.credentialIdentity()
    val changedLabel = when {
        secretChanged -> stringResource(R.string.vault_changed_on_save)
        entry == null || entry.data.effectiveSecret(entries).isEmpty() -> stringResource(R.string.vault_changed_never)
        else -> {
            val iso = lastChangedAt(entry, entries)
            val days = daysSince(iso, LocalDate.now(), ZoneId.systemDefault())
            val date = iso.take(10)
            if (days == 0L) {
                stringResource(R.string.vault_changed_today, date)
            } else {
                pluralStringResource(R.plurals.vault_changed_days_ago, days.toInt(), date, days)
            }
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
                    Text(stringResource(R.string.common_delete))
                }
            }
            Spacer(Modifier.weight(1f))
            Button(
                onClick = {
                    if (needsKeySelection) return@Button
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
                    !needsKeySelection &&
                    (dirty || isNew),
                modifier = Modifier.height(48.dp),
                shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.buttonColors(containerColor = DeepTeal),
            ) { Text(if (busy) stringResource(R.string.vault_encrypting) else stringResource(R.string.common_save), style = MaterialTheme.typography.titleSmall) }
        },
    ) {
                Text(
                    if (isNew) {
                        stringResource(R.string.vault_new_kind, stringResource(VAULT_KIND_LABELS.getValue(draft.kind)))
                    } else {
                        draft.title.ifBlank { stringResource(R.string.common_untitled) }
                    },
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
                            Text(stringResource(reminder.type.label), style = MaterialTheme.typography.titleSmall, color = tone)
                            Text(reminder.message.asString(), color = tone, style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
                if (draft.kind == VAULT_KIND_SUBSCRIPTION) {
                    Text(stringResource(R.string.vault_provider), style = MaterialTheme.typography.labelMedium)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        VAULT_PROVIDER_OPTIONS.forEach { provider ->
                            MemoFilterChip(
                                label = stringResource(VAULT_PROVIDER_LABELS.getValue(provider)),
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
                        label = { Text(stringResource(R.string.vault_plan)) },
                        placeholder = { Text(stringResource(R.string.vault_plan_placeholder)) },
                    )
                }
                OutlinedTextField(
                    value = draft.title,
                    onValueChange = { update(draft.copy(title = it.take(200))) },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                    label = { Text(stringResource(R.string.vault_name)) },
                )
                when (draft.kind) {
                    VAULT_KIND_LOGIN -> {
                        OutlinedTextField(
                            value = draft.username,
                            onValueChange = { update(draft.copy(username = it)) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text(stringResource(R.string.vault_username_or_email)) },
                            trailingIcon = {
                                IconButton(onClick = { onCopy(draft.username, R.string.vault_field_username) }, enabled = draft.username.isNotEmpty()) {
                                    Icon(Icons.Outlined.ContentCopy, contentDescription = stringResource(R.string.vault_copy_username), modifier = Modifier.size(18.dp))
                                }
                            },
                        )
                        OutlinedTextField(
                            value = draft.password,
                            onValueChange = { update(draft.copy(password = it)) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text(stringResource(R.string.auth_password_label)) },
                            textStyle = MaterialTheme.typography.bodyLarge.copy(fontFamily = FontFamily.Monospace),
                            visualTransformation = if (secretVisible) VisualTransformation.None else PasswordVisualTransformation(),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        )
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            FieldAction(if (secretVisible) Icons.Outlined.VisibilityOff else Icons.Outlined.Visibility, if (secretVisible) stringResource(R.string.auth_hide) else stringResource(R.string.auth_show)) { secretVisible = !secretVisible }
                            FieldAction(Icons.Outlined.AutoAwesome, stringResource(R.string.vault_generate)) { update(draft.copy(password = generateVaultPassword())) }
                            FieldAction(Icons.Outlined.ContentCopy, stringResource(R.string.common_copy), enabled = draft.password.isNotEmpty()) { onCopy(draft.password, R.string.auth_password_label) }
                        }
                        if (!draft.skipChecks && isWeakVaultPassword(draft.password)) {
                            Text(stringResource(R.string.vault_weak_password_hint), color = DangerRed, style = MaterialTheme.typography.bodySmall)
                        }
                        OutlinedTextField(
                            value = draft.url,
                            onValueChange = { update(draft.copy(url = it)) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text(stringResource(R.string.vault_field_url)) },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                        )
                    }
                    VAULT_KIND_SECRET -> {
                        OutlinedTextField(
                            value = draft.secret,
                            onValueChange = { update(draft.copy(secret = it)) },
                            modifier = Modifier.fillMaxWidth(),
                            minLines = if (secretVisible) 4 else 1,
                            label = { Text(stringResource(R.string.vault_secret_content)) },
                            textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                            visualTransformation = if (secretVisible) VisualTransformation.None else PasswordVisualTransformation(),
                        )
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            FieldAction(if (secretVisible) Icons.Outlined.VisibilityOff else Icons.Outlined.Visibility, if (secretVisible) stringResource(R.string.auth_hide) else stringResource(R.string.auth_show)) { secretVisible = !secretVisible }
                            FieldAction(Icons.Outlined.ContentCopy, stringResource(R.string.common_copy), enabled = draft.secret.isNotEmpty()) { onCopy(draft.secret, R.string.vault_kind_secret) }
                        }
                    }
                    VAULT_KIND_SERVER -> {
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            OutlinedTextField(
                                value = draft.host,
                                onValueChange = { update(draft.copy(host = it)) },
                                modifier = Modifier.weight(1f),
                                singleLine = true,
                                label = { Text(stringResource(R.string.vault_field_host)) },
                                placeholder = { Text("203.0.113.10") },
                            )
                            OutlinedTextField(
                                value = draft.port,
                                onValueChange = { value ->
                                    update(draft.copy(port = value.filter { it.isDigit() }.take(5)))
                                },
                                modifier = Modifier.width(110.dp),
                                singleLine = true,
                                label = { Text(stringResource(R.string.vault_field_port)) },
                                placeholder = { Text("22") },
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                            )
                        }
                        OutlinedTextField(
                            value = draft.username,
                            onValueChange = { update(draft.copy(username = it)) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text(stringResource(R.string.vault_login_user)) },
                            placeholder = { Text("root") },
                            trailingIcon = {
                                IconButton(onClick = { onCopy(draft.username, R.string.vault_field_username) }, enabled = draft.username.isNotEmpty()) {
                                    Icon(Icons.Outlined.ContentCopy, contentDescription = stringResource(R.string.vault_copy_username), modifier = Modifier.size(18.dp))
                                }
                            },
                        )
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            MemoFilterChip(
                                label = stringResource(R.string.auth_password_label),
                                selected = draft.authMethod == VAULT_AUTH_PASSWORD,
                                onClick = { update(draft.copy(authMethod = VAULT_AUTH_PASSWORD)) },
                            )
                            MemoFilterChip(
                                label = stringResource(R.string.vault_ssh_private_key),
                                selected = draft.authMethod == VAULT_AUTH_KEY,
                                onClick = { update(draft.copy(authMethod = VAULT_AUTH_KEY)) },
                            )
                        }
                        if (draft.authMethod == VAULT_AUTH_KEY) {
                            val secrets = entries
                                .filter { it.data.kind == VAULT_KIND_SECRET }
                                .sortedBy { it.data.title }
                            val resolved = draft.resolvePrivateKey(entries)
                            Text(stringResource(R.string.vault_key_source), style = MaterialTheme.typography.labelMedium)
                            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                MemoFilterChip(
                                    label = stringResource(R.string.vault_enter_directly),
                                    selected = !useKeyRef,
                                    onClick = {
                                        useKeyRef = false
                                        update(draft.copy(privateKeyRef = ""))
                                    },
                                )
                                MemoFilterChip(
                                    label = stringResource(R.string.vault_use_saved_key),
                                    selected = useKeyRef,
                                    onClick = {
                                        useKeyRef = true
                                        onTouch()
                                    },
                                )
                            }
                            if (useKeyRef) {
                                if (secrets.isEmpty()) {
                                    Text(
                                        stringResource(R.string.vault_no_saved_keys),
                                        color = TextMuted,
                                        style = MaterialTheme.typography.bodySmall,
                                    )
                                } else {
                                    Text(stringResource(R.string.vault_choose_key), style = MaterialTheme.typography.labelMedium)
                                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                        secrets.forEach { secret ->
                                            MemoFilterChip(
                                                label = secret.data.title.ifBlank { stringResource(R.string.common_untitled) },
                                                selected = draft.privateKeyRef == secret.id,
                                                onClick = { update(draft.copy(privateKeyRef = secret.id)) },
                                            )
                                        }
                                    }
                                    if (needsKeySelection) {
                                        Text(
                                            stringResource(R.string.vault_choose_key_ref),
                                            color = TextMuted,
                                            style = MaterialTheme.typography.bodySmall,
                                        )
                                    }
                                }
                                if (draft.privateKeyRef.isNotEmpty() && resolved.missing) {
                                    Text(
                                        stringResource(R.string.vault_ref_deleted),
                                        color = DangerRed,
                                        style = MaterialTheme.typography.bodySmall,
                                    )
                                } else if (draft.privateKeyRef.isNotEmpty()) {
                                    Text(
                                        stringResource(R.string.vault_ref_auto_update),
                                        color = TextMuted,
                                        style = MaterialTheme.typography.bodySmall,
                                    )
                                    FieldAction(
                                        Icons.Outlined.ContentCopy,
                                        stringResource(R.string.common_copy),
                                        enabled = resolved.value.isNotEmpty(),
                                    ) { onCopy(resolved.value, R.string.vault_private_key) }
                                }
                            } else {
                                OutlinedTextField(
                                    value = draft.privateKey,
                                    onValueChange = { update(draft.copy(privateKey = it)) },
                                    modifier = Modifier.fillMaxWidth(),
                                    minLines = if (secretVisible) 4 else 1,
                                    label = { Text(stringResource(R.string.vault_ssh_private_key)) },
                                    textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                                    visualTransformation = if (secretVisible) VisualTransformation.None else PasswordVisualTransformation(),
                                )
                                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    FieldAction(if (secretVisible) Icons.Outlined.VisibilityOff else Icons.Outlined.Visibility, if (secretVisible) stringResource(R.string.auth_hide) else stringResource(R.string.auth_show)) { secretVisible = !secretVisible }
                                    FieldAction(Icons.Outlined.ContentCopy, stringResource(R.string.common_copy), enabled = draft.privateKey.isNotEmpty()) { onCopy(draft.privateKey, R.string.vault_private_key) }
                                }
                            }
                            OutlinedTextField(
                                value = draft.keyPassphrase,
                                onValueChange = { update(draft.copy(keyPassphrase = it)) },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                label = { Text(stringResource(R.string.vault_key_passphrase)) },
                                textStyle = MaterialTheme.typography.bodyLarge.copy(fontFamily = FontFamily.Monospace),
                                visualTransformation = if (secretVisible) VisualTransformation.None else PasswordVisualTransformation(),
                            )
                        } else {
                            OutlinedTextField(
                                value = draft.password,
                                onValueChange = { update(draft.copy(password = it)) },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                label = { Text(stringResource(R.string.vault_login_password)) },
                                textStyle = MaterialTheme.typography.bodyLarge.copy(fontFamily = FontFamily.Monospace),
                                visualTransformation = if (secretVisible) VisualTransformation.None else PasswordVisualTransformation(),
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                            )
                            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                FieldAction(if (secretVisible) Icons.Outlined.VisibilityOff else Icons.Outlined.Visibility, if (secretVisible) stringResource(R.string.auth_hide) else stringResource(R.string.auth_show)) { secretVisible = !secretVisible }
                                FieldAction(Icons.Outlined.AutoAwesome, stringResource(R.string.vault_generate)) { update(draft.copy(password = generateVaultPassword())) }
                                FieldAction(Icons.Outlined.ContentCopy, stringResource(R.string.common_copy), enabled = draft.password.isNotEmpty()) { onCopy(draft.password, R.string.auth_password_label) }
                            }
                        }
                    }
                    VAULT_KIND_SUBSCRIPTION -> {
                        OutlinedTextField(
                            value = draft.account,
                            onValueChange = { update(draft.copy(account = it)) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text(stringResource(R.string.vault_subscription_account)) },
                            trailingIcon = {
                                IconButton(onClick = { onCopy(draft.account, R.string.vault_field_account) }, enabled = draft.account.isNotEmpty()) {
                                    Icon(Icons.Outlined.ContentCopy, contentDescription = stringResource(R.string.vault_copy_account), modifier = Modifier.size(18.dp))
                                }
                            },
                        )
                        OutlinedTextField(
                            value = draft.startedOn,
                            onValueChange = { update(draft.copy(startedOn = it.trim().take(10))) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text(stringResource(R.string.vault_started_on)) },
                            placeholder = { Text(stringResource(R.string.vault_example_2026_01)) },
                            isError = startedInvalid,
                            supportingText = {
                                Text(if (startedInvalid) stringResource(R.string.vault_date_hint_start) else stringResource(R.string.vault_start_blank))
                            },
                        )
                        OutlinedTextField(
                            value = draft.expiresOn,
                            onValueChange = { update(draft.copy(expiresOn = it.trim().take(10))) },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            label = { Text(stringResource(R.string.vault_expiry_renewal)) },
                            placeholder = { Text(stringResource(R.string.vault_example_2026_11)) },
                            isError = expiryInvalid,
                            supportingText = {
                                Text(
                                    when {
                                        expiryInvalid -> stringResource(R.string.vault_date_hint_expiry)
                                        expiresIn == null -> stringResource(R.string.vault_expiry_blank_no_reminder)
                                        expiresIn < 0 -> pluralStringResource(R.plurals.vault_expired_days, (-expiresIn).toInt(), -expiresIn)
                                        expiresIn == 0L -> stringResource(R.string.vault_due_today)
                                        else -> pluralStringResource(R.plurals.vault_expires_in_days, expiresIn.toInt(), expiresIn)
                                    },
                                )
                            },
                        )
                        Text(stringResource(R.string.vault_billing_cycle), style = MaterialTheme.typography.labelMedium)
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            VAULT_BILLING_OPTIONS.forEach { cycle ->
                                MemoFilterChip(
                                    label = stringResource(VAULT_BILLING_LABELS.getValue(cycle)),
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
                            label = { Text(stringResource(R.string.vault_price)) },
                            placeholder = { Text(stringResource(R.string.vault_price_placeholder)) },
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                            isError = priceInvalid,
                            supportingText = {
                                if (priceInvalid) Text(stringResource(R.string.vault_money_invalid))
                            },
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.Top) {
                            OutlinedTextField(
                                value = draft.balance,
                                onValueChange = { update(draft.copy(balance = it.trim().take(12))) },
                                modifier = Modifier.weight(1f),
                                singleLine = true,
                                label = { Text(stringResource(R.string.vault_balance)) },
                                placeholder = { Text(stringResource(R.string.vault_balance_placeholder)) },
                                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                                isError = balanceInvalid,
                                supportingText = {
                                    if (balanceInvalid) Text(stringResource(R.string.vault_money_invalid))
                                },
                            )
                            OutlinedTextField(
                                value = draft.currency,
                                onValueChange = { value ->
                                    update(draft.copy(currency = value.filter { it.isLetter() }.uppercase().take(3)))
                                },
                                modifier = Modifier.width(110.dp),
                                singleLine = true,
                                label = { Text(stringResource(R.string.vault_currency)) },
                                placeholder = { Text("USD") },
                                isError = currencyInvalid,
                                supportingText = {
                                    Text(
                                        when {
                                            currencyInvalid -> stringResource(R.string.vault_currency_invalid)
                                            draft.currency.isBlank() -> stringResource(R.string.vault_currency_blank)
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
                            label = { Text(stringResource(R.string.vault_linked_account)) },
                        )
                        if (draft.codes.isNotEmpty()) {
                            Text(stringResource(R.string.vault_codes_remaining, draft.codes.count { !it.used }, draft.codes.size), color = TextMuted, style = MaterialTheme.typography.bodySmall)
                        }
                        draft.codes.forEachIndexed { index, code ->
                            RecoveryCodeRow(
                                code = code,
                                onToggle = {
                                    update(draft.copy(codes = draft.codes.mapIndexed { current, item ->
                                        if (current == index) item.copy(used = !item.used) else item
                                    }))
                                },
                                onCopy = { onCopy(code.code, R.string.vault_kind_recovery) },
                                onRemove = { update(draft.copy(codes = draft.codes.filterIndexed { current, _ -> current != index })) },
                            )
                        }
                        OutlinedTextField(
                            value = pastedCodes,
                            onValueChange = { pastedCodes = it },
                            modifier = Modifier.fillMaxWidth(),
                            minLines = 2,
                            label = { Text(stringResource(R.string.vault_add_codes)) },
                            placeholder = { Text(stringResource(R.string.vault_paste_codes_placeholder)) },
                        )
                        FieldAction(Icons.Outlined.Add, stringResource(R.string.vault_add_codes), enabled = pastedCodes.isNotBlank()) {
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
                        Text(stringResource(R.string.vault_reminders), style = MaterialTheme.typography.titleSmall)
                        Text(
                            stringResource(
                                R.string.vault_last_changed,
                                stringResource(
                                    when (draft.kind) {
                                        VAULT_KIND_LOGIN -> R.string.auth_password_label
                                        VAULT_KIND_SERVER -> R.string.vault_login_credentials
                                        else -> R.string.vault_kind_secret
                                    },
                                ),
                                changedLabel,
                            ),
                            color = TextMuted,
                            style = MaterialTheme.typography.bodySmall,
                        )
                        Text(stringResource(R.string.vault_rotate), style = MaterialTheme.typography.labelMedium)
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
                            label = { Text(stringResource(R.string.vault_expiry_optional)) },
                            placeholder = { Text(stringResource(R.string.vault_example_2027)) },
                            isError = expiryInvalid,
                            supportingText = {
                                Text(
                                    when {
                                        expiryInvalid -> stringResource(R.string.vault_date_hint_expiry_key)
                                        expiresIn == null -> stringResource(R.string.vault_expiry_blank_never)
                                        expiresIn < 0 -> pluralStringResource(R.plurals.vault_expired_days, (-expiresIn).toInt(), -expiresIn)
                                        expiresIn == 0L -> stringResource(R.string.vault_due_today)
                                        else -> pluralStringResource(R.plurals.vault_expires_in_days, expiresIn.toInt(), expiresIn)
                                    },
                                )
                            },
                        )
                        if (draft.kind == VAULT_KIND_LOGIN) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Checkbox(checked = draft.skipChecks, onCheckedChange = { update(draft.copy(skipChecks = it)) })
                                Text(stringResource(R.string.vault_skip_checks), style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
                OutlinedTextField(
                    value = draft.notes,
                    onValueChange = { update(draft.copy(notes = it.take(10_000))) },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 3,
                    label = { Text(stringResource(R.string.dialog_note)) },
                )
    }

    if (confirmDiscard) {
        AlertDialog(
            onDismissRequest = { confirmDiscard = false },
            text = { Text(stringResource(R.string.vault_discard_text)) },
            confirmButton = {
                TextButton(onClick = {
                    confirmDiscard = false
                    onDismiss()
                }) { Text(stringResource(R.string.vault_discard_changes)) }
            },
            dismissButton = { TextButton(onClick = { confirmDiscard = false }) { Text(stringResource(R.string.home_keep_editing)) } },
        )
    }
    if (confirmDelete) {
        val referencing = if (initial.kind == VAULT_KIND_SECRET && entry != null) {
            serversReferencingKey(entry.id, entries)
        } else {
            emptyList()
        }
        val untitled = stringResource(R.string.common_untitled)
        val separator = stringResource(R.string.common_list_separator)
        val deleteMessage = buildString {
            append(stringResource(R.string.vault_delete_confirm, initial.title))
            if (referencing.isNotEmpty()) {
                val names = referencing.joinToString(separator) { it.data.title.ifBlank { untitled } }
                append(pluralStringResource(R.plurals.vault_delete_referenced, referencing.size, referencing.size, names))
            }
        }
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            text = { Text(deleteMessage) },
            confirmButton = {
                TextButton(onClick = {
                    confirmDelete = false
                    onDelete()
                }) { Text(stringResource(R.string.common_delete), color = DangerRed) }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text(stringResource(R.string.common_cancel)) } },
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
            if (code.used) stringResource(R.string.vault_code_used) else stringResource(R.string.vault_code_available),
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
            Icon(Icons.Outlined.ContentCopy, contentDescription = stringResource(R.string.vault_copy_code), modifier = Modifier.size(18.dp))
        }
        IconButton(onClick = onRemove) {
            Icon(Icons.Outlined.Close, contentDescription = stringResource(R.string.vault_delete_code), tint = DangerRed, modifier = Modifier.size(18.dp))
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
