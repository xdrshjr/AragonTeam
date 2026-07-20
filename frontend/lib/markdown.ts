// Markdown 安全子集 → **React 元素树**（document-lifecycle-depth §2.2 B-1）。
//
// ┌─ 铁律（不可协商）────────────────────────────────────────────────────────────┐
// │ 渲染器的返回类型是 `ReactNode[]`。实现中**不得出现** dangerouslySetInnerHTML、 │
// │ innerHTML、document.write，或任何「字符串拼 HTML」的路径。                     │
// │                                                                             │
// │ 理由不是「更干净」，而是**结构性的**：只要产物是 React 元素，用户正文里的       │
// │ `<img src=x onerror=alert(1)>` 就只能作为**文本节点**出现——XSS 不是「被过滤    │
// │ 掉了」，而是**没有可以注入的位置**。上一轮 §8 R-2 的教训（三道防线里两道在     │
// │ 预览路径上失效）在这里以「不给自己留后门」的方式解决。                          │
// └─────────────────────────────────────────────────────────────────────────────┘
//
// 支持的子集**刻意小**，覆盖研发文档 95% 的写法。明确不做：脚注、任务列表勾选、
// HTML 实体解码、自动链接、删除线、语法高亮（那需要一整套词法器或一个新依赖）。

import { createElement, type ReactNode } from "react";

/** 链接允许的协议白名单。其余（含 `javascript:`、`data:`）降级为纯文本。 */
const SAFE_LINK_SCHEMES = ["http://", "https://", "mailto:"];

const HEADING_RE = /^(#{1,4})\s+(.*)$/;
const FENCE_RE = /^```(\S*)\s*$/;
const QUOTE_RE = /^>\s?(.*)$/;
const HR_RE = /^(-{3,}|\*{3,}|_{3,})\s*$/;
const UL_RE = /^(\s*)[-*]\s+(.*)$/;
const OL_RE = /^(\s*)(\d+)\.\s+(.*)$/;
const TABLE_SEP_RE = /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

interface ListItem {
  text: string;
  depth: number;
}

/**
 * 把 Markdown 正文渲染为 React 元素数组。
 *
 * @param source 原始正文（可能被后端按 `DOC_TEXT_PREVIEW_MAX_BYTES` 截断，
 *   截断提示由调用方渲染——那是本轮唯一一处「渲染结果可能与源文件不一致」的地方）。
 * @returns 可直接放进 JSX 的节点数组；空正文返回空数组。
 */
export function renderMarkdown(source: string): ReactNode[] {
  const lines = (source || "").replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;
  let key = 0;

  while (index < lines.length) {
    const line = lines[index];

    // —— 围栏代码块：优先级最高，块内一切原样保留 ——
    const fence = FENCE_RE.exec(line);
    if (fence) {
      const lang = fence[1] || "";
      const body: string[] = [];
      index += 1;
      while (index < lines.length && !FENCE_RE.test(lines[index])) {
        body.push(lines[index]);
        index += 1;
      }
      index += 1; // 跳过闭合围栏（未闭合时正好停在末尾）
      blocks.push(
        createElement(
          "pre",
          {
            key: key++,
            "data-lang": lang || undefined,
            className:
              "my-3 overflow-x-auto rounded-lg border border-border bg-bg p-3 font-mono text-xs leading-relaxed text-ink",
          },
          createElement("code", null, body.join("\n"))
        )
      );
      continue;
    }

    if (!line.trim()) {
      index += 1;
      continue;
    }

    if (HR_RE.test(line)) {
      blocks.push(createElement("hr", { key: key++, className: "my-4 border-border" }));
      index += 1;
      continue;
    }

    const heading = HEADING_RE.exec(line);
    if (heading) {
      const level = heading[1].length;
      blocks.push(
        createElement(
          `h${level}`,
          { key: key++, className: headingClass(level) },
          ...renderInline(heading[2])
        )
      );
      index += 1;
      continue;
    }

    // —— 引用：连续行合并为一个块 ——
    if (QUOTE_RE.test(line)) {
      const body: string[] = [];
      while (index < lines.length && QUOTE_RE.test(lines[index])) {
        body.push(QUOTE_RE.exec(lines[index])![1]);
        index += 1;
      }
      blocks.push(
        createElement(
          "blockquote",
          {
            key: key++,
            className:
              "my-3 border-l-4 border-border pl-3 text-ink-muted [&>p]:my-1",
          },
          createElement("p", null, ...renderInline(body.join(" ")))
        )
      );
      continue;
    }

    // —— GFM 表格：需要表头 + 分隔行，否则按段落处理 ——
    if (line.includes("|") && index + 1 < lines.length && TABLE_SEP_RE.test(lines[index + 1])) {
      const header = splitRow(line);
      index += 2;
      const rows: string[][] = [];
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        rows.push(splitRow(lines[index]));
        index += 1;
      }
      blocks.push(renderTable(key++, header, rows));
      continue;
    }

    // —— 列表：支持**一层**嵌套（两个或四个空格缩进），更深的按纯文本处理 ——
    const listMatch = UL_RE.exec(line) || OL_RE.exec(line);
    if (listMatch) {
      const ordered = OL_RE.test(line);
      const items: ListItem[] = [];
      while (index < lines.length) {
        const current = lines[index];
        const ul = UL_RE.exec(current);
        const ol = OL_RE.exec(current);
        if (!ul && !ol) break;
        if (ordered ? !ol : !ul) break;
        const indent = (ordered ? ol![1] : ul![1]).length;
        const text = ordered ? ol![3] : ul![2];
        items.push({ text, depth: indent >= 2 ? 1 : 0 });
        index += 1;
      }
      blocks.push(renderList(key++, ordered, items));
      continue;
    }

    // —— 段落：连续非空、非块起始的行合并 ——
    const paragraph: string[] = [];
    while (index < lines.length && lines[index].trim() && !isBlockStart(lines[index])) {
      paragraph.push(lines[index]);
      index += 1;
    }
    if (!paragraph.length) {
      // 兜底：当前行本身是块起始却没被上面任何分支接住（不该发生），按文本吐出。
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push(
      createElement(
        "p",
        { key: key++, className: "my-3 leading-[1.75] text-ink" },
        ...renderInline(paragraph.join(" "))
      )
    );
  }

  return blocks;
}

function isBlockStart(line: string): boolean {
  return (
    HEADING_RE.test(line) ||
    FENCE_RE.test(line) ||
    QUOTE_RE.test(line) ||
    HR_RE.test(line) ||
    UL_RE.test(line) ||
    OL_RE.test(line)
  );
}

function headingClass(level: number): string {
  // 【§6.2】模态内的 h1 若比模态标题还大，视觉层级立刻塌掉——故刻意不使用超大字号。
  const sizes: Record<number, string> = {
    1: "mt-5 mb-2 text-lg font-semibold text-ink",
    2: "mt-5 mb-2 text-base font-semibold text-ink",
    3: "mt-4 mb-1.5 text-sm font-semibold text-ink",
    4: "mt-4 mb-1.5 text-sm font-semibold text-ink-muted",
  };
  return sizes[level] || sizes[4];
}

function splitRow(line: string): string[] {
  return line
    .replace(/^\s*\|/, "")
    .replace(/\|\s*$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function renderTable(key: number, header: string[], rows: string[][]): ReactNode {
  return createElement(
    "div",
    { key, className: "my-3 overflow-x-auto" },
    createElement(
      "table",
      { className: "w-full border-collapse text-sm" },
      createElement(
        "thead",
        null,
        createElement(
          "tr",
          null,
          ...header.map((cell, i) =>
            createElement(
              "th",
              {
                key: i,
                className:
                  "border border-border bg-bg px-2 py-1 text-left font-semibold text-ink",
              },
              ...renderInline(cell)
            )
          )
        )
      ),
      createElement(
        "tbody",
        null,
        ...rows.map((row, r) =>
          createElement(
            "tr",
            { key: r },
            ...row.map((cell, c) =>
              createElement(
                "td",
                { key: c, className: "border border-border px-2 py-1 align-top text-ink" },
                ...renderInline(cell)
              )
            )
          )
        )
      )
    )
  );
}

function renderList(key: number, ordered: boolean, items: ListItem[]): ReactNode {
  const nodes: ReactNode[] = [];
  let buffer: ListItem[] = [];
  let itemKey = 0;

  const flushNested = () => {
    if (!buffer.length) return;
    nodes.push(
      createElement(
        ordered ? "ol" : "ul",
        { key: `n${itemKey++}`, className: nestedListClass(ordered) },
        ...buffer.map((item, i) =>
          createElement("li", { key: i, className: "my-0.5" }, ...renderInline(item.text))
        )
      )
    );
    buffer = [];
  };

  for (const item of items) {
    if (item.depth > 0) {
      buffer.push(item);
      continue;
    }
    flushNested();
    nodes.push(
      createElement(
        "li",
        { key: `i${itemKey++}`, className: "my-1 leading-[1.75]" },
        ...renderInline(item.text)
      )
    );
  }
  flushNested();

  return createElement(
    ordered ? "ol" : "ul",
    { key, className: rootListClass(ordered) },
    ...nodes
  );
}

function rootListClass(ordered: boolean): string {
  return ordered
    ? "my-3 list-decimal space-y-0.5 pl-6 text-ink"
    : "my-3 list-disc space-y-0.5 pl-6 text-ink";
}

function nestedListClass(ordered: boolean): string {
  return ordered ? "my-1 list-decimal pl-5" : "my-1 list-[circle] pl-5";
}

/**
 * 行内解析。顺序固定为 **代码 → 链接 → 图片 → 粗 → 斜**：代码必须最先，
 * 否则 `` `**x**` `` 里的星号会被当成强调标记。
 */
export function renderInline(text: string): ReactNode[] {
  return parseCode(text || "", 0);
}

function parseCode(text: string, seed: number): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /`([^`]+)`/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let key = seed;
  while ((match = re.exec(text))) {
    if (match.index > last) out.push(...parseLink(text.slice(last, match.index), key++));
    out.push(
      createElement(
        "code",
        {
          key: `c${key++}`,
          className: "rounded bg-bg px-1 py-0.5 font-mono text-[0.85em] text-ink",
        },
        match[1]
      )
    );
    last = match.index + match[0].length;
  }
  if (last < text.length) out.push(...parseLink(text.slice(last), key++));
  return out;
}

function parseLink(text: string, seed: number): ReactNode[] {
  const out: ReactNode[] = [];
  // 同时吃掉 `![alt](url)` 与 `[文字](url)`：前者**不渲染外链图片**——那会向第三方
  // 泄漏内网访问行为，且本产品的图片走 blob 预览。渲染为 `[图片: alt]` 字样。
  const re = /(!?)\[([^\]]*)\]\(([^)\s]+)\)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let key = seed * 100;
  while ((match = re.exec(text))) {
    if (match.index > last) out.push(...parseStrong(text.slice(last, match.index), key++));
    const [raw, bang, label, href] = match;
    if (bang) {
      out.push(`[图片: ${label || href}]`);
    } else if (isSafeHref(href)) {
      out.push(
        createElement(
          "a",
          {
            key: `a${key++}`,
            href,
            target: "_blank",
            rel: "noopener noreferrer",
            className: "text-clay underline underline-offset-2 hover:opacity-80",
          },
          label || href,
          " ↗"
        )
      );
    } else {
      // 协议不在白名单（含 javascript: / data:）→ **降级为纯文本并保留原始字面**。
      out.push(raw);
    }
    last = match.index + raw.length;
  }
  if (last < text.length) out.push(...parseStrong(text.slice(last), key++));
  return out;
}

function isSafeHref(href: string): boolean {
  const lowered = href.trim().toLowerCase();
  return SAFE_LINK_SCHEMES.some((scheme) => lowered.startsWith(scheme));
}

function parseStrong(text: string, seed: number): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\*\*([^*]+)\*\*/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let key = seed * 10;
  while ((match = re.exec(text))) {
    if (match.index > last) out.push(...parseEm(text.slice(last, match.index), key++));
    out.push(
      createElement("strong", { key: `s${key++}`, className: "font-semibold" }, match[1])
    );
    last = match.index + match[0].length;
  }
  if (last < text.length) out.push(...parseEm(text.slice(last), key++));
  return out;
}

function parseEm(text: string, seed: number): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(?:\*([^*\n]+)\*|_([^_\n]+)_)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let key = seed * 3;
  while ((match = re.exec(text))) {
    if (match.index > last) out.push(text.slice(last, match.index));
    out.push(createElement("em", { key: `e${key++}`, className: "italic" }, match[1] ?? match[2]));
    last = match.index + match[0].length;
  }
  // 剩余部分作为**纯文本节点**吐出——裸 HTML 在这里逐字显示，不解析。
  if (last < text.length) out.push(text.slice(last));
  return out;
}
