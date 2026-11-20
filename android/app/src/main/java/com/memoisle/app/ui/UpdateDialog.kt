package com.memoisle.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.DialogProperties
import com.memoisle.app.UpdatePhase
import com.memoisle.app.UpdateUiState
import com.memoisle.app.data.formatRelayBytes

/**
 * 新版本提示：版本号、更新说明、下载进度。
 * 按钮为「更新 / 稍后 / 忽略此版本」，下载完成后变为「安装」。
 */
@Composable
fun UpdateDialog(
    state: UpdateUiState,
    currentVersionName: String,
    onUpdate: () -> Unit,
    onInstall: () -> Unit,
    onLater: () -> Unit,
    onIgnore: () -> Unit,
) {
    val release = state.release ?: return
    val downloading = state.phase == UpdatePhase.DOWNLOADING
    AlertDialog(
        // 下载中点外面不关闭，避免误触取消；要取消请点「稍后」。
        onDismissRequest = { if (!downloading) onLater() },
        properties = DialogProperties(dismissOnClickOutside = !downloading),
        containerColor = SurfaceWhite,
        title = { Text("发现新版本 ${release.versionName}", fontWeight = FontWeight.SemiBold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    "当前版本 $currentVersionName · 安装包 ${formatRelayBytes(release.size)}",
                    style = MaterialTheme.typography.bodySmall,
                    color = TextMuted,
                )
                if (release.releaseNotes.isNotBlank()) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(max = 220.dp)
                            .verticalScroll(rememberScrollState()),
                    ) {
                        Text(release.releaseNotes, style = MaterialTheme.typography.bodyMedium, color = TextStrong)
                    }
                }
                when (state.phase) {
                    UpdatePhase.DOWNLOADING -> {
                        val progress = state.progress
                        if (progress == null) {
                            LinearProgressIndicator(modifier = Modifier.fillMaxWidth(), color = DeepTeal)
                        } else {
                            LinearProgressIndicator(
                                progress = { progress },
                                modifier = Modifier.fillMaxWidth(),
                                color = DeepTeal,
                            )
                        }
                        Text(
                            if (progress == null) "下载中…" else "下载中 ${(progress * 100).toInt()}%",
                            style = MaterialTheme.typography.bodySmall,
                            color = TextMuted,
                        )
                    }
                    UpdatePhase.DOWNLOADED -> Text(
                        "已下载并校验通过。点「安装」后在系统界面确认；首次安装需允许 MemoIsle 安装未知应用。",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextMuted,
                    )
                    UpdatePhase.FAILED -> Text(
                        state.message ?: "更新失败，请稍后重试",
                        style = MaterialTheme.typography.bodySmall,
                        color = DangerRed,
                    )
                    else -> Unit
                }
            }
        },
        confirmButton = {
            when (state.phase) {
                UpdatePhase.DOWNLOADED -> Button(onClick = onInstall) { Text("安装") }
                UpdatePhase.FAILED -> Button(onClick = onUpdate) { Text("重试") }
                else -> Button(onClick = onUpdate, enabled = !downloading) {
                    Text(if (downloading) "下载中…" else "更新")
                }
            }
        },
        dismissButton = {
            Row {
                if (state.phase == UpdatePhase.AVAILABLE) {
                    TextButton(onClick = onIgnore) { Text("忽略此版本", color = TextMuted) }
                }
                TextButton(onClick = onLater) { Text(if (downloading) "取消" else "稍后") }
            }
        },
    )
}
