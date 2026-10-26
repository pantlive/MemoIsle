import type { ReactNode } from "react";

// 所有界面图标共用视图框和描边，避免不同字体字形带来的粗细差异。
const paths = {
  home: <><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z" /></>,
  inbox: <><path d="M4 4h16l2 11v5H2v-5Z" /><path d="M2 15h6l2 3h4l2-3h6" /></>,
  word: <><path d="m3 19 6-14 6 14M5 15h8M16 10h5M18.5 7v3c0 5-3 8-4 9M16 14c1 2 3 4 5 5" /></>,
  link: <><path d="M14 3h7v7M21 3 10 14" /><path d="M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5" /></>,
  image: <><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8" cy="8" r="1.5" /><path d="m21 15-6-6L3 21" /></>,
  health: <><path d="M12 3 2 21h20Z" /><path d="M12 9v5m0 3h.01" /></>,
  history: <><path d="M3 11a9 9 0 1 1 2.6 7.4M3 4v7h7M12 7v5l3 2" /></>,
  idea: <><path d="M9 18h6m-5 3h4M8 14a6 6 0 1 1 8 0c-1 .8-1 1-1 2H9c0-1 0-1.2-1-2Z" /></>,
  review: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  trash: <><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7" /></>,
  vault: <><rect x="4" y="3" width="16" height="18" rx="2" /><circle cx="12" cy="12" r="3" /><path d="m12 9 1-2m2 5h2m-5 3-1 2m-2-5H7" /></>,
  settings: <><path d="m9 3-.5 3-2 1-3-.5-2 3L4 12l-2.5 2.5 2 3 3-.5 2 1L9 21h6l.5-3 2-1 3 .5 2-3L20 12l2.5-2.5-2-3-3 .5-2-1L15 3Z" /><circle cx="12" cy="12" r="3" /></>,
  collection: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
  list: <><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" /></>,
  keyboard: <><rect x="2" y="5" width="20" height="14" rx="2" /><path d="M6 9h.01M10 9h.01M14 9h.01M18 9h.01M6 12h.01M10 12h.01M14 12h.01M18 12h.01M7 16h10" /></>,
  book: <><path d="M12 5C8 2 4 3 2 4v16c4-2 7-1 10 1 3-2 6-3 10-1V4c-2-1-6-2-10 1Zm0 0v16" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  search: <><circle cx="10.5" cy="10.5" r="7.5" /><path d="m16 16 5 5" /></>,
  refresh: <><path d="M20 7a9 9 0 0 0-15-1L2 9m0-6v6h6M4 17a9 9 0 0 0 15 1l3-3m0 6v-6h-6" /></>,
  star: <path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9Z" />,
  more: <><circle cx="5" cy="12" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /></>,
  download: <><path d="M12 3v12m-5-5 5 5 5-5M3 16v5h18v-5" /></>,
  copy: <><rect x="8" y="8" width="13" height="13" rx="2" /><path d="M16 8V3H3v13h5" /></>,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  sync: <><path d="M7 3v18m-4-4 4 4 4-4M17 21V3m-4 4 4-4 4 4" /></>,
  chevronDown: <path d="m6 9 6 6 6-6" />,
  chevronRight: <path d="m9 6 6 6-6 6" />,
  play: <path d="M8 5v14l11-7Z" />,
  check: <path d="m5 12 5 5L20 7" />,
  swap: <><path d="M3 8h18m-4-4 4 4-4 4M21 16H3m4-4-4 4 4 4" /></>,
  upload: <><path d="M12 21V9m-5 5 5-5 5 5M3 8V3h18v5" /></>,
  cloud: <path d="M7 19a5 5 0 0 1-.9-9.9 6 6 0 0 1 11.6 1.4A4 4 0 0 1 17 19Z" />,
  audio: <><rect x="9" y="2" width="6" height="13" rx="3" /><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8" /></>,
  arrowDown: <path d="M12 4v16m-6-6 6 6 6-6" />,
  arrowUp: <path d="M12 20V4m-6 6 6-6 6 6" />,
  arrowRight: <path d="M4 12h16m-6-6 6 6-6 6" />,
  arrowLeft: <path d="M20 12H4m6-6-6 6 6 6" />,
  bookmark: <path d="M7 4h10a1 1 0 0 1 1 1v16l-6-3.5L6 21V5a1 1 0 0 1 1-1Z" />,
  folder: <path d="M3 6h6l2 2h10v11H3Z" />,
  monitor: <><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M12 17v4m-4 0h8" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></>,
  moon: <path d="M21 12.8A9 9 0 0 1 11.2 3 9 9 0 1 0 21 12.8Z" />,
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof paths;

export default function Icon({ name, size = 18, className }: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      className={className ? `icon ${className}` : "icon"}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {paths[name]}
    </svg>
  );
}
