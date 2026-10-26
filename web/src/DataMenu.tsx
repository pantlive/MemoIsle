import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";

import type { DataExportFormat } from "./api";
import { androidDownloadUrl, browserExtensionArchiveFilename, browserExtensionDownloadUrl } from "./api";
import Icon from "./Icon";

const exportOptions: { format: DataExportFormat; label: string }[] = [
  { format: "json", label: "导出 JSON" },
  { format: "csv", label: "导出 CSV" },
  { format: "markdown", label: "导出 Markdown（仅阅读）" },
];

// 顶栏「数据」菜单共用原有的键盘导航，下载链接也收在这里。
export default function DataMenu({ busyLabel, onImportLibrary, onImportWords, onExport }: {
  busyLabel: string;
  onImportLibrary: () => void;
  onImportWords: () => void;
  onExport: (format: DataExportFormat) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const busy = busyLabel !== "";

  useEffect(() => {
    if (!open) return;
    const closeOnOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    rootRef.current?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
    return () => {
      document.removeEventListener("pointerdown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const choose = (action: () => void) => {
    setOpen(false);
    action();
  };

  const moveFocus = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("[role=menuitem]"));
    const index = items.indexOf(document.activeElement as HTMLElement);
    const next = event.key === "ArrowDown" ? index + 1 : index - 1;
    items[(next + items.length) % items.length]?.focus();
  };

  return <div className="data-menu" ref={rootRef}>
    <button
      ref={triggerRef}
      type="button"
      className="top-bar-button"
      aria-haspopup="menu"
      aria-expanded={open}
      disabled={busy}
      onClick={() => setOpen((value) => !value)}
      title="导入备份、导入单词或导出数据副本"
      aria-label={busy ? busyLabel : "数据"}
    >{busy ? busyLabel : <><Icon name="sync" size={16} /> 数据 <Icon name="chevronDown" size={16} /></>}</button>
    {open && <div className="data-menu-list" role="menu" aria-label="数据" onKeyDown={moveFocus}>
      <button type="button" role="menuitem" onClick={() => choose(onImportLibrary)}>
        导入备份<small>JSON 或 CSV，恢复灵感、单词和网页资料</small>
      </button>
      <button type="button" role="menuitem" onClick={() => choose(onImportWords)}>
        导入单词<small>JSON 或 CSV 单词表</small>
      </button>
      <hr />
      {exportOptions.map((option) => (
        <button key={option.format} type="button" role="menuitem" onClick={() => choose(() => onExport(option.format))}>
          {option.label}
        </button>
      ))}
      <hr />
      <a role="menuitem" href={browserExtensionDownloadUrl()} download={browserExtensionArchiveFilename()}
        title="下载后解压，并在 Chrome 或 Edge 中加载已解压的扩展" onClick={() => setOpen(false)}>
        <Icon name="download" size={16} /> 下载扩展
      </a>
      <a role="menuitem" href={androidDownloadUrl()} download="MemoIsle-android.apk" onClick={() => setOpen(false)}>
        <Icon name="download" size={16} /> 下载安卓端
      </a>
    </div>}
  </div>;
}
