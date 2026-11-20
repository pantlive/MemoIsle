package com.memoisle.app.ui

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContract
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.core.content.FileProvider
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.memoisle.app.RelayViewModel
import com.memoisle.app.data.RelayItem
import com.memoisle.app.data.formatRelayBytes
import com.memoisle.app.data.formatRelayRemaining
import com.memoisle.app.data.relayClipboardImageName
import com.memoisle.app.data.relayDeviceLabel
import com.memoisle.app.update.AppUpdater
import java.io.File
import kotlinx.coroutines.delay

/** 系统「另存为」，文件名和类型按收到的内容逐条设置。 */
private class CreateRelayDocument : ActivityResultContract<Pair<String, String>, Uri?>() {
    override fun createIntent(context: Context, input: Pair<String, String>): Intent =
        Intent(Intent.ACTION_CREATE_DOCUMENT)
            .addCategory(Intent.CATEGORY_OPENABLE)
            .setType(input.second)
            .putExtra(Intent.EXTRA_TITLE, input.first)

    override fun parseResult(resultCode: Int, intent: Intent?): Uri? =
        if (resultCode == Activity.RESULT_OK) intent?.data else null
}

/**
 * 手机与网页互传文字、图片、小文件。服务端只在内存里转发，取走即删，10 分钟内有效。
 * 页面可见时自动接收，App 退到后台时暂停。
 */
@OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3Api::class)
@Composable
fun RelayScreen(viewModel: RelayViewModel, onClose: () -> Unit) {
    val state = viewModel.uiState
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val snackbarHostState = remember { SnackbarHostState() }
    var text by rememberSaveable { mutableStateOf("") }
    var pendingSave by remember { mutableStateOf<RelayItem?>(null) }
    var pendingLocalFile by remember { mutableStateOf<File?>(null) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }

    val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) viewModel.sendFile(uri, context.contentResolver)
    }
    val saveLauncher = rememberLauncherForActivityResult(CreateRelayDocument()) { uri ->
        val item = pendingSave
        val local = pendingLocalFile
        pendingSave = null
        pendingLocalFile = null
        if (uri == null) {
            if (local != null) {
                viewModel.showError("无法写入剪贴板，且未选择保存位置，内容可能已从服务器删除。")
            }
            return@rememberLauncherForActivityResult
        }
        if (local != null) {
            viewModel.saveCachedFile(local, uri, context.contentResolver, item?.filename ?: local.name)
        } else if (item != null) {
            viewModel.saveFile(item, uri, context.contentResolver)
        }
    }

    fun pasteClipboardImage() {
        val clipboard = context.getSystemService(ClipboardManager::class.java)
        if (clipboard == null) {
            viewModel.showError("剪贴板里没有图片")
            return
        }
        try {
            val clip = clipboard.primaryClip
            val description = clip?.description
            if (clip == null || description == null) {
                viewModel.showError("剪贴板里没有图片")
                return
            }
            for (index in 0 until clip.itemCount) {
                val uri = clip.getItemAt(index).uri ?: continue
                val mime = context.contentResolver.getType(uri)
                    ?: (0 until description.mimeTypeCount)
                        .map { description.getMimeType(it) }
                        .firstOrNull { it.startsWith("image/", ignoreCase = true) }
                val looksLikeImage = description.hasMimeType("image/*") ||
                    mime?.startsWith("image/") == true
                if (!looksLikeImage) continue
                viewModel.sendFile(
                    uri,
                    context.contentResolver,
                    relayClipboardImageName(mime, System.currentTimeMillis()),
                )
                return
            }
            viewModel.showError("剪贴板里没有图片")
        } catch (_: SecurityException) {
            viewModel.showError("没有读取或写入这个文件的权限。")
        }
    }

    fun copyReceivedImage(item: RelayItem) {
        viewModel.copyImage(item, context.cacheDir) { file ->
            val copied = runCatching {
                val uri = FileProvider.getUriForFile(
                    context,
                    "${context.packageName}${AppUpdater.AUTHORITY_SUFFIX}",
                    file,
                )
                val clipboard = context.getSystemService(ClipboardManager::class.java)
                    ?: error("无法访问剪贴板")
                clipboard.setPrimaryClip(ClipData.newUri(context.contentResolver, "MemoIsle 图片", uri))
            }.isSuccess
            if (!copied) {
                pendingLocalFile = file
                pendingSave = item
                viewModel.showError("无法写入剪贴板，请选择保存位置以免内容丢失。")
                runCatching {
                    saveLauncher.launch(
                        (item.filename ?: file.name) to (item.mimeType ?: "image/*"),
                    )
                }.onFailure {
                    pendingLocalFile = null
                    pendingSave = null
                    viewModel.showError("无法写入剪贴板，也没有可用的文件管理器来保存文件。")
                }
            }
        }
    }

    BackHandler(onBack = onClose)
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> viewModel.startPolling()
                Lifecycle.Event.ON_STOP -> viewModel.stopPolling()
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            viewModel.stopPolling()
        }
    }
    LaunchedEffect(state.message, state.error) {
        val message = state.error ?: state.message ?: return@LaunchedEffect
        snackbarHostState.showSnackbar(message)
        viewModel.clearMessage()
    }
    // 有待接收内容时每秒刷新倒计时。
    LaunchedEffect(state.items.isNotEmpty()) {
        while (state.items.isNotEmpty()) {
            now = System.currentTimeMillis()
            delay(1_000)
        }
    }

    fun copy(value: String) {
        val clipboard = context.getSystemService(ClipboardManager::class.java) ?: return
        clipboard.setPrimaryClip(ClipData.newPlainText("MemoIsle", value))
    }

    val busy = state.sending || state.busyId != null
    val visible = state.items.filter { (state.deadlines[it.id] ?: 0L) > now }

    Scaffold(
        topBar = {
            TopAppBar(title = { Text("传输") }, navigationIcon = {
                IconButton(onClick = onClose) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回") }
            })
        },
        snackbarHost = { SnackbarHost(snackbarHostState) },
    ) { padding ->
        LazyColumn(
            Modifier.fillMaxSize().padding(padding).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Text(
                    "手机和网页互传文字、图片、小文件；服务器只转发不保存，10 分钟内有效。",
                    style = MaterialTheme.typography.bodySmall,
                    color = TextMuted,
                )
            }
            item {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Text("发给网页", style = MaterialTheme.typography.titleMedium)
                        OutlinedTextField(
                            value = text,
                            onValueChange = { text = it },
                            label = { Text("要发送的文字") },
                            placeholder = { Text("链接、验证码或一段文字") },
                            enabled = !state.sending,
                            modifier = Modifier.fillMaxWidth().heightIn(min = 96.dp),
                            maxLines = 8,
                        )
                        FlowRow(
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Button(
                                enabled = !busy && text.isNotBlank(),
                                onClick = { viewModel.sendText(text) { text = "" } },
                            ) { Text(if (state.sending) "发送中…" else "发送文字") }
                            Button(
                                enabled = !busy,
                                onClick = { pasteClipboardImage() },
                            ) { Text("粘贴剪贴板图片") }
                            OutlinedButton(
                                enabled = !busy,
                                onClick = { filePicker.launch(arrayOf("*/*")) },
                            ) { Text("选择文件") }
                        }
                        Text("单个文件不超过 20 MB。", style = MaterialTheme.typography.bodySmall, color = TextMuted)
                    }
                }
            }
            item {
                Text("收到的内容", style = MaterialTheme.typography.titleMedium)
                Text(
                    state.pollError ?: "保持此页打开即可自动接收",
                    style = MaterialTheme.typography.bodySmall,
                    color = if (state.pollError != null) MaterialTheme.colorScheme.error else TextMuted,
                )
            }
            if (visible.isEmpty()) {
                item {
                    Text(
                        "暂时没有。在网页打开「传输」发送文字、图片或文件后，会自动出现在这里。",
                        modifier = Modifier.padding(vertical = 24.dp),
                        color = TextMuted,
                    )
                }
            }
            items(visible, key = { it.id }) { item ->
                val remaining = ((state.deadlines[item.id] ?: now) - now) / 1_000
                val itemBusy = state.busyId == item.id
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(
                            "来自${relayDeviceLabel(item.source)} · ${formatRelayBytes(item.size)} · " +
                                "剩余 ${formatRelayRemaining(remaining)}",
                            style = MaterialTheme.typography.bodySmall,
                            color = TextMuted,
                        )
                        if (item.isText) {
                            SelectionContainer { Text(item.text.orEmpty(), maxLines = 12) }
                        } else {
                            Text(item.filename ?: "file", style = MaterialTheme.typography.titleSmall)
                        }
                        FlowRow(
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            if (item.isText) {
                                Button(enabled = !busy, onClick = { viewModel.copyText(item, ::copy) }) {
                                    Text("复制")
                                }
                            } else if (item.isImage) {
                                Button(enabled = !busy, onClick = { copyReceivedImage(item) }) {
                                    Text(if (itemBusy) "复制中…" else "复制图片")
                                }
                                OutlinedButton(enabled = !busy, onClick = {
                                    pendingLocalFile = null
                                    pendingSave = item
                                    runCatching {
                                        saveLauncher.launch(
                                            (item.filename ?: "file") to
                                                (item.mimeType ?: "image/*"),
                                        )
                                    }.onFailure {
                                        pendingSave = null
                                        viewModel.showError("没有可用的文件管理器来保存文件。")
                                    }
                                }) { Text(if (itemBusy) "保存中…" else "保存") }
                            } else {
                                Button(enabled = !busy, onClick = {
                                    pendingLocalFile = null
                                    pendingSave = item
                                    runCatching {
                                        saveLauncher.launch(
                                            (item.filename ?: "file") to
                                                (item.mimeType ?: "application/octet-stream"),
                                        )
                                    }.onFailure {
                                        pendingSave = null
                                        viewModel.showError("没有可用的文件管理器来保存文件。")
                                    }
                                }) { Text(if (itemBusy) "保存中…" else "保存") }
                            }
                            TextButton(enabled = !busy, onClick = { viewModel.discard(item) }) { Text("忽略") }
                        }
                    }
                }
            }
        }
    }
}
