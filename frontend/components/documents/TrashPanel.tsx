"use client";

import { useState } from "react";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import ErrorState from "@/components/ui/ErrorState";
import { documentKindStyle } from "@/lib/constants";
import { canManageDocument, canPurgeDocument } from "@/lib/permissions";
import { useToast } from "@/lib/toast";
import { useDocumentTrash } from "@/hooks/useDocumentTrash";
import type { DocumentSummary, User } from "@/lib/types";

interface Props {
  user: User | null;
  retentionDays: number | null;
}

function fullTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleString("zh-CN", {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit",
      });
}

/** 剩余保留天数 = 保留期 − 已过天数；到期或未知返回 null。 */
function daysLeft(deletedAt: string | null, retentionDays: number | null): number | null {
  if (!deletedAt || retentionDays == null) return null;
  const deleted = new Date(deletedAt).getTime();
  if (Number.isNaN(deleted)) return null;
  const elapsed = (Date.now() - deleted) / 86_400_000;
  return Math.max(0, Math.ceil(retentionDays - elapsed));
}

/**
 * 回收站视图（document-lifecycle-depth §6.4）。
 *
 * 两处必须说出来的事：
 * 1. **回收站里的文档不可预览或下载**——详情 / content / download 三个端点都已被软删
 *    过滤成 404，这是有意的（回收站不是阅读场所，让被删文档继续可读等于删除没生效）。
 *    界面若不说，用户会以为是坏了。故行内**不提供预览按钮**，并在顶部给一句说明。
 * 2. **走 `force` 删除的那些，恢复不会带回绑定**——恢复确认框如实说明，否则用户会以为
 *    工单抽屉里的位置也会一起回来。
 */
export default function TrashPanel({ user, retentionDays }: Props) {
  const toast = useToast();
  const { documents, isLoading, error, restore, purge } = useDocumentTrash(true);
  const [restoring, setRestoring] = useState<DocumentSummary | null>(null);
  const [purging, setPurging] = useState<DocumentSummary | null>(null);
  const canPurge = canPurgeDocument(user);

  if (error) return <ErrorState message="无法加载回收站" />;

  return (
    <div className="space-y-3">
      <p className="rounded-lg border border-border bg-black/[0.015] px-3 py-2 text-xs text-ink-muted">
        回收站中的文档不可预览或下载，<strong className="font-medium text-ink">如需查看内容请先恢复</strong>。
        {retentionDays != null && `删除的文档会在这里保留 ${retentionDays} 天。`}
      </p>

      {isLoading && documents.length === 0 && (
        <div className="py-10 text-center text-sm text-ink-muted">加载回收站…</div>
      )}

      {!isLoading && documents.length === 0 && (
        <div className="rounded-lg border border-dashed border-border px-4 py-10 text-center text-sm text-ink-muted">
          回收站是空的。
          {retentionDays != null && `删除的文档会在这里保留 ${retentionDays} 天。`}
        </div>
      )}

      <ul className="space-y-1.5">
        {documents.map((doc) => {
          const left = daysLeft(doc.deleted_at, retentionDays);
          const urgent = left != null && left <= 3;
          return (
            <li
              key={doc.id}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-border px-3 py-2"
            >
              <Badge style={documentKindStyle(doc.kind)} className="shrink-0" />
              <span className="min-w-0 flex-1 truncate text-sm text-ink" title={doc.title}>
                {doc.title}
              </span>
              <span className="text-xs text-ink-muted">
                {doc.deleted_by?.name ?? "—"} · {fullTime(doc.deleted_at)}
              </span>
              {left != null && (
                <span className={urgent ? "text-xs text-[#B23B1E]" : "text-xs text-ink-muted"}>
                  剩 {left} 天
                </span>
              )}
              <div className="flex shrink-0 items-center gap-1.5">
                {canManageDocument(user, doc) && (
                  <Button size="sm" variant="ghost" onClick={() => setRestoring(doc)}>
                    恢复
                  </Button>
                )}
                {canPurge && (
                  <button
                    type="button"
                    onClick={() => setPurging(doc)}
                    className="rounded-md px-2 py-1 text-xs text-[#B23B1E] hover:bg-[#F3D2C7]/40 focus:outline-none focus:ring-2 focus:ring-clay/20"
                  >
                    彻底删除
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      <ConfirmDialog
        open={restoring !== null}
        title={`恢复「${restoring?.title ?? ""}」`}
        danger={false}
        confirmLabel="恢复"
        description={
          <>
            文档将回到文档库。
            <strong className="font-medium">
              若它当初是以「强制删除」方式移除的，与工单的绑定不会自动恢复
            </strong>
            ——那次操作已经解除了全部绑定，需要重新绑定一次。
          </>
        }
        onConfirm={async () => {
          if (!restoring) return;
          await restore(restoring.id);
          toast.success("已恢复");
          setRestoring(null);
        }}
        onClose={() => setRestoring(null)}
      />

      <ConfirmDialog
        open={purging !== null}
        title={`彻底删除「${purging?.title ?? ""}」`}
        confirmLabel="彻底删除"
        description={
          <>
            这是全系统<strong className="font-medium">唯一不可逆</strong>的文档操作：
            文档本体、全部历史版本与剩余绑定都会被永久删除，磁盘上的文件随后被回收。
            <strong className="font-medium">此操作无法撤销。</strong>
          </>
        }
        onConfirm={async () => {
          if (!purging) return;
          await purge(purging.id);
          toast.success("已彻底删除");
          setPurging(null);
        }}
        onClose={() => setPurging(null)}
      />
    </div>
  );
}
