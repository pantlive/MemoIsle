import { type RefObject, useEffect, useRef, useState } from "react";
import { loadMemoImageUrl } from "./api";
import Icon from "./Icon";
import { ThumbnailCache } from "./thumbnailCache";

// 图片接口需要 Bearer 头，缩略图通过组件内的对象 URL 读取，卸载时释放。
export const thumbnailCache = new ThumbnailCache((memoId) => loadMemoImageUrl(memoId, "thumbnail"));

/** 元素进入视口（含预加载边距）后返回 true，之后保持 true。 */
export function useNearViewport<T extends Element>(): [RefObject<T | null>, boolean] {
  const ref = useRef<T | null>(null);
  const [near, setNear] = useState(() => typeof IntersectionObserver === "undefined");
  useEffect(() => {
    const element = ref.current;
    if (near || !element) {
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setNear(true);
          observer.disconnect();
        }
      },
      { rootMargin: "300px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [near]);
  return [ref, near];
}

export default function MemoImageThumb({
  memoId,
  version,
  alt,
  className,
}: {
  memoId: string;
  version: number;
  alt: string;
  className?: string;
}) {
  // 缩略图要带鉴权头下载，浏览器原生 loading="lazy" 管不到，
  // 所以等占位块接近视口再请求，长列表不会一次发出几十个请求。
  const [placeholderRef, near] = useNearViewport<HTMLSpanElement>();
  const [url, setUrl] = useState(() => thumbnailCache.peek(memoId, version) ?? "");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const cached = thumbnailCache.peek(memoId, version);
    setUrl(cached ?? "");
    setFailed(false);
    if (cached || !near) {
      return;
    }
    let active = true;
    void thumbnailCache
      .load(memoId, version)
      .then((next) => {
        if (active) setUrl(next);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [memoId, version, near]);

  if (failed) {
    return <span className="image-thumb-fallback" aria-hidden="true"><Icon name="image" size={20} /></span>;
  }
  if (!url) {
    return <span ref={placeholderRef} className="image-thumb-loading" aria-hidden="true" />;
  }
  return <img className={className ?? "image-thumb"} src={url} alt={alt} decoding="async" />;
}
