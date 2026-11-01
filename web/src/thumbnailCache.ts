/**
 * 图片缩略图的对象 URL 缓存。
 *
 * 缩略图接口需要 Bearer 头，只能 fetch 成 Blob 再生成对象 URL。之前每次列表
 * 刷新、切换视图或翻页回来都会重新下载并重建对象 URL；这里按「条目 ID + 版本」
 * 缓存，同一缩略图的并发请求共用一次下载，超出容量时淘汰最久未用的并释放。
 */

export const THUMBNAIL_CACHE_LIMIT = 300;

type Loader = (memoId: string) => Promise<string>;
type Revoke = (url: string) => void;

export class ThumbnailCache {
  private readonly urls = new Map<string, string>();
  private readonly pending = new Map<string, Promise<string>>();
  // clear() 之后才完成的旧请求不能再写回缓存。
  private generation = 0;

  constructor(
    private readonly loader: Loader,
    private readonly revoke: Revoke = (url) => URL.revokeObjectURL(url),
    private readonly limit = THUMBNAIL_CACHE_LIMIT,
  ) {}

  private static key(memoId: string, version: number): string {
    return `${memoId}:${version}`;
  }

  /** 已缓存时同步返回，组件首帧就能直接显示，不闪占位块。 */
  peek(memoId: string, version: number): string | null {
    const key = ThumbnailCache.key(memoId, version);
    const url = this.urls.get(key);
    if (url === undefined) {
      return null;
    }
    // Map 保持插入顺序：重新插入即标记为最近使用。
    this.urls.delete(key);
    this.urls.set(key, url);
    return url;
  }

  load(memoId: string, version: number): Promise<string> {
    const cached = this.peek(memoId, version);
    if (cached) {
      return Promise.resolve(cached);
    }
    const key = ThumbnailCache.key(memoId, version);
    const inFlight = this.pending.get(key);
    if (inFlight) {
      return inFlight;
    }
    const generation = this.generation;
    const request: Promise<string> = this.loader(memoId)
      .then((url) => {
        if (generation !== this.generation) {
          this.revoke(url);
          throw new Error("缩略图缓存已清空");
        }
        this.store(memoId, key, url);
        return url;
      })
      .finally(() => {
        // clear() 后同一键可能已有新请求，只删自己。
        if (this.pending.get(key) === request) this.pending.delete(key);
      });
    this.pending.set(key, request);
    return request;
  }

  private store(memoId: string, key: string, url: string): void {
    // 同一条目的旧版本缩略图已过时，替换图片后立即释放。
    for (const [existingKey, existingUrl] of this.urls) {
      if (existingKey.startsWith(`${memoId}:`) && existingKey !== key) {
        this.urls.delete(existingKey);
        this.revoke(existingUrl);
      }
    }
    this.urls.set(key, url);
    while (this.urls.size > this.limit) {
      const [oldestKey, oldestUrl] = this.urls.entries().next().value as [string, string];
      this.urls.delete(oldestKey);
      this.revoke(oldestUrl);
    }
  }

  /** 退出登录时清空，避免下一个账号看到上一个账号的图片。 */
  clear(): void {
    for (const url of this.urls.values()) {
      this.revoke(url);
    }
    this.urls.clear();
    this.pending.clear();
    this.generation += 1;
  }

  get size(): number {
    return this.urls.size;
  }
}
