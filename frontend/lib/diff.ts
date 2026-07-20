// 行级对比（document-lifecycle-depth §2.2 B-2）——零依赖，经典 LCS 动态规划。
//
// **为什么不是 Myers**：LCS DP 的实现只有二十来行、行为完全可预测，对研发文档这个量级
// 足够。Myers 更快，但它的调试成本与这个功能的价值不成比例。
//
// **规模保护是必须的**：浏览器主线程上跑一个 O(n·m) 的 DP，一个 5 万行的日志会让页面
// 白屏十几秒。超过 `DIFF_MAX_CELLS` 时**不计算**，如实降级为整块对比——
// **如实降级好过假装计算**。这里不引入 Web Worker：为一个对比功能引入 worker 生命周期
// 管理，复杂度与收益不成比例（§8 R-6）。

export type DiffOp = "equal" | "insert" | "delete";

export interface DiffRow {
  op: DiffOp;
  /** 左侧（旧版）行号，1 起；该行是新增时为 null。 */
  leftNo: number | null;
  /** 右侧（新版）行号，1 起；该行是删除时为 null。 */
  rightNo: number | null;
  text: string;
}

export interface DiffResult {
  rows: DiffRow[];
  added: number;
  removed: number;
  /** 为真表示超过规模闸、未真正逐行比较（UI 必须如实告知）。 */
  degraded: boolean;
  /** 两侧行数之和，供降级横幅显示。 */
  totalLines: number;
}

/** DP 表格的单元格上限，约等于两侧各 2000 行。 */
export const DIFF_MAX_CELLS = 4_000_000;

/**
 * 逐行对比两段文本。
 *
 * 比较前统一 `\r\n → \n`，**不 trim**——缩进变化是真实变化，把它抹掉等于对用户说谎。
 */
export function diffLines(left: string, right: string): DiffResult {
  const a = splitLines(left);
  const b = splitLines(right);
  const totalLines = a.length + b.length;

  if (a.length * b.length > DIFF_MAX_CELLS) {
    return degrade(a, b, totalLines);
  }

  // lcs[i][j] = a[i..] 与 b[j..] 的最长公共子序列长度。
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array<number>(b.length + 1).fill(0)
  );
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      lcs[i][j] =
        a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }

  const rows: DiffRow[] = [];
  let added = 0;
  let removed = 0;
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      rows.push({ op: "equal", leftNo: i + 1, rightNo: j + 1, text: a[i] });
      i += 1;
      j += 1;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      rows.push({ op: "delete", leftNo: i + 1, rightNo: null, text: a[i] });
      removed += 1;
      i += 1;
    } else {
      rows.push({ op: "insert", leftNo: null, rightNo: j + 1, text: b[j] });
      added += 1;
      j += 1;
    }
  }
  while (i < a.length) {
    rows.push({ op: "delete", leftNo: i + 1, rightNo: null, text: a[i] });
    removed += 1;
    i += 1;
  }
  while (j < b.length) {
    rows.push({ op: "insert", leftNo: null, rightNo: j + 1, text: b[j] });
    added += 1;
    j += 1;
  }

  return { rows, added, removed, degraded: false, totalLines };
}

function splitLines(text: string): string[] {
  return (text || "").replace(/\r\n/g, "\n").split("\n");
}

function degrade(a: string[], b: string[], totalLines: number): DiffResult {
  const rows: DiffRow[] = [
    ...a.map((text, index) => ({
      op: "delete" as DiffOp,
      leftNo: index + 1,
      rightNo: null,
      text,
    })),
    ...b.map((text, index) => ({
      op: "insert" as DiffOp,
      leftNo: null,
      rightNo: index + 1,
      text,
    })),
  ];
  return { rows, added: b.length, removed: a.length, degraded: true, totalLines };
}
