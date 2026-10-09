interface BrandLogoProps {
  className?: string;
}

export default function BrandLogo({ className }: BrandLogoProps) {
  // 页面与浏览器标签共用 Stitch 矢量稿，避免独立字形或配色发生偏差。
  return (
    <img
      className={className}
      src={`${import.meta.env.BASE_URL}favicon.svg`}
      width={64}
      height={64}
      alt=""
      aria-hidden="true"
      draggable={false}
    />
  );
}
