interface BrandLogoProps {
  className?: string;
}

export default function BrandLogo({ className }: BrandLogoProps) {
  // 沿用 favicon 的图形，通过主题变量适配页面配色。
  return (
    <svg
      className={className}
      width={64}
      height={64}
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <rect width="64" height="64" rx="16" fill="var(--primary-soft)" />
      <path
        d="M15 47V21L28 35.5C30.2 37.9 33.8 37.9 36 35.5L49 21V47"
        stroke="var(--primary)"
        strokeWidth="7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
