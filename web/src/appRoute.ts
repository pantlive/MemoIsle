/**
 * 工作台视图与地址栏同步：`?view=resource&item=<id>`。
 *
 * 刷新页面、浏览器后退/前进和分享链接都依赖这里；只占用 `view` 与 `item`
 * 两个参数，扩展回跳用的 `memoisle_capture*` 等其他参数原样保留。
 */

export const ROUTE_VIEWS = [
  "all",
  "inbox",
  "review",
  "resource",
  "word",
  "idea",
  "image",
  "trash",
  "vault",
] as const;

export type RouteView = (typeof ROUTE_VIEWS)[number];

export interface AppRoute {
  view: RouteView;
  item: string | null;
}

const DEFAULT_VIEW: RouteView = "all";
// 条目 ID 是 UUID；限制字符集，避免把任意字符串当作 ID 发给服务端。
const ITEM_ID_PATTERN = /^[0-9a-zA-Z-]{1,64}$/;

function isRouteView(value: string | null): value is RouteView {
  return value !== null && (ROUTE_VIEWS as readonly string[]).includes(value);
}

export function readAppRoute(search: string): AppRoute {
  const params = new URLSearchParams(search);
  const rawView = params.get("view");
  const view = isRouteView(rawView) ? rawView : DEFAULT_VIEW;
  const rawItem = params.get("item");
  // 密码库是独立页面，不承载条目选择。
  const item =
    view !== "vault" && rawItem && ITEM_ID_PATTERN.test(rawItem) ? rawItem : null;
  return { view, item };
}

export function routesEqual(left: AppRoute, right: AppRoute): boolean {
  return left.view === right.view && left.item === right.item;
}

/** 把路由写回地址，保留其他查询参数与 hash；默认视图不带参数。 */
export function routeHref(currentHref: string, route: AppRoute): string {
  const url = new URL(currentHref);
  if (route.view === DEFAULT_VIEW) {
    url.searchParams.delete("view");
  } else {
    url.searchParams.set("view", route.view);
  }
  if (route.item && route.view !== "vault") {
    url.searchParams.set("item", route.item);
  } else {
    url.searchParams.delete("item");
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * 同步地址栏：切换视图记一条历史（后退可回到上个视图），
 * 同一视图里换选中条目只替换当前历史，避免逐条浏览把历史栈刷满。
 */
export function writeAppRoute(route: AppRoute): void {
  const current = readAppRoute(window.location.search);
  if (routesEqual(current, route)) {
    return;
  }
  const href = routeHref(window.location.href, route);
  if (current.view !== route.view) {
    window.history.pushState(null, "", href);
  } else {
    window.history.replaceState(window.history.state, "", href);
  }
}

/** 列表刷新时保留深链接打开、但不在当前页里的条目。 */
export function keepLinkedMemo<T extends { id: string }>(
  items: T[],
  current: T[],
  linkedId: string | null,
): T[] {
  if (!linkedId || items.some((item) => item.id === linkedId)) {
    return items;
  }
  const linked = current.find((item) => item.id === linkedId);
  return linked ? [linked, ...items] : items;
}
