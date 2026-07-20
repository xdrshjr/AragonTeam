"use client";

import { useMemo } from "react";
import { renderMarkdown } from "@/lib/markdown";

interface Props {
  source: string;
}

/**
 * Markdown 渲染容器（document-lifecycle-depth §6.2）。
 *
 * 排版规范：正文行高 1.75、段间距 `mt-3`、`h1~h4` 递减字号且**不使用超大字号**
 * （模态内的 h1 若比模态标题还大，视觉层级立刻塌掉）。代码块与表格各自包一层
 * `overflow-x-auto`，**横向滚动收在块内，模态本体永不横滚**。
 * 全部沿用既有设计令牌（bg / surface / border / ink / ink-muted / clay），不引入新配色。
 *
 * 安全性由 `lib/markdown.ts` 结构性保证：产物是 React 元素树，用户正文里的
 * `<img onerror=…>` 只能作为文本节点出现——这里既没有 `dangerouslySetInnerHTML`，
 * 也没有任何可以注入的位置。
 *
 * **截断横幅有意不在这里**：正文截断是 `/content` 这个端点的性质，`.txt` / `.log` /
 * `.csv` 与 Markdown 的「源码」态同样会被截断。横幅若挂在本组件上，那三种情形就会
 * **静默**截断——用户读到一份看似完整、实则少了后半截的日志。故它由
 * `DocumentPreviewModal` 统一渲染在两种视图之上（§6.2 的横幅位置也在切换控件之下）。
 */
export default function MarkdownView({ source }: Props) {
  const nodes = useMemo(() => renderMarkdown(source), [source]);

  return (
    <div className="max-h-[60vh] overflow-y-auto rounded-lg border border-border px-4 py-3">
      <div className="text-sm text-ink [&_a]:break-words [&_p]:break-words">
        {nodes.length > 0 ? nodes : <p className="text-sm text-ink-muted">（空文档）</p>}
      </div>
    </div>
  );
}
