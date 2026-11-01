// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { visibleInterval } from "../visibleInterval";

function fakeDocument() {
  const target = new EventTarget();
  const doc = {
    hidden: false,
    addEventListener: target.addEventListener.bind(target),
    removeEventListener: target.removeEventListener.bind(target),
    fire() {
      target.dispatchEvent(new Event("visibilitychange"));
    },
  };
  return doc;
}

describe("visibleInterval", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("skips ticks while hidden and catches up once visible again", () => {
    const doc = fakeDocument();
    const callback = vi.fn();
    const stop = visibleInterval(callback, 1_000, doc as unknown as Document);

    vi.advanceTimersByTime(1_000);
    expect(callback).toHaveBeenCalledTimes(1);

    doc.hidden = true;
    vi.advanceTimersByTime(3_000);
    expect(callback).toHaveBeenCalledTimes(1);

    doc.hidden = false;
    doc.fire();
    expect(callback).toHaveBeenCalledTimes(2);

    // 没有错过任何轮次时，切回可见不额外触发。
    doc.fire();
    expect(callback).toHaveBeenCalledTimes(2);

    stop();
    vi.advanceTimersByTime(5_000);
    expect(callback).toHaveBeenCalledTimes(2);
  });
});
