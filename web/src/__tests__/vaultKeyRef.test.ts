// @vitest-environment happy-dom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import VaultItemDialog from "../VaultItemDialog";
import {
  emptyVaultItem,
  normalizeItemData,
  normalizeVaultItemForSave,
  planVaultImport,
  resolveServerPrivateKey,
  serversReferencingKey,
  stampSecretChange,
  type VaultEntry,
  type VaultItemData,
  type VaultSecretData,
  type VaultServerData,
} from "../vault";
import { collectVaultReminders, lastChangedAt, reminderLabels } from "../vaultReminders";

function server(fields: Partial<VaultServerData> = {}): VaultServerData {
  return {
    ...emptyVaultItem("server") as VaultServerData,
    title: "示例服务器",
    host: "vps.example.com",
    authMethod: "key",
    ...fields,
  };
}

function secret(fields: Partial<VaultSecretData> = {}): VaultSecretData {
  return {
    ...emptyVaultItem("secret") as VaultSecretData,
    title: "示例密钥",
    secret: "example-secret-placeholder",
    ...fields,
  };
}

function entry(id: string, data: VaultItemData, createdAt = "2026-01-01T00:00:00Z"): VaultEntry {
  return { id, data, createdAt, updatedAt: createdAt, version: 1 };
}

describe("私钥引用规范化与解析", () => {
  it.each([undefined, null, 123, false, {}])("将缺失或非字符串引用 %s 补为空字符串", (privateKeyRef) => {
    const raw: Record<string, unknown> = { kind: "server" };
    if (privateKeyRef !== undefined) raw.privateKeyRef = privateKeyRef;
    expect(normalizeItemData(raw)).toMatchObject({ privateKeyRef: "", privateKey: "" });
    expect(emptyVaultItem("server")).toMatchObject({ privateKeyRef: "" });
  });

  it("规范化保留引用，保存时清空内联私钥且不修改草稿", () => {
    const draft = server({ privateKeyRef: "key", privateKey: "example-inline-placeholder" });
    expect(normalizeItemData({ ...draft })).toMatchObject({ privateKeyRef: "key", privateKey: draft.privateKey });
    expect(normalizeVaultItemForSave(draft)).toMatchObject({ privateKeyRef: "key", privateKey: "" });
    expect(draft.privateKey).toBe("example-inline-placeholder");
    expect(normalizeVaultItemForSave({ ...draft, authMethod: "password" })).toMatchObject({
      privateKeyRef: "key", privateKey: draft.privateKey, authMethod: "password",
    });
  });

  it("读取引用的最新内容和标题，不使用旧的内联值", () => {
    const data = server({ privateKeyRef: "key", privateKey: "example-old-placeholder" });
    const target = entry("key", secret());
    expect(resolveServerPrivateKey(data, [target])).toEqual({
      value: "example-secret-placeholder", refTitle: "示例密钥", missing: false,
    });
    expect(resolveServerPrivateKey(data, [entry("key", secret({ secret: "example-rotated-placeholder" }))]).value)
      .toBe("example-rotated-placeholder");
    expect(resolveServerPrivateKey(data, [entry("key", secret({ secret: "" }))])).toEqual({
      value: "", refTitle: "示例密钥", missing: false,
    });
  });

  it("引用缺失或指向其他类型时标记失效，不回退到内联值", () => {
    const data = server({ privateKeyRef: "key", privateKey: "example-old-placeholder" });
    for (const entries of [[], [entry("key", emptyVaultItem("login"))]]) {
      expect(resolveServerPrivateKey(data, entries)).toEqual({ value: "", refTitle: null, missing: true });
    }
  });

  it("无引用时读取内联私钥", () => {
    expect(resolveServerPrivateKey(server({ privateKey: "example-inline-placeholder" }), [])).toEqual({
      value: "example-inline-placeholder", refTitle: null, missing: false,
    });
  });

  it("按 ID 查找引用服务器，包括密码模式下保留的引用", () => {
    const active = entry("server", server({ privateKeyRef: "key" }));
    const retained = entry("password-server", server({ authMethod: "password", privateKeyRef: "key" }));
    const entries = [active, retained, entry("other", server()), entry("key", secret())];
    expect(serversReferencingKey("key", entries)).toEqual([active, retained]);
    expect(serversReferencingKey("missing", entries)).toEqual([]);
  });
});

describe("凭据更换时间", () => {
  const now = "2026-11-05T12:00:00Z";
  const previous = server({ privateKeyRef: "old-key", changedAt: "2026-01-01T00:00:00Z" });

  it("更换引用目标或新建引用时记录时间", () => {
    const next = { ...previous, privateKeyRef: "new-key" };
    expect(stampSecretChange(previous, next, now)).toMatchObject({ changedAt: now });
    expect(stampSecretChange(null, next, now)).toMatchObject({ changedAt: now });
  });

  it("直接填写与引用之间切换都记录时间", () => {
    const direct = server({ privateKey: "example-inline-placeholder" });
    expect(stampSecretChange(direct, { ...direct, privateKeyRef: "key" }, now)).toMatchObject({ changedAt: now });
    expect(stampSecretChange(previous, direct, now)).toMatchObject({ changedAt: now });
  });

  it("引用不变时修改草稿私钥或标题不算更换", () => {
    const next = { ...previous, privateKey: "example-ignored-placeholder", title: "新标题" };
    expect(stampSecretChange(previous, next, now)).toBe(next);
  });

  it("密码模式忽略保留的引用，仍按密码变化记录时间", () => {
    const before = server({ authMethod: "password", password: "example-password-placeholder", privateKeyRef: "key" });
    const next = { ...before, privateKeyRef: "other" };
    expect(stampSecretChange(before, next, now)).toBe(next);
    expect(stampSecretChange(before, { ...next, password: "example-new-password-placeholder" }, now))
      .toMatchObject({ changedAt: now });
  });
});

describe("备份导入计划", () => {
  it("先分配密钥 ID，再重映射位于密钥之前的服务器，并对备份内重复项去重", () => {
    const data = server({ privateKeyRef: "old-key", privateKey: "example-ignored-placeholder" });
    const backup = [
      { id: "old-server", data },
      { id: "duplicate-server", data: { ...data, privateKeyRef: "duplicate-key" } },
      { id: "old-key", data: secret() },
      { id: "duplicate-key", data: secret() },
    ];
    let counter = 0;
    const newId = vi.fn(() => `new-${++counter}`);
    const original = structuredClone(backup);
    const plan = planVaultImport(backup, [], newId);
    expect(plan).toEqual({ items: [
      { id: "new-1", data: secret() },
      { id: "new-2", data: { ...data, privateKeyRef: "new-1", privateKey: "" } },
    ], skipped: 2 });
    expect(newId).toHaveBeenCalledTimes(2);
    expect(backup).toEqual(original);
    expect(resolveServerPrivateKey(plan.items[1].data as VaultServerData, plan.items).value).toBe(secret().secret);
  });

  it("重复密钥映射到现有条目，服务器在改写引用之后与已有服务器去重", () => {
    const existing = [entry("existing-key", secret()), entry("existing-server", server({ privateKeyRef: "existing-key" }))];
    const newId = vi.fn(() => "unused");
    expect(planVaultImport([
      { id: "old-server", data: server({ privateKeyRef: "old-key" }) },
      { id: "old-key", data: secret() },
    ], existing, newId)).toEqual({ items: [], skipped: 2 });
    expect(newId).not.toHaveBeenCalled();
  });

  it("新服务器引用去重后的现有密钥，重复导入不会增加条目", () => {
    const backup = [
      { id: "old-server", data: server({ privateKeyRef: "old-key" }) },
      { id: "old-key", data: secret() },
    ];
    const existing = [entry("existing-key", secret())];
    const plan = planVaultImport(backup, existing, () => "new-server");
    expect(plan.skipped).toBe(1);
    expect(plan.items).toEqual([{ id: "new-server", data: server({ privateKeyRef: "existing-key" }) }]);
    expect(planVaultImport(backup, [...existing, entry(plan.items[0].id, plan.items[0].data)], () => "unused"))
      .toEqual({ items: [], skipped: 2 });
  });

  it("无法映射的引用保留旧 ID，继续表现为失效引用", () => {
    const plan = planVaultImport([{ id: "old-server", data: server({ privateKeyRef: "missing-key" }) }], [], () => "new-server");
    expect(plan.items[0].data).toMatchObject({ privateKeyRef: "missing-key" });
    expect(resolveServerPrivateKey(plan.items[0].data as VaultServerData, plan.items).missing).toBe(true);
  });

  it("无引用服务器和其他类型仍然按内容去重", () => {
    const direct = server({ privateKey: "example-inline-placeholder" });
    const login = emptyVaultItem("login");
    const newId = vi.fn(() => "new-server");
    expect(planVaultImport([
      { id: "login", data: login },
      { id: "direct", data: direct },
      { id: "duplicate", data: direct },
    ], [entry("existing-login", login)], newId)).toEqual({
      items: [{ id: "new-server", data: direct }], skipped: 2,
    });
    expect(newId).toHaveBeenCalledTimes(1);
  });
});

describe("私钥引用提醒", () => {
  const now = new Date(2026, 10, 5, 12);

  it("失效引用产生 danger 提醒，不因旧私钥或密码产生轮换与到期提醒", () => {
    const data = server({ privateKeyRef: "gone", privateKey: "example-old-placeholder", password: "example-password-placeholder",
      rotateDays: 30, expiresOn: "2026-01-01" });
    expect(collectVaultReminders([entry("server", data)], now)).toEqual([{
      entryId: "server", title: data.title, type: "missing-key", level: "danger",
      message: "引用的密钥已被删除，请重新选择或直接填写私钥。",
    }]);
    expect(reminderLabels["missing-key"]).toBe("密钥缺失");
  });

  it("有效引用按原密钥 changedAt 计算，轮换后服务器提醒自动消失", () => {
    const target = entry("key", secret({ changedAt: "2026-10-01T12:00:00Z" }));
    const host = entry("server", server({ privateKeyRef: "key", rotateDays: 30, changedAt: "2026-11-05T12:00:00Z" }));
    expect(lastChangedAt(host, [target, host])).toBe("2026-10-01T12:00:00Z");
    expect(collectVaultReminders([host, target], now)).toContainEqual(expect.objectContaining({
      entryId: "server", type: "rotate", message: "已 35 天没有更换，设定为每 30 天换一次。",
    }));
    const rotated = entry("key", secret({ changedAt: "2026-11-04T12:00:00Z" }));
    expect(collectVaultReminders([host, rotated], now)).toEqual([]);
  });

  it("原密钥没有 changedAt 时使用其 createdAt，而非服务器时间", () => {
    const host = entry("server", server({ privateKeyRef: "key", rotateDays: 30 }), "2026-11-05T12:00:00Z");
    const target = entry("key", secret(), "2026-10-01T12:00:00Z");
    expect(lastChangedAt(host, [target])).toBe(target.createdAt);
    expect(collectVaultReminders([host, target], now)).toContainEqual(expect.objectContaining({ entryId: "server", type: "rotate" }));
  });

  it("空密钥引用有效但无凭据，密码模式不会产生密钥缺失提醒", () => {
    const host = entry("server", server({ privateKeyRef: "key", rotateDays: 30, expiresOn: "2026-01-01" }));
    expect(collectVaultReminders([host, entry("key", secret({ secret: "" }))], now)).toEqual([]);
    const passwordHost = entry("server", server({
      authMethod: "password",
      privateKeyRef: "gone",
      changedAt: "2026-11-04T12:00:00Z",
      rotateDays: 30,
      password: "example-password-placeholder",
    }));
    expect(collectVaultReminders([passwordHost], now)).toEqual([]);
  });
});

describe("私钥来源编辑界面", () => {
  let root: Root | undefined;
  let container: HTMLDivElement | undefined;

  afterEach(() => {
    if (root) act(() => root?.unmount());
    container?.remove();
    root = undefined;
    container = undefined;
    vi.unstubAllGlobals();
  });

  function renderDialog(
    initial: VaultServerData,
    secretEntries: { id: string; title: string; secret: string }[],
  ): { host: HTMLDivElement; onCopy: ReturnType<typeof vi.fn>; onSave: ReturnType<typeof vi.fn> } {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    const onCopy = vi.fn();
    const onSave = vi.fn();
    act(() => root?.render(createElement(VaultItemDialog, {
      initial, secretEntries, isNew: false, changedAt: null, reminders: [], busy: false, error: "",
      onCopy, onSave, onDelete: vi.fn(), onClose: vi.fn(),
    })));
    return { host: container, onCopy, onSave };
  }

  it("切换来源保留内联草稿，选择按标题排序，复制当前选中的密钥", () => {
    const draft = server({ privateKey: "example-inline-placeholder" });
    const { host, onCopy, onSave } = renderDialog(draft, [
      { id: "b", title: "B", secret: "example-b-placeholder" },
      { id: "a", title: "A", secret: "example-a-placeholder" },
    ]);
    const radios = host.querySelectorAll<HTMLInputElement>('input[name="server-key-source"]');
    act(() => radios[1].click());
    const select = host.querySelector<HTMLSelectElement>("select")!;
    expect([...select.options].map((option) => option.text)).toEqual(["请选择密钥", "A", "B"]);
    expect(host.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled).toBe(true);
    act(() => {
      select.value = "b";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(host.textContent).toContain("原密钥更新后这里会自动使用新内容");
    const copy = host.querySelector<HTMLButtonElement>('button[aria-label="复制引用的私钥"]')!;
    act(() => copy.click());
    expect(onCopy).toHaveBeenCalledWith("example-b-placeholder", "私钥");
    act(() => host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ privateKeyRef: "b", privateKey: draft.privateKey }));
    act(() => radios[0].click());
    act(() => host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({ privateKeyRef: "", privateKey: draft.privateKey }));
  });

  it("没有密钥时禁用选择，并对失效引用显示警告", () => {
    const { host } = renderDialog(server({ privateKeyRef: "gone" }), []);
    expect(host.querySelector<HTMLSelectElement>("select")!.disabled).toBe(true);
    expect(host.textContent).toContain("还没有保存的密钥，请先新建一个「密钥」条目。");
    expect(host.querySelector('[role="alert"]')?.textContent).toBe("引用的密钥已被删除，请重新选择");
    expect(host.textContent).not.toContain("原密钥更新后这里会自动使用新内容");
    expect(host.querySelector('input[aria-label="私钥口令（可选）"]')).not.toBeNull();
  });
});
