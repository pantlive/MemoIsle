import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { inflateRawSync } from "node:zlib";

import {
  buildZip,
  parseOrigin,
  storeBackground,
  storeManifest,
} from "../scripts/build-store-package.mjs";

const manifest = JSON.parse(
  await readFile(new URL("../manifest.json", import.meta.url), "utf8"),
);
const background = await readFile(new URL("../background.js", import.meta.url), "utf8");
const web = new URL("https://memo.example.com/");
const api = new URL("https://api.example.com/api/v1");

test("商店版只信任正式 Web 地址，去掉本机开发地址", () => {
  const result = storeManifest(manifest, web, api);
  assert.deepEqual(result.content_scripts[0].matches, ["https://memo.example.com/*"]);
  assert.ok(result.host_permissions.includes("https://api.example.com/*"));
  assert.ok(result.host_permissions.every((pattern) => !/localhost|127\.0\.0\.1/.test(pattern)));
  // 原清单不被修改。
  assert.ok(manifest.content_scripts[0].matches.some((pattern) => pattern.includes("localhost")));
});

test("商店版默认地址换成正式地址", () => {
  const result = storeBackground(background, web, api);
  assert.match(result, /apiBaseUrl: "https:\/\/api\.example\.com\/api\/v1"/);
  assert.match(result, /webBaseUrl: "https:\/\/memo\.example\.com\/"/);
  assert.doesNotMatch(result, /webBaseUrl: "http:\/\/localhost:5173\/"/);
});

test("拒绝明文 http 和本机地址", () => {
  assert.throws(() => parseOrigin("http://memo.example.com", "--web"), /https/);
  assert.throws(() => parseOrigin("https://localhost:5173", "--web"), /本机/);
  assert.throws(() => parseOrigin("不是地址", "--web"), /有效/);
});

test("ZIP 可以按中央目录读回原文件", () => {
  const entries = [
    { name: "manifest.json", data: Buffer.from("{\"a\":1}") },
    { name: "icons/icon16.png", data: Buffer.from([1, 2, 3, 4, 5]) },
  ];
  const zip = buildZip(entries);
  const endOffset = zip.length - 22;
  assert.equal(zip.readUInt32LE(endOffset), 0x06054b50);
  assert.equal(zip.readUInt16LE(endOffset + 10), 2);
  let pointer = zip.readUInt32LE(endOffset + 16);
  for (const entry of entries) {
    assert.equal(zip.readUInt32LE(pointer), 0x02014b50);
    const compressedSize = zip.readUInt32LE(pointer + 20);
    const nameLength = zip.readUInt16LE(pointer + 28);
    const localOffset = zip.readUInt32LE(pointer + 42);
    const name = zip.subarray(pointer + 46, pointer + 46 + nameLength).toString();
    assert.equal(name, entry.name);
    const dataStart = localOffset + 30 + zip.readUInt16LE(localOffset + 26);
    const data = inflateRawSync(zip.subarray(dataStart, dataStart + compressedSize));
    assert.deepEqual(data, entry.data);
    pointer += 46 + nameLength;
  }
});
