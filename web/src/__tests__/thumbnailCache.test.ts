import { describe, expect, it, vi } from "vitest";
import { ThumbnailCache } from "../thumbnailCache";

function setup(limit = 3) {
  let counter = 0;
  const loader = vi.fn(async (memoId: string) => `blob:${memoId}:${++counter}`);
  const revoke = vi.fn();
  return { cache: new ThumbnailCache(loader, revoke, limit), loader, revoke };
}

describe("ThumbnailCache", () => {
  it("shares one download between concurrent requests and caches the result", async () => {
    const { cache, loader } = setup();
    const [first, second] = await Promise.all([cache.load("m", 1), cache.load("m", 1)]);
    expect(first).toBe(second);
    expect(loader).toHaveBeenCalledTimes(1);
    expect(cache.peek("m", 1)).toBe(first);
    await cache.load("m", 1);
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it("drops and revokes the stale version when an image is replaced", async () => {
    const { cache, revoke } = setup();
    const old = await cache.load("m", 1);
    await cache.load("m", 2);
    expect(revoke).toHaveBeenCalledWith(old);
    expect(cache.peek("m", 1)).toBeNull();
    expect(cache.size).toBe(1);
  });

  it("evicts the least recently used entry beyond the limit", async () => {
    const { cache, revoke } = setup(2);
    const a = await cache.load("a", 1);
    await cache.load("b", 1);
    cache.peek("a", 1); // a 变为最近使用
    const b = cache.peek("b", 1);
    cache.peek("a", 1);
    await cache.load("c", 1);
    expect(revoke).toHaveBeenCalledWith(b);
    expect(cache.peek("a", 1)).toBe(a);
    expect(cache.size).toBe(2);
  });

  it("revokes everything on clear and ignores requests that finish afterwards", async () => {
    const { cache, revoke } = setup();
    const kept = await cache.load("a", 1);
    const pending = cache.load("b", 1);
    cache.clear();
    expect(revoke).toHaveBeenCalledWith(kept);
    await expect(pending).rejects.toThrow();
    expect(cache.size).toBe(0);
  });
});
