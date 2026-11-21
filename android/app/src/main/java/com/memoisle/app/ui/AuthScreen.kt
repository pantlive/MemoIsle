package com.memoisle.app.ui

import android.util.Patterns
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.memoisle.app.AuthMessageTone
import com.memoisle.app.AuthStatus
import com.memoisle.app.AuthUiState
import com.memoisle.app.AuthViewModel
import com.memoisle.app.R
import com.memoisle.app.network.AuthProviderInfo

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
    var verificationCode by rememberSaveable { mutableStateOf("") }
    var inviteCode by rememberSaveable { mutableStateOf("") }
    var displayName by rememberSaveable { mutableStateOf("") }
    var showPassword by rememberSaveable { mutableStateOf(false) }
    var showConfirmPassword by rememberSaveable { mutableStateOf(false) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(WarmMist)
            .imePadding(),
    ) {
        Column(
            modifier = Modifier
                .align(Alignment.Center)
                .fillMaxWidth()
                .widthIn(max = 480.dp)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 24.dp, vertical = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            AuthBrand()
            Spacer(modifier = Modifier.height(22.dp))
            val inviteRequired = state.providers?.inviteRequired == true
            Text(
                text = when {
                    isRegisterMode && inviteRequired -> stringResource(R.string.auth_title_register_invite)
                    isRegisterMode -> stringResource(R.string.auth_title_register)
                    else -> stringResource(R.string.auth_title_login)
                },
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.SemiBold,
                textAlign = TextAlign.Center,
            )
            Spacer(modifier = Modifier.height(7.dp))
            Text(
                text = if (isRegisterMode) {
                    stringResource(R.string.auth_subtitle_register)
                } else {
                    stringResource(R.string.auth_subtitle_login)
                },
                color = TextMuted,
                style = MaterialTheme.typography.bodyMedium,
                textAlign = TextAlign.Center,
            )
            Spacer(modifier = Modifier.height(26.dp))

            if (state.status == AuthStatus.LOADING) {
                CircularProgressIndicator(color = DeepTeal)
                Spacer(modifier = Modifier.height(12.dp))
                Text(stringResource(R.string.auth_checking), color = TextMuted)
            } else {
                AuthForm(
                    isRegisterMode = isRegisterMode,
                    email = email,
                    onEmailChange = { email = it },
                    displayName = displayName,
                    onDisplayNameChange = { displayName = it },
                    verificationCode = verificationCode,
                    onVerificationCodeChange = {
                        verificationCode = it.filter(Char::isDigit).take(6)
                    },
                    inviteCode = inviteCode,
                    onInviteCodeChange = { inviteCode = it.take(32) },
                    password = password,
                    onPasswordChange = { password = it },
                    confirmPassword = confirmPassword,
                    onConfirmPasswordChange = { confirmPassword = it },
                    showPassword = showPassword,
                    onShowPasswordChange = { showPassword = it },
                    showConfirmPassword = showConfirmPassword,
                    onShowConfirmPasswordChange = { showConfirmPassword = it },
                    state = state,
                    viewModel = viewModel,
                ) {
                    if (isRegisterMode) {
                        viewModel.registerWithEmail(
                            email.trim(),
                            password,
                            confirmPassword,
                            verificationCode.trim(),
                            displayName.trim().ifEmpty { null },
                            inviteCode.trim(),
                        )
                    } else {
                        viewModel.loginWithEmail(email.trim(), password)
                    }
                }

                if (!isRegisterMode) {
                    TextButton(
                        onClick = { viewModel.requestPasswordReset(email.trim()) },
                        enabled = !state.isBusy && email.isNotBlank(),
                        contentPadding = PaddingValues(horizontal = 12.dp),
                    ) {
                        Text(stringResource(R.string.auth_forgot_password), color = DeepTealHover)
                    }
                }

                AuthModeSwitch(
                    isRegisterMode = isRegisterMode,
                    onToggle = { isRegisterMode = !isRegisterMode },
                    enabled = !state.isBusy,
                )

                val enabledProviders = state.providers?.providers
                    ?.filter { it.enabled }
                    .orEmpty()
                if (!isRegisterMode && state.providers?.devLoginAvailable == true) {
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedButton(
                        onClick = viewModel::devLogin,
                        modifier = Modifier.fillMaxWidth(),
                        enabled = !state.isBusy,
                        shape = RoundedCornerShape(10.dp),
                    ) {
                        Text(if (state.isBusy) stringResource(R.string.auth_entering) else stringResource(R.string.auth_dev_login))
                    }
                }
                if (enabledProviders.isNotEmpty()) {
                    AuthProviderButtons(
                        providers = enabledProviders,
                        onOpenProvider = onOpenProvider,
                    )
                }
                if (isRegisterMode) {
                    Text(
                        text = stringResource(R.string.auth_register_terms),
                        color = TextMuted,
                        style = MaterialTheme.typography.labelSmall,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.padding(top = 18.dp),
                    )
                }
                Text(
                    text = stringResource(R.string.auth_footer),
                    color = TextMuted,
                    style = MaterialTheme.typography.labelSmall,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(top = 18.dp),
                )
                state.message?.let { message ->
                    Text(
                        text = message.asString(),
                        style = MaterialTheme.typography.bodySmall,
                        color = if (state.messageTone == AuthMessageTone.NOTICE) {
                            DeepTealHover
                        } else {
                            MaterialTheme.colorScheme.error
                        },
                        textAlign = TextAlign.Center,
                        modifier = Modifier.padding(top = 14.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun AuthBrand(): Unit {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Box(
            modifier = Modifier
                .size(50.dp)
                .clip(RoundedCornerShape(15.dp))
                .background(TealSoft)
                .border(1.dp, DeepTeal.copy(alpha = 0.18f), RoundedCornerShape(15.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Image(
                painter = painterResource(R.drawable.ic_memoisle),
                contentDescription = null,
                modifier = Modifier.size(50.dp),
            )
        }
        Spacer(modifier = Modifier.height(6.dp))
        Text(
            text = "MemoIsle",
            color = DeepTealHover,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
private fun AuthForm(
    isRegisterMode: Boolean,
    email: String,
    onEmailChange: (String) -> Unit,
    displayName: String,
    onDisplayNameChange: (String) -> Unit,
    verificationCode: String,
    onVerificationCodeChange: (String) -> Unit,
    inviteCode: String,
    onInviteCodeChange: (String) -> Unit,
    password: String,
    onPasswordChange: (String) -> Unit,
    confirmPassword: String,
    onConfirmPasswordChange: (String) -> Unit,
    showPassword: Boolean,
    onShowPasswordChange: (Boolean) -> Unit,
    showConfirmPassword: Boolean,
    onShowConfirmPasswordChange: (Boolean) -> Unit,
    state: AuthUiState,
    viewModel: AuthViewModel,
    onSubmit: () -> Unit,
): Unit {
    val minimumPasswordLength = if (isRegisterMode) 8 else 1
    val inviteRequired = isRegisterMode && state.providers?.inviteRequired == true
    val inviteMissing = inviteRequired && inviteCode.isBlank()
    val emailError = email.isNotBlank() &&
        !Patterns.EMAIL_ADDRESS.matcher(email.trim()).matches()
    val verificationCodeError = isRegisterMode &&
        verificationCode.isNotBlank() &&
        (verificationCode.length != 6 || verificationCode.any { !it.isDigit() })
    val confirmPasswordError = isRegisterMode &&
        confirmPassword.isNotBlank() &&
        confirmPassword != password
    val canSubmit = !state.isBusy &&
        email.isNotBlank() &&
        !emailError &&
        password.length >= minimumPasswordLength &&
        (!isRegisterMode || (
            confirmPassword == password &&
                !inviteMissing &&
                verificationCode.length == 6 &&
                verificationCode.all { it.isDigit() }
            ))

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(13.dp),
    ) {
        if (isRegisterMode) {
            OutlinedTextField(
                value = displayName,
                onValueChange = onDisplayNameChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.auth_nickname_label)) },
                placeholder = { Text(stringResource(R.string.auth_nickname_placeholder)) },
                singleLine = true,
                shape = RoundedCornerShape(10.dp),
            )
        }
        OutlinedTextField(
            value = email,
            onValueChange = onEmailChange,
            modifier = Modifier.fillMaxWidth(),
            label = { Text(stringResource(R.string.auth_email_label)) },
            placeholder = { Text(stringResource(R.string.auth_email_placeholder)) },
            singleLine = true,
            isError = emailError,
            supportingText = if (emailError) {
                { Text(stringResource(R.string.auth_email_invalid)) }
            } else {
                null
            },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
            shape = RoundedCornerShape(10.dp),
        )
        if (isRegisterMode && state.providers?.inviteRequired == true) {
            OutlinedTextField(
                value = inviteCode,
                onValueChange = onInviteCodeChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.auth_invite_label)) },
                placeholder = { Text(stringResource(R.string.auth_invite_placeholder)) },
                singleLine = true,
                isError = inviteMissing,
                supportingText = if (inviteMissing) {
                    { Text(stringResource(R.string.auth_error_invite_required)) }
                } else {
                    null
                },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
                shape = RoundedCornerShape(10.dp),
            )
        }
        if (isRegisterMode) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.Bottom,
            ) {
                OutlinedTextField(
                    value = verificationCode,
                    onValueChange = onVerificationCodeChange,
                    modifier = Modifier.weight(0.58f),
                    label = { Text(stringResource(R.string.auth_code_label)) },
                    placeholder = { Text(stringResource(R.string.auth_code_placeholder)) },
                    singleLine = true,
                    maxLines = 1,
                    isError = verificationCodeError,
                    supportingText = if (verificationCodeError) {
                        { Text(stringResource(R.string.auth_code_digits)) }
                    } else {
                        null
                    },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    shape = RoundedCornerShape(10.dp),
                )
                OutlinedButton(
                    onClick = { viewModel.requestVerificationCode(email.trim(), inviteCode.trim()) },
                    modifier = Modifier
                        .weight(0.42f)
                        .height(56.dp),
                    enabled = !state.isBusy &&
                        !state.isSendingVerificationCode &&
                        state.verificationCodeCooldownSeconds == 0 &&
                        email.isNotBlank() && !emailError && !inviteMissing,
                    contentPadding = PaddingValues(horizontal = 7.dp),
                    shape = RoundedCornerShape(10.dp),
                ) {
                    Text(
                        when {
                            state.isSendingVerificationCode -> stringResource(R.string.relay_ui_sending)
                            state.verificationCodeCooldownSeconds > 0 ->
                                "${state.verificationCodeCooldownSeconds}s"
                            else -> stringResource(R.string.auth_send_code)
                        },
                    )
                }
            }
        }
        OutlinedTextField(
            value = password,
            onValueChange = onPasswordChange,
            modifier = Modifier.fillMaxWidth(),
            label = { Text(stringResource(R.string.auth_password_label)) },
            placeholder = {
                Text(if (isRegisterMode) stringResource(R.string.auth_password_placeholder_register) else stringResource(R.string.auth_password_placeholder))
            },
            singleLine = true,
            isError = isRegisterMode && password.isNotEmpty() &&
                password.length < minimumPasswordLength,
            visualTransformation = if (showPassword) {
                VisualTransformation.None
            } else {
                PasswordVisualTransformation()
            },
            trailingIcon = {
                TextButton(
                    onClick = { onShowPasswordChange(!showPassword) },
                    contentPadding = PaddingValues(horizontal = 8.dp),
                ) {
                    Text(if (showPassword) stringResource(R.string.auth_hide) else stringResource(R.string.auth_show), color = TextMuted)
                }
            },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            shape = RoundedCornerShape(10.dp),
        )
        if (isRegisterMode) {
            Text(
                text = stringResource(R.string.auth_password_hint),
                color = TextMuted,
                style = MaterialTheme.typography.labelSmall,
                modifier = Modifier.padding(start = 4.dp),
            )
            OutlinedTextField(
                value = confirmPassword,
                onValueChange = onConfirmPasswordChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text(stringResource(R.string.auth_confirm_password_label)) },
                placeholder = { Text(stringResource(R.string.auth_confirm_password_placeholder)) },
                singleLine = true,
                isError = confirmPasswordError,
                supportingText = if (confirmPasswordError) {
                    { Text(stringResource(R.string.auth_confirm_password_mismatch)) }
                } else {
                    null
                },
                visualTransformation = if (showConfirmPassword) {
                    VisualTransformation.None
                } else {
                    PasswordVisualTransformation()
                },
                trailingIcon = {
                    TextButton(
                        onClick = { onShowConfirmPasswordChange(!showConfirmPassword) },
                        contentPadding = PaddingValues(horizontal = 8.dp),
                    ) {
                        Text(
                            if (showConfirmPassword) stringResource(R.string.auth_hide) else stringResource(R.string.auth_show),
                            color = TextMuted,
                        )
                    }
                },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                shape = RoundedCornerShape(10.dp),
            )
        }
        Button(
            onClick = onSubmit,
            modifier = Modifier
                .fillMaxWidth()
                .height(48.dp),
            enabled = canSubmit,
            shape = RoundedCornerShape(10.dp),
        ) {
            Text(
                when {
                    state.isBusy -> stringResource(R.string.auth_processing)
                    isRegisterMode -> stringResource(R.string.auth_create_account)
                    else -> stringResource(R.string.auth_login)
                },
            )
        }
    }
}

@Composable
private fun AuthModeSwitch(
    isRegisterMode: Boolean,
    onToggle: () -> Unit,
    enabled: Boolean,
): Unit {
    Row(
        modifier = Modifier.padding(top = 12.dp),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = if (isRegisterMode) stringResource(R.string.auth_have_account) else stringResource(R.string.auth_no_account),
            color = TextMuted,
            style = MaterialTheme.typography.bodySmall,
        )
        TextButton(
            onClick = onToggle,
            enabled = enabled,
            contentPadding = PaddingValues(horizontal = 5.dp),
        ) {
            Text(
                text = if (isRegisterMode) stringResource(R.string.auth_back_to_login) else stringResource(R.string.auth_register_now),
                color = DeepTealHover,
            )
        }
    }
}

@Composable
private fun AuthProviderButtons(
    providers: List<AuthProviderInfo>,
    onOpenProvider: (String) -> Unit,
): Unit {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 18.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            HorizontalDivider(
                modifier = Modifier.weight(1f),
                color = Border,
            )
            Text(
                text = stringResource(R.string.auth_other_methods),
                color = TextMuted,
                style = MaterialTheme.typography.labelSmall,
                modifier = Modifier.padding(horizontal = 10.dp),
            )
            HorizontalDivider(
                modifier = Modifier.weight(1f),
                color = Border,
            )
        }
        providers.chunked(2).forEach { rowProviders ->
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                rowProviders.forEach { provider ->
                    OutlinedButton(
                        onClick = { onOpenProvider(provider.provider) },
                        modifier = Modifier
                            .weight(1f)
                            .height(48.dp),
                        shape = RoundedCornerShape(10.dp),
                    ) {
                        Text(provider.label)
                    }
                }
                if (rowProviders.size == 1) {
                    Spacer(modifier = Modifier.weight(1f))
                }
            }
        }
    }
}
