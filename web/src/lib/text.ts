/** Word-level diff (LCS) for "What changed" between a draft and its revision. */
export type DiffPart = { kind: "same" | "added" | "removed"; text: string };

export function diffWords(before: string, after: string): DiffPart[] {
  const a = before.split(/(\s+)/);
  const b = after.split(/(\s+)/);
  // Guard against pathological sizes; captions are short so this is plenty.
  if (a.length * b.length > 4_000_000) {
    return [
      { kind: "removed", text: before },
      { kind: "added", text: after },
    ];
  }
  const dp: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array(b.length + 1).fill(0),
  );
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: DiffPart[] = [];
  const push = (kind: DiffPart["kind"], text: string) => {
    const last = out[out.length - 1];
    if (last && last.kind === kind) last.text += text;
    else out.push({ kind, text });
  };
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push("same", a[i]);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      push("removed", a[i++]);
    } else {
      push("added", b[j++]);
    }
  }
  while (i < a.length) push("removed", a[i++]);
  while (j < b.length) push("added", b[j++]);
  return out;
}

const URL_RE = /https?:\/\/\S+|www\.\S+/gi;

/** Mirrors the API's X weighted length: URLs = 23, wide characters (emoji, CJK) = 2. */
export function xWeightedLength(text: string): number {
  let total = 0;
  let last = 0;
  for (const m of text.matchAll(URL_RE)) {
    total += weigh(text.slice(last, m.index)) + 23;
    last = (m.index ?? 0) + m[0].length;
  }
  return total + weigh(text.slice(last));
}

function weigh(s: string): number {
  let n = 0;
  for (const ch of s) {
    const cp = ch.codePointAt(0) ?? 0;
    const light =
      cp <= 0x10ff ||
      (cp >= 0x2000 && cp <= 0x200d) ||
      (cp >= 0x2010 && cp <= 0x201f) ||
      (cp >= 0x2032 && cp <= 0x2037);
    n += light && !/\p{Extended_Pictographic}/u.test(ch) ? 1 : 2;
  }
  return n;
}
