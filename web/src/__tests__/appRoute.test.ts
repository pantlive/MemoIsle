// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from "vitest";
import {
  isStandaloneView,
  keepLinkedMemo,
  readAppRoute,
  routeHref,
  writeAppRoute,
} from "../appRoute";

describe("readAppRoute", () => {
  it("defaults to the home view", () => {
    expect(readAppRoute("")).toEqual({ view: "all", item: null });
  });

  it("reads a known view and item", () => {
    expect(readAppRoute("?view=resource&item=abc-123")).toEqual({
      view: "resource",
      item: "abc-123",
    });
  });

  it("ignores unknown views and malformed ids", () => {
    expect(readAppRoute("?view=admin&item=../../etc")).toEqual({
      view: "all",
      item: null,
    });
  });

  it("never carries an item on the vault page", () => {
    expect(readAppRoute("?view=vault&item=abc")).toEqual({ view: "vault", item: null });
  });

  it("opens the ledger page without an item", () => {
    expect(readAppRoute("?view=ledger")).toEqual({ view: "ledger", item: null });
    expect(readAppRoute("?view=ledger&item=abc")).toEqual({ view: "ledger", item: null });
  });

  it("marks only vault and ledger as standalone pages", () => {
    expect(isStandaloneView("vault")).toBe(true);
    expect(isStandaloneView("ledger")).toBe(true);
    expect(isStandaloneView("resource")).toBe(false);
    expect(isStandaloneView("all")).toBe(false);
  });
});

describe("routeHref", () => {
  it("keeps unrelated params and drops defaults", () => {
    const href = routeHref("https://x.test/?memoisle_capture=t#h", {
      view: "all",
      item: null,
    });
    expect(href).toBe("/?memoisle_capture=t#h");
  });

  it("drops the item on standalone pages", () => {
    expect(routeHref("https://x.test/?view=word&item=m1&keep=1", { view: "ledger", item: "m1" })).toBe(
      "/?view=ledger&keep=1",
    );
  });

  it("writes view and item", () => {
    expect(routeHref("https://x.test/?view=word", { view: "image", item: "m1" })).toBe(
      "/?view=image&item=m1",
    );
  });
});

describe("writeAppRoute", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("pushes when the view changes and replaces when only the item changes", () => {
    const start = window.history.length;
    writeAppRoute({ view: "resource", item: null });
    expect(window.location.search).toBe("?view=resource");
    expect(window.history.length).toBe(start + 1);

    writeAppRoute({ view: "resource", item: "m1" });
    expect(window.location.search).toBe("?view=resource&item=m1");
    expect(window.history.length).toBe(start + 1);
  });

  it("pushes a history entry when switching between vault and ledger", () => {
    writeAppRoute({ view: "vault", item: null });
    const length = window.history.length;
    writeAppRoute({ view: "ledger", item: null });
    expect(window.location.search).toBe("?view=ledger");
    expect(window.history.length).toBe(length + 1);
  });

  it("does nothing when the address already matches", () => {
    writeAppRoute({ view: "word", item: null });
    const length = window.history.length;
    writeAppRoute({ view: "word", item: null });
    expect(window.history.length).toBe(length);
  });
});

describe("keepLinkedMemo", () => {
  const a = { id: "a" };
  const b = { id: "b" };
  const linked = { id: "linked" };

  it("returns the new page unchanged without a linked memo", () => {
    expect(keepLinkedMemo([a, b], [linked], null)).toEqual([a, b]);
  });

  it("keeps the linked memo in front when the page no longer contains it", () => {
    expect(keepLinkedMemo([a, b], [linked, a], "linked")).toEqual([linked, a, b]);
  });

  it("does not duplicate a linked memo already on the page", () => {
    expect(keepLinkedMemo([a, linked], [linked], "linked")).toEqual([a, linked]);
  });
});
