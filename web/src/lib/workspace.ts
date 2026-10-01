export const LAST_WS_KEY = "lp:last-workspace";

export function rememberWorkspace(id: string) {
  try {
    localStorage.setItem(LAST_WS_KEY, id);
  } catch {
    // Storage can be unavailable (private mode); remembering is only a convenience.
  }
}
