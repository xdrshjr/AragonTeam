"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api";
import {
  DOCUMENT_KIND_OPTIONS,
  documentIcon,
  documentKindStyle,
  formatBytes,
} from "@/lib/constants";
import { useToast } from "@/lib/toast";
import { useDocumentLibrary } from "@/hooks/useDocumentLibrary";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import EmptyState from "@/components/ui/EmptyState";
import ErrorState from "@/components/ui/ErrorState";

interface Props {
  open: boolean;
  /** 已绑定的文档 id，用于防重复绑定提示（后端同样会 409，这里只是提前告知）。 */
  boundIds: number[];
  onBind: (documentId: number, label?: string) => Promise<unknown>;
  onClose: () => void;
}

// 从文档库搜索并绑定已有文档（ticket-document-management §3.4）。
//
// 这个入口是「复用」这条设计主线的落点：一份 PRD 服务 5 张需求单时，用户应当在这里
// 找到它并绑上，而不是把同一个文件传 5 遍。
export default function DocumentBindModal({ open, boundIds, onBind, onClose }: Props) {
  const toast = useToast();
  const [keyword, setKeyword] = useState("");
  const [kind, setKind] = useState("");
  const [label, setLabel] = useState("");
  const [binding, setBinding] = useState<number | null>(null);

  const { documents, total, isLoading, error, refresh } = useDocumentLibrary({
    q: keyword || undefined,
    kind: kind || undefined,
    limit: 20,
  });

  async function bind(documentId: number) {
    setBinding(documentId);
    try {
      await onBind(documentId, label.trim() || undefined);
      toast.success("已绑定");
      onClose();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast.info("这份文档已经绑定在本工单上了");
      } else {
        toast.error(err instanceof ApiError ? err.message : "绑定失败");
      }
    } finally {
      setBinding(null);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="从文档库绑定已有文档"
      width={660}
      footer={<Button size="sm" variant="ghost" onClick={onClose}>关闭</Button>}
    >
      <div className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="按标题 / 描述搜索"
            aria-label="搜索文档"
            className="h-9 min-w-[10rem] flex-1 rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
          />
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            aria-label="按类型筛选"
            className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
          >
            <option value="">全部类型</option>
            {DOCUMENT_KIND_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          maxLength={64}
          placeholder="给这次绑定加个备注（可选，例如「验收报告」）"
          aria-label="绑定备注"
          className="h-9 w-full rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
        />

        {error ? (
          <ErrorState message="无法加载文档库" onRetry={() => refresh()} />
        ) : isLoading && documents.length === 0 ? (
          <div className="py-8 text-center text-sm text-ink-muted">加载文档库…</div>
        ) : documents.length === 0 ? (
          <EmptyState
            title="没有匹配的文档"
            hint="换个关键词，或直接在上方的上传区把文件拖进来。"
          />
        ) : (
          <>
            <ul className="max-h-[46vh] space-y-1 overflow-y-auto">
              {documents.map((doc) => {
                const alreadyBound = boundIds.includes(doc.id);
                return (
                  <li
                    key={doc.id}
                    className="flex items-center gap-2 rounded-lg border border-border px-2.5 py-2"
                  >
                    <span aria-hidden="true">{documentIcon(doc.current_version?.original_filename)}</span>
                    <Badge style={documentKindStyle(doc.kind)} className="shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm text-ink">{doc.title}</p>
                      <p className="truncate text-xs text-ink-muted">
                        {doc.current_version?.original_filename} ·{" "}
                        {formatBytes(doc.current_version?.size_bytes)} · 已绑定 {doc.link_count} 处
                      </p>
                    </div>
                    <Button
                      size="sm"
                      variant={alreadyBound ? "ghost" : "primary"}
                      disabled={alreadyBound || binding === doc.id}
                      onClick={() => bind(doc.id)}
                    >
                      {alreadyBound ? "已绑定" : binding === doc.id ? "绑定中…" : "绑定"}
                    </Button>
                  </li>
                );
              })}
            </ul>
            <p className="text-xs text-ink-muted">
              共 {total} 份文档{total > documents.length ? "，缩小关键词可以更快找到" : ""}。
            </p>
          </>
        )}
      </div>
    </Modal>
  );
}
