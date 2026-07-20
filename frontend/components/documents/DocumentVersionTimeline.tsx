"use client";

import { ApiError, downloadBlob, saveBlobAs } from "@/lib/api";
import { formatBytes } from "@/lib/constants";
import { useToast } from "@/lib/toast";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import { useDocumentDetail } from "@/hooks/useDocumentLibrary";
import type { DocumentSummary, DocumentVersion } from "@/lib/types";

interface Props {
  open: boolean;
  document: DocumentSummary | null;
  onClose: () => void;
  onPreview?: (version: DocumentVersion) => void;
}

function fullTime(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleString("zh-CN", {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit",
      });
}

// 版本历史（ticket-document-management §3.4）：版本号、备注、上传人、时间、下载。
//
// 「编辑」产生新版本而非覆盖原文件——研发文档的价值有一半在版本对比上，这里就是
// 那一半价值的入口：每一版都还能被单独下载回来。
export default function DocumentVersionTimeline({ open, document: doc, onClose, onPreview }: Props) {
  const toast = useToast();
  const { document: detail, isLoading } = useDocumentDetail(open ? doc?.id ?? null : null);
  const versions = detail?.versions ?? [];

  async function onDownload(version: DocumentVersion) {
    if (!doc) return;
    try {
      const { blob, filename } = await downloadBlob(
        `/documents/${doc.id}/download?version_id=${version.id}`);
      saveBlobAs(blob, filename || version.original_filename);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "下载失败");
    }
  }

  if (!doc) return null;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`「${doc.title}」的版本历史`}
      width={620}
      footer={<Button size="sm" variant="ghost" onClick={onClose}>关闭</Button>}
    >
      {isLoading && versions.length === 0 ? (
        <div className="py-8 text-center text-sm text-ink-muted">加载版本历史…</div>
      ) : (
        <ol className="space-y-2">
          {versions.map((version) => {
            const isCurrent = version.id === detail?.current_version?.id;
            return (
              <li
                key={version.id}
                className="rounded-lg border border-border px-3 py-2.5"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <span className="text-sm font-medium text-ink">
                    v{version.version_no}
                    {isCurrent && (
                      <span className="ml-2 rounded bg-[#D9EBDD] px-1.5 py-0.5 text-xs font-normal text-[#3E7A4F]">
                        当前
                      </span>
                    )}
                  </span>
                  <span className="text-xs text-ink-muted">
                    {version.uploader?.name ?? "—"} · {fullTime(version.created_at)}
                  </span>
                </div>
                <p className="mt-1 text-xs text-ink-muted">
                  {version.original_filename} · {formatBytes(version.size_bytes)}
                </p>
                {version.note && (
                  <p className="mt-1 text-xs text-ink">{version.note}</p>
                )}
                <div className="mt-2 flex gap-2">
                  {onPreview && (
                    <button
                      type="button"
                      onClick={() => onPreview(version)}
                      className="text-xs text-clay hover:underline"
                    >
                      预览此版本
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => onDownload(version)}
                    className="text-xs text-clay hover:underline"
                  >
                    下载此版本
                  </button>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Modal>
  );
}
