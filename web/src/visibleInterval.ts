/**
 * 只在页面可见时执行的轮询。
 *
 * 标签页切到后台后浏览器虽然会节流计时器，但请求仍会按分钟级继续打到服务端；
 * 这里在隐藏期间跳过，重新可见时立刻补一次，保证回来看到的是最新状态。
 * 返回清理函数，直接作为 useEffect 的返回值使用。
 */
export function visibleInterval(
  callback: () => void,
  intervalMs: number,
  doc: Pick<Document, "hidden" | "addEventListener" | "removeEventListener"> = document,
): () => void {
  let missed = false;
  const tick = () => {
    if (doc.hidden) {
      missed = true;
      return;
    }
    callback();
  };
  const handleVisibility = () => {
    if (!doc.hidden && missed) {
      missed = false;
      callback();
    }
  };
  const timer = window.setInterval(tick, intervalMs);
  doc.addEventListener("visibilitychange", handleVisibility);
  return () => {
    window.clearInterval(timer);
    doc.removeEventListener("visibilitychange", handleVisibility);
  };
}
