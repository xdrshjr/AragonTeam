"use client";

import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useDocumentContent } from "@/hooks/useDocumentContent";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import ErrorState from "@/components/ui/ErrorState";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import type { DocumentSummary } from "@/lib/types";

interface Props {
  open: boolean;
  document: DocumentSummary | null;
  onClose: () => void;
  onSaved?: () => void;
}

// 文本正文在线编辑 → 提交为新版本（ticket-document-management §2.6）。
//
// 两条不肯让步的规则：
//   1. **有未保存内容时，Esc 与遮罩点击必须先弹二次确认**（§6.4）。
//   2. **`editable` 为假时只读**，并**如实说明原因**——而不是让「编辑」按钮神秘消失。
//      后端在 `POST /versions` 里独立复核同一判据；前端隐藏只是收敛，不是防线。
export default function DocumentTextEditorModal({ open, document: doc, onClose, onSaved }: Props) {
  const toast = useToast();
  const { content, isLoading, error, save } = useDocumentContent(open ? doc?.id ?? null : null);
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");
  const [loadedFor, setLoadedFor] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirmingDiscard, setConfirmingDiscard] = useState(false);

  // 首次拿到正文时灌进编辑器；后续 revalidate 不覆盖用户正在敲的内容
  // （与 TicketDrawer 的 loadedRef 同款策略）。
  useEffect(() => {
    if (content && loadedFor !== content.version_id) {
      setLoadedFor(content.version_id);
      setDraft(content.content);
      setNote("");
    }
  }, [content, loadedFor]);

  useEffect(() => {
    if (!open) {
      setLoadedFor(null);
      setConfirmingDiscard(false);
    }
  }, [open]);

  const dirty = content != null && draft !== content.content;
  const readOnly = !content?.editable;

  function requestClose() {
    if (dirty && !saving) {
      setConfirmingDiscard(true);
      return;
    }
    onClose();
  }

  async function onSave() {
    if (!doc || readOnly) return;
    setSaving(true);
    try {
      const result = await save(draft, note.trim() || undefined);
      if (result?.fanout_truncated) {
        // 如实告知：假装 60 条提醒都发了，比只发 20 条更糟。
        toast.info(
          `已保存为 v${result.version.version_no}；该文档绑定了 ${result.link_count} 张单，` +
          `本次仅向前 ${result.fanout_written} 张写入了提醒`
        );
      } else {
        toast.success(`已保存为 v${result?.version.version_no ?? "新版本"}`);
      }
      onSaved?.();
      onClose();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast.error(err.message);          // 版本冲突 / 不可编辑，后端已给出可读文案
      } else {
        toast.error(err instanceof ApiError ? err.message : "保存失败");
      }
    } finally {
      setSaving(false);
    }
  }

  if (!doc) return null;

  const reason = (content as any)?.reason as string | undefined;

  return (
    <>
      <Modal
        open={open && !confirmingDiscard}
        onClose={requestClose}
        title={`编辑「${doc.title}」`}
        width={820}
        footer={
          <>
            <Button size="sm" variant="ghost" onClick={requestClose} disabled={saving}>
              取消
            </Button>
            <Button size="sm" onClick={onSave} disabled={readOnly || !dirty || saving}>
              {saving ? "保存中…" : "保存为新版本"}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {isLoading && !content && (
            <div className="py-10 text-center text-sm text-ink-muted">加载正文…</div>
          )}

          {error && <ErrorState message="无法读取该文档的正文" />}

          {content && !content.encoding_confident && (
            <div className="rounded-lg border border-[#F6E7C8] bg-[#F6E7C8]/40 px-3 py-2 text-xs text-[#8A6716]">
              该文件不是 UTF-8 编码，可预览、不可在线编辑。
              强行保存会把每个不可解码的字节写成 �，原文件将不可逆损毁。请下载后用本地
              编辑器处理，再作为新版本上传。
            </div>
          )}
          {content && content.truncated && (
            <div className="rounded-lg border border-[#F6E7C8] bg-[#F6E7C8]/40 px-3 py-2 text-xs text-[#8A6716]">
              该文件超过预览上限，下面只显示了开头一部分，因此**不可**在线编辑——
              否则保存下去，截断的部分就会成为新版本的全部内容。
            </div>
          )}
          {content && !content.editable && !content.truncated && content.encoding_confident && (
            <div className="rounded-lg border border-border bg-black/[0.02] px-3 py-2 text-xs text-ink-muted">
              该文档不支持在线编辑{reason ? `（${reason}）` : ""}，可下载后修改，再作为新版本上传。
            </div>
          )}

          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            readOnly={readOnly}
            rows={20}
            spellCheck={false}
            aria-label="文档正文"
            className="w-full resize-y rounded-lg border border-border bg-surface px-3 py-2 font-mono text-xs leading-relaxed text-ink read-only:opacity-70 focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
          />

          <div className="flex flex-col gap-1.5">
            <label htmlFor="doc-version-note" className="text-xs text-ink-muted">
              本次修改备注（会出现在版本历史与协作时间线里）
            </label>
            <input
              id="doc-version-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              readOnly={readOnly}
              maxLength={255}
              placeholder="例如：补充降级方案"
              className="h-9 rounded-lg border border-border bg-surface px-3 text-sm text-ink read-only:opacity-70 focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
            />
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={confirmingDiscard}
        title="放弃未保存的修改？"
        description="你对正文的改动尚未保存为新版本，关闭后将丢失。"
        onConfirm={async () => {
          setConfirmingDiscard(false);
          onClose();
        }}
        onClose={() => setConfirmingDiscard(false)}
      />
    </>
  );
}
