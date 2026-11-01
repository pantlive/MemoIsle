import { useSyncExternalStore } from "react";

/**
 * 高频变化的单个数值（音量电平等）的小型外部 store。
 *
 * 录音音量在 requestAnimationFrame 里每帧更新；放在 App 的 state 里会让整个
 * 工作台每秒重渲染几十次。改由 store 承载后，只有订阅它的电平条组件重绘。
 */
export interface LevelStore {
  get(): number;
  set(value: number): void;
  subscribe(listener: () => void): () => void;
}

export function createLevelStore(initial = 0): LevelStore {
  let value = initial;
  const listeners = new Set<() => void>();
  return {
    get: () => value,
    set(next) {
      if (next === value) {
        return;
      }
      value = next;
      for (const listener of listeners) listener();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

export function useLevel(store: LevelStore): number {
  return useSyncExternalStore(store.subscribe, store.get, store.get);
}
