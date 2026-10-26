import { useEffect, useRef } from "react";
import Icon from "./Icon";

type Shortcut = { keys: string[][]; label: string };

// keys 的每一项是一组可互换的按键，组内按键需同时按下。
const sections: { title: string; note?: string; items: Shortcut[] }[] = [
  {
    title: "全局",
    items: [
      { keys: [["/"]], label: "聚焦搜索框" },
      { keys: [["N"]], label: "新建内容" },
      { keys: [["?"]], label: "打开本面板" },
      { keys: [["Ctrl/⌘", "Shift", "Alt", "B"]], label: "收藏最近浏览的网页（需扩展）" },
    ],
  },
  {
    title: "网页资料列表",
    items: [
      { keys: [["J"], ["↓"]], label: "下一条" },
      { keys: [["K"], ["↑"]], label: "上一条" },
      { keys: [["Enter"], ["空格"]], label: "打开预览" },
      { keys: [["E"]], label: "编辑" },
      { keys: [["O"]], label: "在新标签页打开原网页" },
      { keys: [["C"]], label: "复制链接" },
      { keys: [["S"]], label: "添加或取消星标" },
      { keys: [["X"]], label: "选中或取消选中" },
      { keys: [["Delete"]], label: "移入回收站" },
      { keys: [["]"], ["→"]], label: "下一页" },
      { keys: [["["], ["←"]], label: "上一页" },
    ],
  },
  {
    title: "网页资料预览",
    items: [
      { keys: [["E"]], label: "编辑" },
      { keys: [["O"]], label: "打开原网页" },
      { keys: [["Esc"]], label: "退出编辑；不在编辑时关闭预览" },
    ],
  },
  {
    title: "浏览器扩展",
    note: "可在 chrome://extensions/shortcuts 修改。",
    items: [
      { keys: [["Ctrl/⌘", "Shift", "M"]], label: "在任意网页收藏当前页面" },
    ],
  },
];

export default function ShortcutHelpDialog({ onClose }: { onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const closeOnKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" || event.key === "?") {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", closeOnKey);
    return () => {
      window.removeEventListener("keydown", closeOnKey);
      opener?.focus?.();
    };
  }, [onClose]);

  return (
    <div
      className="dialog-backdrop shortcut-help-backdrop"
      role="presentation"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="shortcut-help-dialog dialog-shell"
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcut-help-title"
      >
        <div className="dialog-header">
          <div>
            <span className="type-label"><Icon name="keyboard" size={16} /> 操作指南</span>
            <h2 id="shortcut-help-title">键盘快捷键</h2>
          </div>
          <button
            ref={closeRef}
            type="button"
            className="icon-button"
            aria-label="关闭快捷键说明"
            onClick={onClose}
          ><Icon name="close" size={16} /></button>
        </div>
        <div className="dialog-body">
          <p className="shortcut-help-hint">在输入框里打字时，单键快捷键不会生效。</p>
          <div className="shortcut-help-sections">
            {sections.map((section) => (
              <div className="shortcut-help-section" key={section.title}>
                <h3>{section.title}</h3>
                <dl>
                  {section.items.map((item) => (
                    <div key={item.label}>
                      <dt>
                        {item.keys.map((combo, index) => (
                          <span key={combo.join("+")}>
                            {index > 0 && <span className="shortcut-or">或</span>}
                            {combo.map((key, keyIndex) => (
                              <span key={key}>
                                {keyIndex > 0 && "+"}
                                <kbd aria-label={key === "↓" ? "向下" : key === "↑" ? "向上" : key === "→" ? "向右" : key === "←" ? "向左" : undefined}>
                                  {key === "↓" ? <Icon name="arrowDown" size={12} />
                                    : key === "↑" ? <Icon name="arrowUp" size={12} />
                                    : key === "→" ? <Icon name="arrowRight" size={12} />
                                    : key === "←" ? <Icon name="arrowLeft" size={12} /> : key}
                                </kbd>
                              </span>
                            ))}
                          </span>
                        ))}
                      </dt>
                      <dd>{item.label}</dd>
                    </div>
                  ))}
                </dl>
                {section.note && <small>{section.note}</small>}
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
