"use client";

import { useEffect, useState } from "react";
import { ApiError, downloadBlob, saveBlobAs } from "@/lib/api";
import { formatBytes, isInlineSafeMime } from "@/lib/constants";
import { useToast } from "@/lib/toast";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import ErrorState from "@/components/ui/ErrorState";
import type { DocumentSummary, DocumentVersion } from "@/lib/types";

interface Props {
  open: boolean;
  document: DocumentSummary | null;
  /** 指定预览哪个版本；缺省用当前版本。 */
  version?: DocumentVersion | null;
  onClose: () => void;
}

type Mode = "image" | "pdf" | "text" | "download";

/**
 * 挑选预览方式。**只认后端 `mime_type`**（数据库字段，非用户可控），并且必须先经
 * `INLINE_SAFE_MIMES` 白名单过滤——落选一律走下载。
 */
function decideMode(mime: string | undefined): Mode {
  if (!mime || !isInlineSafeMime(mime)) return "download";
  if (mime.startsWith("image/")) return "image";
  if (mime === "application/pdf") return "pdf";
  return "text";
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
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const shown = version ?? doc?.current_version ?? null;
  const mime = shown?.mime_type;
  const mode = decideMode(mime);

  useEffect(() => {
    if (!open || !doc || !shown) return;
    let revoked = false;
    let created: string | null = null;
    setError(null);
    setText(null);
    setObjectUrl(null);
    setLoading(true);

    (async () => {
      try {
        const path = `/documents/${doc.id}/download?version_id=${shown.id}`;
        const { blob } = await downloadBlob(path);
        if (revoked) return;
        if (mode === "text") {
          // 文本只进 <pre> 的文本节点，永远不构造 blob:，也就没有 MIME 可被滥用。
          setText(await blob.text());
        } else if (mode !== "download") {
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
          // 文本以等宽 <pre> 渲染并保留空白。**不引入 Markdown 渲染库**——那意味着
          // HTML 输出，意味着必须再配一套消毒链，意味着两个新依赖与一类新漏洞（§8 R-6）。
          // 这里用 children 而非 dangerouslySetInnerHTML：React 会把它当文本节点转义。
          <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-black/[0.02] p-3 font-mono text-xs leading-relaxed text-ink">
            {text}
          </pre>
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
