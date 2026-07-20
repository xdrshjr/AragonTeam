"use client";

import { useEffect, useState } from "react";
import { ApiError, api, downloadBlob, saveBlobAs } from "@/lib/api";
import {
  extensionOf,
  formatBytes,
  isInlineSafeMime,
  isMarkdownExtension,
  isTextExtension,
} from "@/lib/constants";
import { useToast } from "@/lib/toast";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import ErrorState from "@/components/ui/ErrorState";
import MarkdownView from "@/components/documents/MarkdownView";
import { useDocumentMeta } from "@/hooks/useDocumentTrash";
import type { DocumentContent, DocumentSummary, DocumentVersion } from "@/lib/types";

interface Props {
  open: boolean;
  document: DocumentSummary | null;
  /** 指定预览哪个版本；缺省用当前版本。 */
  version?: DocumentVersion | null;
  onClose: () => void;
}

type Mode = "image" | "pdf" | "text" | "download";

const SEGMENTS: ReadonlyArray<readonly [string, boolean]> = [
  ["渲染", true],
  ["源码", false],
];

/**
 * 预览模式判定。
 *
 * 【为什么 text 分支用扩展名、而不用 INLINE_SAFE_MIMES】
 * 两个常量回答的是**不同的问题**：
 *   - TEXT_EXTENSIONS  = 「这份东西的正文能不能当纯文本读」——正文经 /content 这个
 *     JSON 端点取回，最终落进 <pre> 的**文本节点**或 Markdown 元素树，全程不产生
 *     blob: URL、不产生任何由浏览器自主解析的文档，故它没有任何安全职责。
 *   - INLINE_SAFE_MIMES = 「哪些 MIME 允许被浏览器当作文档直接渲染」——它是 blob:
 *     预览与 Content-Disposition: inline 的判据，text/html 与 image/svg+xml 被刻意
 *     排除在外，因为它们能在本站源上执行脚本。
 * 把 csv/json/yaml 加进 INLINE_SAFE_MIMES 是一个看起来更短、实则把上一轮唯一还生效的
 * 防线撬松的改法（text/html 与它们只隔一行）。**不要那样做**（R-13）。
 *
 * 【顺序不可颠倒】扩展名判据必须在 inline-safe 闸**之前**：text/csv、application/json、
 * application/yaml 都不在 INLINE_SAFE_MIMES 里，闸在前就永远到不了 text 分支——
 * 那正是本次要修的 bug 本身（评审 V-05）。
 */
function decideMode(mime: string | undefined, filename: string | undefined): Mode {
  if (isTextExtension(extensionOf(filename))) return "text";   // ← 前置
  if (!mime || !isInlineSafeMime(mime)) return "download";
  if (mime.startsWith("image/")) return "image";
  if (mime === "application/pdf") return "pdf";
  return "download";        // ← 兜底由 "text" 改为 "download"：走到这里说明
                            //    扩展名不是文本，再当文本读就是猜（原 "text" 只可能
                            //    被 text/plain / text/markdown 命中，已被第一行接管）
}

// 图片 / PDF / 文本预览 + 下载（ticket-document-management §2.6）。
//
// ┌─ 【评审 R6 · P1】本组件是 §8 R-2 那张风险表的真正落点 ─────────────────────┐
// │ §8 R-2 声明了三道 XSS 防线：扩展名白名单、`Content-Disposition: attachment`、  │
// │ `nosniff`。**后两道都是响应头，而 `blob:` URL 与响应头无关**：blob 文档的      │
// │ MIME 完全取自下面 `new Blob(..., { type })` 的入参，且它运行在**本源**——      │
// │ JWT 就存放在这个源的 localStorage["aragon_token"] 里。                        │
// │                                                                              │
// │ 因此以下四条是**实施硬约束**，不是建议：                                       │
// │  1. Blob 的 type 只能来自后端 `mime_type`，绝不取自响应头 / 扩展名 / 用户输入； │
// │  2. 该 mime 必须先经 INLINE_SAFE_MIMES 过滤，落选一律 octet-stream 且只下载；  │
// │  3. PDF 只在 `<iframe sandbox>`（不含 allow-same-origin / allow-scripts）内   │
// │     渲染；图片只进 `<img>`；文本只进 `<pre>` 的文本节点（**不用** innerHTML）；│
// │  4. **禁止**把 objectURL 交给 window.open() 或任何顶层导航——那正是把 blob     │
// │     文档提升为同源顶级文档的唯一路径。每个 URL 在卸载时 revoke。               │
// └──────────────────────────────────────────────────────────────────────────────┘
export default function DocumentPreviewModal({ open, document: doc, version, onClose }: Props) {
  const toast = useToast();
  const { previewMaxBytes } = useDocumentMeta();
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  /** 渲染 / 源码切换（仅 Markdown）。状态记在组件内，**不持久化**。 */
  const [rendered, setRendered] = useState(true);

  const shown = version ?? doc?.current_version ?? null;
  const mime = shown?.mime_type;
  const extension = extensionOf(shown?.original_filename);
  const mode = decideMode(mime, shown?.original_filename);
  const isMarkdown = mode === "text" && isMarkdownExtension(extension);

  // 换文档 / 换版本时回到默认视图（Markdown 默认渲染态）。
  useEffect(() => setRendered(true), [shown?.id]);

  useEffect(() => {
    if (!open || !doc || !shown) return;
    let revoked = false;
    let created: string | null = null;
    setError(null);
    setText(null);
    setTruncated(false);
    setObjectUrl(null);
    setLoading(true);

    (async () => {
      try {
        if (mode === "text") {
          // 文本走 /content 这个 JSON 端点：正文只进 React 的文本节点或 Markdown
          // 元素树，**永远不构造 blob:**，也就没有 MIME 可被滥用。它同时带回
          // truncated 标记——渲染视图必须如实告知「可能不完整」。
          const body = await api.get<DocumentContent>(
            `/documents/${doc.id}/content?version_id=${shown.id}`);
          if (revoked) return;
          setText(body.content);
          setTruncated(body.truncated);
          return;
        }
        const path = `/documents/${doc.id}/download?version_id=${shown.id}`;
        const { blob } = await downloadBlob(path);
        if (revoked) return;
        if (mode !== "download") {
          // 【硬规则 1+2】type 只来自已过白名单的后端 mime_type。
          created = URL.createObjectURL(new Blob([blob], { type: mime }));
          if (revoked) {
            URL.revokeObjectURL(created);
            return;
          }
          setObjectUrl(created);
        }
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "无法加载预览");
      } finally {
        if (!revoked) setLoading(false);
      }
    })();

    return () => {
      revoked = true;
      // 【硬规则 4】每个 objectURL 在卸载时 revoke，不留悬挂引用。
      if (created) URL.revokeObjectURL(created);
    };
  }, [open, doc, shown, mode, mime]);

  async function onDownload() {
    if (!doc || !shown) return;
    try {
      const { blob, filename } = await downloadBlob(
        `/documents/${doc.id}/download?version_id=${shown.id}`);
      saveBlobAs(blob, filename || shown.original_filename);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "下载失败");
    }
  }

  if (!doc) return null;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={doc.title}
      width={760}
      footer={
        <>
          <Button size="sm" variant="ghost" onClick={onClose}>关闭</Button>
          <Button size="sm" onClick={onDownload}>下载原文件</Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-ink-muted">
            {shown ? (
              <>
                {shown.original_filename} · v{shown.version_no} ·{" "}
                {formatBytes(shown.size_bytes)} · {shown.mime_type}
              </>
            ) : (
              "该文档还没有任何版本"
            )}
          </p>
          {isMarkdown && (
            // 分段控件（segmented control），不是两个独立按钮——它表达的是**互斥态**。
            <div
              role="group"
              aria-label="预览方式"
              className="inline-flex overflow-hidden rounded-md border border-border text-xs"
            >
              {SEGMENTS.map(([label, value]) => (
                <button
                  key={label}
                  type="button"
                  aria-pressed={rendered === value}
                  onClick={() => setRendered(value)}
                  className={
                    rendered === value
                      ? "bg-clay px-2.5 py-1 text-white"
                      : "px-2.5 py-1 text-ink-muted hover:bg-black/[0.04]"
                  }
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* 截断横幅对**全部**文本类型生效，不只是 Markdown 的渲染态：`/content` 按
            DOC_TEXT_PREVIEW_MAX_BYTES 截断，一份 3 MB 的 .log 与切到「源码」的 .md
            同样只回来一截。挂在 MarkdownView 上就等于让那些情形静默截断——用户读到
            一份看似完整、实则少了后半截的正文，那是本轮唯一一处「显示与源文件不一致」
            的地方，不说出来就是欺骗（§6.2）。 */}
        {!loading && !error && mode === "text" && truncated && (
          <p
            role="status"
            className="rounded-md border border-[#E4C9A8] bg-[#FBF3E7] px-3 py-2 text-xs text-[#8A5A16]"
          >
            ⚠ 正文过长已被截断
            {previewMaxBytes ? `（仅显示前 ${formatBytes(previewMaxBytes)}）` : ""}
            ，显示内容可能不完整{isMarkdown && rendered ? "（例如未闭合的代码块）" : ""}。
            完整内容请下载原文件。
          </p>
        )}

        {loading && <div className="py-10 text-center text-sm text-ink-muted">加载预览…</div>}

        {!loading && error && <ErrorState message={error} />}

        {!loading && !error && mode === "image" && objectUrl && (
          <img
            src={objectUrl}
            alt={doc.title}
            className="mx-auto max-h-[60vh] max-w-full rounded-lg border border-border object-contain"
          />
        )}

        {!loading && !error && mode === "pdf" && objectUrl && (
          // 【硬规则 3】sandbox 不含 allow-same-origin / allow-scripts：即便 PDF 里
          // 嵌了脚本，它也拿不到本源，读不到 localStorage 里的 JWT。
          <iframe
            src={objectUrl}
            title={`${doc.title} 预览`}
            sandbox=""
            className="h-[60vh] w-full rounded-lg border border-border bg-white"
          />
        )}

        {!loading && !error && mode === "text" && text !== null && (
          isMarkdown && rendered ? (
            // Markdown 渲染成 **React 元素树**（lib/markdown.ts），全程零
            // dangerouslySetInnerHTML——XSS 不是「被过滤掉了」，而是没有可注入的位置。
            <MarkdownView source={text} />
          ) : (
            // 其余文本类型行为**逐字节不变**：等宽 <pre> + 保留空白。这里用 children
            // 而非 dangerouslySetInnerHTML：React 会把它当文本节点转义。
            <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-black/[0.02] p-3 font-mono text-xs leading-relaxed text-ink">
              {text}
            </pre>
          )
        )}

        {!loading && !error && mode === "download" && (
          <div className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-ink-muted">
            该类型不支持在线预览，请下载后查看。
          </div>
        )}
      </div>
    </Modal>
  );
}
