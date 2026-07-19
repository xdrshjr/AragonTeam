// @提及光标数学纯函数（mention-autocomplete spec §2.3 / §6.2.1）。
// 纯 TS、无 React 依赖：供 MentionTextarea 复用，将来接入 JS runner 即可直接单测。
// 逐字对齐后端 services/notifications.py 的 _MENTION_RE 左边界语义（非单词字符 / 行首）。

const WORD = /[A-Za-z0-9_]/;

// 从 caret 处向左吃 [A-Za-z0-9_]，若紧邻左侧是 '@' 且 '@' 左边界非单词字符 → 命中。
export function activeMention(
  value: string,
  caret: number
): { query: string; anchor: number } | null {
  let i = caret;
  while (i > 0 && WORD.test(value[i - 1])) i--;
  if (i === 0 || value[i - 1] !== "@") return null;
  const at = i - 1; // '@' 的下标
  if (at > 0 && WORD.test(value[at - 1])) return null; // 左边界必须非单词字符（镜像后端 lookbehind）
  return { query: value.slice(i, caret), anchor: at };
}

// 在 anchor 处把当前 @token 替换为 "@username "（含尾随空格），返回新串与新光标位置。
export function applyMention(
  value: string,
  anchor: number,
  caret: number,
  username: string
): { next: string; nextCaret: number } {
  const before = value.slice(0, anchor);
  const insert = `@${username} `;
  return { next: before + insert + value.slice(caret), nextCaret: (before + insert).length };
}
