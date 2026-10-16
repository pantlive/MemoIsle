import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";

import type { DataExportFormat } from "./api";

const exportOptions: { format: DataExportFormat; label: string }[] = [
  { format: "json", label: "导出 JSON" },
  { format: "csv", label: "导出 CSV" },
  { format: "markdown", label: "导出 Markdown（仅阅读）" },
];

// 顶栏「数据」菜单：把导入备份、导入单词和三种导出格式收进一个入口。
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
    rootRef.current?.querySelector<HTMLButtonElement>("[role=menuitem]")?.focus();
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
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("[role=menuitem]"));
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
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
    >{busy ? busyLabel : <>⇅ 数据 <span aria-hidden="true">▾</span></>}</button>
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
    </div>}
  </div>;
}
