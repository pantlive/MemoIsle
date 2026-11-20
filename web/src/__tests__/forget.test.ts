import { describe, expect, it } from "vitest";

import { isStandaloneView, readAppRoute } from "../appRoute";
import {
  FORGET_CONTENT_MAX,
  FORGET_MAX_ATTACHMENT_BYTES,
  FORGET_TITLE_MAX,
  forgetDisplayTitle,
  forgetFileError,
  forgetTextError,
  forgetTextLength,
  formatForgetBytes,
  isForgetImage,
} from "../forget";
import { navigation } from "../workspaceViews";

describe("易忘事项入口", () => {
  it("侧栏工具里有独立页面", () => {
    expect(navigation.find((item) => item.action === "forget")).toMatchObject({
      label: "易忘事项",
      icon: "forget",
    });
    expect(readAppRoute("?view=forget&item=abc")).toEqual({ view: "forget", item: null });
    expect(isStandaloneView("forget")).toBe(true);
  });
});

describe("易忘事项文字和附件校验", () => {
  it("按字数限制标题和正文，空文本可以只放附件", () => {
    expect(forgetTextError("", "")).toBeNull();
    expect(forgetTextError("  标题  ", "正文")).toBeNull();
    expect(forgetTextError("标".repeat(FORGET_TITLE_MAX), "")).toBeNull();
    expect(forgetTextError("标".repeat(FORGET_TITLE_MAX + 1), "")).toBe("标题最多 100 个字");
    expect(forgetTextError("", "文".repeat(FORGET_CONTENT_MAX + 1))).toBe("正文最多 10000 个字");
    expect(forgetTextLength("😀")).toBe(1);
  });

  it("挡住空文件和超过 20 MB 的附件", () => {
    expect(forgetFileError({ size: 1 })).toBeNull();
    expect(forgetFileError({ size: FORGET_MAX_ATTACHMENT_BYTES })).toBeNull();
    expect(forgetFileError({ size: 0 })).toBe("附件内容不能为空");
    expect(forgetFileError({ size: FORGET_MAX_ATTACHMENT_BYTES + 1 })).toBe("附件不能超过 20 MB");
  });

  it("显示标题、大小和图片标记", () => {
    expect(forgetDisplayTitle("  ")).toBe("未命名");
    expect(forgetDisplayTitle(" 钥匙 ")).toBe("钥匙");
    expect(formatForgetBytes(12)).toBe("12 B");
    expect(formatForgetBytes(2048)).toBe("2 KB");
    expect(formatForgetBytes(1.5 * 1024 * 1024)).toBe("1.5 MB");
    expect(isForgetImage({ kind: "image" })).toBe(true);
    expect(isForgetImage({ kind: "file" })).toBe(false);
  });
});
