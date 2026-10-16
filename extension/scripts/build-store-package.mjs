// 生成上架 Chrome 网上应用店 / Edge 加载项商店的 ZIP。
//
// 用法：node scripts/build-store-package.mjs --web https://memo.example.com [--api https://memo.example.com/api/v1]
//
// 本地开发版只信任 localhost 的 Vite 端口；商店版改为只信任正式的 Web 地址，
// 并把默认的 Web / API 地址换成正式地址。生成的 ZIP 里 manifest.json 位于根目录。

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { crc32, deflateRawSync } from "node:zlib";

const EXTENSION_DIRECTORY = new URL("../", import.meta.url);
const RUNTIME_FILES = [
  "manifest.json",
  "background.js",
  "content.js",
  "icons/icon16.png",
  "icons/icon32.png",
  "icons/icon48.png",
  "icons/icon128.png",
];
const LOCAL_HOST_PATTERN = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//;

export function parseOrigin(value, name) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${name} 不是有效的地址：${value}`);
  }
  if (parsed.protocol !== "https:") {
    throw new Error(`${name} 必须是 https 地址，商店版不连接明文 http。`);
  }
  if (LOCAL_HOST_PATTERN.test(parsed.href)) {
    throw new Error(`${name} 不能是本机地址。`);
  }
  return parsed;
}

export function storeManifest(manifest, webUrl, apiUrl) {
  const result = structuredClone(manifest);
  result.content_scripts = result.content_scripts.map((script) => ({
    ...script,
    matches: [`${webUrl.origin}/*`],
  }));
  result.host_permissions = [
    ...new Set([
      ...result.host_permissions.filter((pattern) => !LOCAL_HOST_PATTERN.test(pattern)),
      `${apiUrl.origin}/*`,
    ]),
  ];
  return result;
}

export function storeBackground(source, webUrl, apiUrl) {
  const replacements = [
    [/apiBaseUrl: "http:\/\/127\.0\.0\.1:8000\/api\/v1"/, `apiBaseUrl: ${JSON.stringify(apiUrl.href.replace(/\/$/, ""))}`],
    [/webBaseUrl: "http:\/\/localhost:5173\/"/, `webBaseUrl: ${JSON.stringify(`${webUrl.origin}/`)}`],
  ];
  let result = source;
  for (const [pattern, replacement] of replacements) {
    if (!pattern.test(result)) {
      throw new Error(`background.js 里找不到默认地址 ${pattern}，请同步更新打包脚本。`);
    }
    result = result.replace(pattern, replacement);
  }
  return result;
}

// 最小的 ZIP 写入：每个文件 deflate 压缩，带本地文件头和中央目录。
export function buildZip(entries) {
  const localParts = [];
  const centralParts = [];
  let offset = 0;
  // 固定时间戳（1980-01-01），同样的输入得到同样的包。
  const dosTime = 0;
  const dosDate = (0 << 9) | (1 << 5) | 1;
  for (const { name, data } of entries) {
    const nameBytes = Buffer.from(name, "utf8");
    const compressed = deflateRawSync(data, { level: 9 });
    const checksum = crc32(data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0x0800, 6);
    local.writeUInt16LE(8, 8);
    local.writeUInt16LE(dosTime, 10);
    local.writeUInt16LE(dosDate, 12);
    local.writeUInt32LE(checksum, 14);
    local.writeUInt32LE(compressed.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(nameBytes.length, 26);
    local.writeUInt16LE(0, 28);
    localParts.push(local, nameBytes, compressed);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0x0800, 8);
    central.writeUInt16LE(8, 10);
    central.writeUInt16LE(dosTime, 12);
    central.writeUInt16LE(dosDate, 14);
    central.writeUInt32LE(checksum, 16);
    central.writeUInt32LE(compressed.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(nameBytes.length, 28);
    central.writeUInt32LE(offset, 42);
    centralParts.push(central, nameBytes);
    offset += local.length + nameBytes.length + compressed.length;
  }
  const centralSize = centralParts.reduce((sum, part) => sum + part.length, 0);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(centralSize, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...localParts, ...centralParts, end]);
}

function readArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (key === "--web" || key === "--api" || key === "--out") {
      args[key.slice(2)] = argv[index + 1];
      index += 1;
    }
  }
  return args;
}

export async function buildStorePackage({ web, api, out }) {
  if (!web) throw new Error("请用 --web 指定正式的 MemoIsle Web 地址，例如 --web https://memo.example.com");
  const webUrl = parseOrigin(web, "--web");
  const apiUrl = parseOrigin(api || new URL("/api/v1", webUrl).href, "--api");
  const manifest = JSON.parse(await readFile(new URL("manifest.json", EXTENSION_DIRECTORY), "utf8"));
  const entries = [];
  for (const name of RUNTIME_FILES) {
    let data = await readFile(new URL(name, EXTENSION_DIRECTORY));
    if (name === "manifest.json") {
      data = Buffer.from(`${JSON.stringify(storeManifest(manifest, webUrl, apiUrl), null, 2)}\n`);
    } else if (name === "background.js") {
      data = Buffer.from(storeBackground(data.toString("utf8"), webUrl, apiUrl));
    }
    entries.push({ name, data });
  }
  const outDirectory = new URL(out ? `${out.replace(/\/?$/, "/")}` : "dist/", EXTENSION_DIRECTORY);
  await mkdir(outDirectory, { recursive: true });
  const target = new URL(`memoisle-extension-store-${manifest.version}.zip`, outDirectory);
  await writeFile(target, buildZip(entries));
  return fileURLToPath(target);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  try {
    const target = await buildStorePackage(readArgs(process.argv.slice(2)));
    console.log(`已生成：${target}`);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
