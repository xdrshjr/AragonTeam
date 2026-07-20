"use client";

import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { DOCUMENT_KIND_OPTIONS } from "@/lib/constants";
import { useToast } from "@/lib/toast";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Modal from "@/components/ui/Modal";
import type { DocumentKind, DocumentSummary } from "@/lib/types";

interface Props {
  open: boolean;
  document: DocumentSummary | null;
  /** 走 `useDocumentLibrary.patch()`——它此前**已实现却没有任何 UI 调用方**。 */
  onSave: (id: number, body: Record<string, unknown>) => Promise<unknown>;
  onClose: () => void;
}

/**
 * 「编辑信息」：标题 / 类型 / 描述三字段 + 乐观锁（document-lifecycle-depth §2.1 A-4②）。
 *
 * 补的是一个真实缺口：`PATCH /api/documents/:id` 与 `useDocumentLibrary.patch()` 都早已
 * 就绪，但**没有任何界面调它**——改一份文档的标题 / 类型 / 描述在今天的界面上做不到。
 *
 * `expected_updated_at` 是既有的乐观锁字段（后端 `check_concurrency` 已就绪）：两个标签页
 * 同时打开时，后保存的一方拿到 409 并在此就地显示，而不是静默覆盖别人的改动。
 */
export default function DocumentMetaModal({ open, document: doc, onSave, onClose }: Props) {
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<DocumentKind>("other");
  const [description, setDescription] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 每次打开都从当前值开始，避免上一份文档的输入残留。
  useEffect(() => {
    if (!open || !doc) return;
    setTitle(doc.title);
    setKind(doc.kind);
    setDescription(doc.description ?? "");
    setError(null);
  }, [open, doc]);

  if (!doc) return null;

  async function submit() {
    if (!doc) return;
    const trimmed = title.trim();
    if (!trimmed) {
      setError("标题不能为空");
      return;
    }
    setPending(true);
    setError(null);
    try {
      await onSave(doc.id, {
        title: trimmed,
        kind,
        description: description.trim() || null,
        expected_updated_at: doc.updated_at,
      });
      toast.success("已更新");
      onClose();
    } catch (err) {
      // 409（别人先改了）必须**就地读到**，弹一个转瞬即逝的 toast 然后关窗是最差解。
      setError(err instanceof ApiError ? err.message : "保存失败");
    } finally {
      setPending(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={pending ? () => {} : onClose}
      title="编辑文档信息"
      width={480}
      footer={
        <>
          <Button size="sm" variant="ghost" onClick={onClose} disabled={pending}>
            取消
          </Button>
          <Button size="sm" onClick={submit} disabled={pending}>
            {pending ? "保存中…" : "保存"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-ink">标题</span>
          <Input
            value={title}
            maxLength={200}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="文档标题"
          />
        </label>

        <label className="block">
          <span className="mb-1 block text-xs font-medium text-ink">类型</span>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as DocumentKind)}
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-clay/20"
          >
            {DOCUMENT_KIND_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="mb-1 block text-xs font-medium text-ink">描述</span>
          <textarea
            value={description}
            rows={3}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="这份文档是做什么的（可留空）"
            className="w-full resize-y rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-clay/20"
          />
        </label>

        {error && (
          <p role="alert" className="text-xs text-[#B23B1E]">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}
