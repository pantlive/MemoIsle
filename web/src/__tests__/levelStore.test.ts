import { describe, expect, it, vi } from "vitest";
import { createLevelStore } from "../levelStore";

describe("createLevelStore", () => {
  it("notifies subscribers only when the value changes", () => {
    const store = createLevelStore();
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);
    store.set(10);
    store.set(10);
    store.set(20);
    expect(listener).toHaveBeenCalledTimes(2);
    expect(store.get()).toBe(20);
    unsubscribe();
    store.set(30);
    expect(listener).toHaveBeenCalledTimes(2);
  });
});
