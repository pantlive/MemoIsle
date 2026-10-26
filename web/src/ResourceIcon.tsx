import Icon from "./Icon";
import { isIdeographic, sourceMonogram } from "./webUrl";

interface ResourceMonogramProps {
  sourceUrl: string | null | undefined;
  /** 抓取到的站点名；比域名更贴近用户认知，优先使用。 */
  siteName?: string | null;
  /** 站点首字和兜底箭头的尺寸，默认 17px。 */
  size?: number;
  className?: string;
}

/**
 * 网页资料的类型图标：站点首字。
 *
 * 之前用的是字体字形「↗」，不同平台胖瘦不一，也看不出这是哪一站。
 * 换成站点首字后，列表扫一眼就能分出 github、知乎、少数派；
 * 拿不到可用字符（IP 地址、纯数字域名）时退回矢量外链箭头。
 */
export default function ResourceMonogram({
  sourceUrl,
  siteName,
  size = 17,
  className,
}: ResourceMonogramProps) {
  const glyph = sourceMonogram(sourceUrl, siteName);
  if (!glyph) {
    return <ResourceLinkGlyph size={size} />;
  }
  // 汉字是满格方块，同字号下比拉丁大写字母重一档；降两号才等重视觉。
  const fontSize = isIdeographic(glyph) ? size - 2 : size;
  return (
    <span
      className={
        className
          ? `resource-monogram ${className}`
          : "resource-monogram"
      }
      style={{ fontSize }}
      aria-hidden="true"
    >
      {glyph}
    </span>
  );
}

/** 没有可用站点首字时的兜底图标：矢量外链箭头。 */
export function ResourceLinkGlyph({
  size = 18,
  className,
}: {
  size?: number;
  className?: string;
}) {
  // 兼容原调用位置，同时收敛到 16、18、20 三档尺寸。
  return <Icon name="link" size={size <= 16 ? 16 : size <= 18 ? 18 : 20} className={className} />;
}
