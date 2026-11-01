import {
  type ComponentProps,
  type ComponentType,
  lazy,
  type ReactNode,
  Suspense,
} from "react";

/**
 * 按需加载的组件：首次渲染时才下载对应代码块，并自带 Suspense 边界。
 *
 * 对话框、密码库这类「点开才用」的界面不必进首屏包；调用处的 JSX 不用改，
 * 也不会因为某个块还在下载而让整个工作台显示 fallback。
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function lazyComponent<T extends ComponentType<any>>(
  loader: () => Promise<{ default: T }>,
  fallback: ReactNode = null,
): (props: ComponentProps<T>) => ReactNode {
  const LazyInner = lazy(loader);
  function LazyBoundary(props: ComponentProps<T>) {
    return (
      <Suspense fallback={fallback}>
        <LazyInner {...props} />
      </Suspense>
    );
  }
  return LazyBoundary;
}
