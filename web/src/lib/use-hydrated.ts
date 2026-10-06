import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/** False during SSR and the hydration pass, true after. Inputs whose value lives in React state
 * should be disabled until then: keystrokes typed into server-rendered HTML are otherwise
 * silently overwritten when React hydrates with its initial state. */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}
