package com.memoisle.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.memoisle.app.AuthStatus
import com.memoisle.app.AuthViewModel

@Composable
fun AuthScreen(
    viewModel: AuthViewModel,
    onOpenProvider: (String) -> Unit,
): Unit {
    val state by viewModel.uiState.collectAsState()
    var isRegisterMode by rememberSaveable { mutableStateOf(false) }
    var email by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var confirmPassword by rememberSaveable { mutableStateOf("") }
    var displayName by rememberSaveable { mutableStateOf("") }
    var showThirdPartyLogin by rememberSaveable { mutableStateOf(false) }
    val minimumPasswordLength = if (isRegisterMode) 8 else 1
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Card {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(text = "MemoIsle", style = MaterialTheme.typography.headlineMedium)
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "使用同一账号在 Web 与 Android 之间同步资料库。",
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(modifier = Modifier.height(24.dp))
                if (state.status == AuthStatus.LOADING) {
                    CircularProgressIndicator()
                } else {
                    OutlinedButton(
                        onClick = { showThirdPartyLogin = !showThirdPartyLogin },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text(if (showThirdPartyLogin) "收起第三方登录" else "第三方登录")
                    }
                    Spacer(modifier = Modifier.height(10.dp))
                    if (showThirdPartyLogin) {
                        state.providers?.providers?.forEach { provider ->
                            OutlinedButton(
                                onClick = { onOpenProvider(provider.provider) },
                                modifier = Modifier.fillMaxWidth(),
                                enabled = provider.enabled,
                            ) {
                                Text(text = provider.label)
                            }
                            Spacer(modifier = Modifier.height(10.dp))
                        }
                        if (state.providers?.providers?.any { it.enabled } == false) {
                            Text(
                                text = "第三方登录待远程部署配置完成后开放。",
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                        Spacer(modifier = Modifier.height(18.dp))
                    }
                    if (state.providers?.emailLoginEnabled != false) {
                        OutlinedTextField(
                            value = email,
                            onValueChange = { email = it },
                            modifier = Modifier.fillMaxWidth(),
                            label = { Text("邮箱") },
                            singleLine = true,
                        )
                        Spacer(modifier = Modifier.height(10.dp))
                        if (isRegisterMode) {
                            OutlinedTextField(
                                value = displayName,
                                onValueChange = { displayName = it },
                                modifier = Modifier.fillMaxWidth(),
                                label = { Text("昵称（可选）") },
                                singleLine = true,
                            )
                            Spacer(modifier = Modifier.height(10.dp))
                        }
                        OutlinedTextField(
                            value = password,
                            onValueChange = { password = it },
                            modifier = Modifier.fillMaxWidth(),
                            label = { Text(if (isRegisterMode) "密码（至少 8 位）" else "密码") },
                            singleLine = true,
                            visualTransformation = PasswordVisualTransformation(),
                        )
                        Spacer(modifier = Modifier.height(10.dp))
                        if (isRegisterMode) {
                            OutlinedTextField(
                                value = confirmPassword,
                                onValueChange = { confirmPassword = it },
                                modifier = Modifier.fillMaxWidth(),
                                label = { Text("确认密码") },
                                singleLine = true,
                                visualTransformation = PasswordVisualTransformation(),
                            )
                            Spacer(modifier = Modifier.height(10.dp))
                        }
                        Button(
                            onClick = {
                                if (isRegisterMode) {
                                    viewModel.registerWithEmail(
                                        email.trim(),
                                        password,
                                        confirmPassword,
                                        displayName.trim().ifEmpty { null },
                                    )
                                } else {
                                    viewModel.loginWithEmail(email.trim(), password)
                                }
                            },
                            modifier = Modifier.fillMaxWidth(),
                            enabled = !state.isBusy && email.isNotBlank() &&
                                password.length >= minimumPasswordLength &&
                                (!isRegisterMode ||
                                    confirmPassword == password),
                        ) {
                            Text(
                                when {
                                    state.isBusy -> "正在处理…"
                                    isRegisterMode -> "创建账号"
                                    else -> "邮箱登录"
                                },
                            )
                        }
                        OutlinedButton(
                            onClick = { isRegisterMode = !isRegisterMode },
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text(if (isRegisterMode) "已有账号？切换登录" else "没有账号？注册邮箱账号")
                        }
                        Spacer(modifier = Modifier.height(18.dp))
                    }
                    if (state.providers?.devLoginAvailable == true) {
                        Button(
                            onClick = viewModel::devLogin,
                            modifier = Modifier.fillMaxWidth(),
                            enabled = !state.isBusy,
                        ) {
                            Text(text = if (state.isBusy) "正在登录…" else "本地开发登录")
                        }
                    }
                    if (state.providers != null &&
                        state.providers?.providers?.none { it.enabled } == true &&
                        state.providers?.devLoginAvailable == false
                    ) {
                        Spacer(modifier = Modifier.height(12.dp))
                        Text(
                            text = "第三方登录将在远程部署配置完成后开放。",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    state.message?.let { message ->
                        Spacer(modifier = Modifier.height(12.dp))
                        Text(
                            text = message,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                }
            }
        }
    }
}
