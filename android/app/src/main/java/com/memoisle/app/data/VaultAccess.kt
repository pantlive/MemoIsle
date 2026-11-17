package com.memoisle.app.data

/** 把密码库门禁错误码收成界面阶段。其他错误留给原来的失败提示。 */
fun vaultGate(code: String?): String? = when (code) {
    "vault_ip_blocked", "vault_ip_allowlist_empty" -> "ip_blocked"
    "vault_step_up_required" -> "step_up"
    else -> null
}
