export type VaultGate = "ip_blocked" | "step_up";

/** 把密码库门禁错误码收成界面阶段。其他错误留给原来的失败提示。 */
export function vaultGate(code: string | undefined): VaultGate | null {
  if (code === "vault_ip_blocked" || code === "vault_ip_allowlist_empty") {
    return "ip_blocked";
  }
  if (code === "vault_step_up_required") return "step_up";
  return null;
}

/** 身份验证器密钥每 4 个字符空一格，方便手动抄写。复制时仍用原始密钥。 */
export function formatTotpSecret(secret: string): string {
  const compact = secret.replace(/\s+/g, "");
  return compact.match(/.{1,4}/g)?.join(" ") ?? "";
}
