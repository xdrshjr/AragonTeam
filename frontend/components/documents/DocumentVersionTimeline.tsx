"use client";

import { useEffect, useState } from "react";
import { ApiError, api, downloadBlob, saveBlobAs } from "@/lib/api";
import { extensionOf, formatBytes, isTextExtension } from "@/lib/constants";
import { useToast } from "@/lib/toast";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { useDocumentDetail } from "@/hooks/useDocumentLibrary";
import type {
  DocumentRevisionResult,
  DocumentSummary,
  DocumentVersion,
} from "@/lib/types";

interface Props {
  open: boolean;
  document: DocumentSummary | null;
  onClose: () => void;
  onPreview?: (version: DocumentVersion) => void;
  /** 勾选恰好两个版本后点「对比」→ 交给 `DocumentDiffModal`（左旧右新）。 */
  onCompare?: (versions: [DocumentVersion, DocumentVersion]) => void;
  /** 回滚成功后通知调用方刷新列表 / 徽章。 */
  onRolledBack?: () => void;
  /** 无管理权时隐藏回滚入口（后端仍是权威）。 */
  canManage?: boolean;
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
export default function DocumentVersionTimeline({
  open,
  document: doc,
  onClose,
  onPreview,
  onCompare,
  onRolledBack,
  canManage = false,
}: Props) {
  const toast = useToast();
  const { document: detail, isLoading, refresh } =
    useDocumentDetail(open ? doc?.id ?? null : null);
  const versions = detail?.versions ?? [];
  const [selected, setSelected] = useState<number[]>([]);
  const [rollbackTarget, setRollbackTarget] = useState<DocumentVersion | null>(null);

  // 换文档 / 重新打开时清空勾选，避免上一份文档的选择残留。
  useEffect(() => setSelected([]), [doc?.id, open]);

  // **只对文本版本开放对比**：任一版本非文本时 `/content` 返 415，按钮置灰并解释。
  const textOnly = versions.every((v) => isTextExtension(extensionOf(v.original_filename)));
  const chosen = versions.filter((v) => selected.includes(v.id));
  const canCompare = chosen.length === 2 && textOnly;
  const compareHint = !textOnly
    ? "该文档不是文本类型，无法逐行对比"
    : chosen.length === 2
      ? ""
      : `请勾选恰好两个版本（已选 ${chosen.length} 个）`;

  function toggle(versionId: number) {
    setSelected((prev) =>
      prev.includes(versionId)
        ? prev.filter((id) => id !== versionId)
        : [...prev, versionId]
    );
  }

  async function doRollback(version: DocumentVersion) {
    if (!doc) return;
    const result = await api.post<DocumentRevisionResult>(
      `/documents/${doc.id}/versions`, { from_version_id: version.id });
    refresh();
    onRolledBack?.();
    toast.success(`已回滚到 v${version.version_no}（新版本 v${result.version.version_no}）`);
  }

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
                  <span className="flex items-center gap-2 text-sm font-medium text-ink">
                    {onCompare && (
                      <input
                        type="checkbox"
                        checked={selected.includes(version.id)}
                        onChange={() => toggle(version.id)}
                        aria-label={`选择 v${version.version_no} 用于对比`}
                        className="h-3.5 w-3.5 accent-[#C15F3C]"
                      />
                    )}
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
                  {canManage && !isCurrent && (
                    <button
                      type="button"
                      onClick={() => setRollbackTarget(version)}
                      className="text-xs text-clay hover:underline"
                    >
                      回滚到此版本
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {onCompare && versions.length > 1 && (
        <div className="mt-3 flex items-center justify-end gap-2">
          {compareHint && <span className="text-xs text-ink-muted">{compareHint}</span>}
          {/* 选中数 ≠ 2 时**禁用 + 解释**，而不是隐藏——消失的按钮无法被学会。 */}
          <Button
            size="sm"
            variant="ghost"
            disabled={!canCompare}
            title={compareHint || "对比选中的两个版本"}
            onClick={() => {
              if (!canCompare) return;
              const ordered = [...chosen].sort((a, b) => a.version_no - b.version_no);
              onCompare([ordered[0], ordered[1]]);
            }}
          >
            对比选中的两个版本
          </Button>
        </div>
      )}

      <ConfirmDialog
        open={rollbackTarget !== null}
        title={`回滚到 v${rollbackTarget?.version_no ?? ""}`}
        danger={false}
        confirmLabel="回滚"
        description={
          <>
            将以 v{rollbackTarget?.version_no} 的内容创建一个新版本 v
            {(detail?.versions[0]?.version_no ?? 0) + 1}。
            <strong className="font-medium">历史版本不会被删除</strong>，随时可以再滚回来。
          </>
        }
        onConfirm={async () => {
          if (!rollbackTarget) return;
          await doRollback(rollbackTarget);
          setRollbackTarget(null);
        }}
        onClose={() => setRollbackTarget(null)}
      />
    </Modal>
  );
}
