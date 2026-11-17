export type VaultGate = "ip_blocked" | "step_up";

/** 把密码库门禁错误码收成界面阶段。其他错误留给原来的失败提示。 */
export function vaultGate(code: string | undefined): VaultGate | null {
  if (code === "vault_ip_blocked" || code === "vault_ip_allowlist_empty") {
    return "ip_blocked";
  }
  if (code === "vault_step_up_required") return "step_up";
  return null;
}
