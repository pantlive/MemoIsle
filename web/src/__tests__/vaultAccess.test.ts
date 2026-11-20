// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getVaultAccess,
  reportVaultUnlockFailure,
  requestVaultAccessCode,
  updateVaultSecurity,
  verifyVaultAccess,
} from "../api";
import { formatTotpSecret, vaultGate } from "../vaultAccess";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("密码库门禁阶段", () => {
  it("把白名单和二次验证错误码收成界面阶段", () => {
    expect(vaultGate("vault_ip_blocked")).toBe("ip_blocked");
    expect(vaultGate("vault_ip_allowlist_empty")).toBe("ip_blocked");
    expect(vaultGate("vault_step_up_required")).toBe("step_up");
    expect(vaultGate("vault_code_invalid")).toBeNull();
    expect(vaultGate(undefined)).toBeNull();
  });
});

describe("身份验证器密钥分组", () => {
  it("每 4 个字符空一格", () => {
    expect(formatTotpSecret("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP")).toBe(
      "JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP",
    );
  });

  it("长度不是 4 的倍数时最后一组保留余下字符", () => {
    expect(formatTotpSecret("ABCDEFGHIJ")).toBe("ABCD EFGH IJ");
    expect(formatTotpSecret("ABC")).toBe("ABC");
  });

  it("空串返回空串", () => {
    expect(formatTotpSecret("")).toBe("");
  });
});

describe("密码库授权接口", () => {
  it("网页请求带客户端头，并提交验证码和追加的白名单", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/vault/access") && init?.method === undefined) {
        return jsonResponse({
          granted: false,
          expires_at: null,
          totp_enabled: false,
          hours: 4,
          client_type: "web",
          client_token: null,
        });
      }
      if (url.endsWith("/vault/access/code")) {
        return jsonResponse({ detail: "验证码已发送到 owner@example.com" });
      }
      if (url.endsWith("/vault/access/verify")) {
        return jsonResponse({
          granted: true,
          expires_at: "2026-11-17T12:00:00Z",
          totp_enabled: false,
          hours: 4,
          client_type: "web",
          client_token: null,
        });
      }
      if (url.endsWith("/vault/unlock-failed")) {
        return jsonResponse({ sent: true });
      }
      if (url.endsWith("/vault/security")) {
        return jsonResponse({
          totp_enabled: false,
          env_allowlist: ["203.0.113.0/24"],
          user_allowlist: ["198.51.100.20/32"],
          web_grant_hours: 4,
          mobile_grant_hours: 24,
        });
      }
      return jsonResponse({ detail: "未模拟的接口" }, 500);
    });
    vi.stubGlobal("fetch", fetchMock);

    const access = await getVaultAccess();
    expect(access.granted).toBe(false);
    expect(access.hours).toBe(4);
    await expect(requestVaultAccessCode()).resolves.toBe("验证码已发送到 owner@example.com");
    const verified = await verifyVaultAccess("email", "123456");
    expect(verified.client_token).toBeNull();
    await expect(reportVaultUnlockFailure()).resolves.toBe(true);
    const security = await updateVaultSecurity(["198.51.100.20/32"]);
    expect(security.env_allowlist).toEqual(["203.0.113.0/24"]);
    expect(security.user_allowlist).toEqual(["198.51.100.20/32"]);

    for (const call of fetchMock.mock.calls) {
      const init = call[1] as RequestInit;
      const headers = init.headers as Record<string, string>;
      expect(headers["X-MemoIsle-Client"]).toBe("web");
      expect(init.credentials).toBe("include");
    }
    const verifyCall = fetchMock.mock.calls.find((call) => String(call[0]).endsWith("/vault/access/verify"));
    expect(JSON.parse(String((verifyCall?.[1] as RequestInit).body))).toEqual({
      method: "email",
      code: "123456",
    });
    const securityCall = fetchMock.mock.calls.find((call) => (
      String(call[0]).endsWith("/vault/security")
    ));
    expect((securityCall?.[1] as RequestInit).method).toBe("PUT");
  });
});
