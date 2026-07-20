"use client";

import { useEffect, useRef, useState } from "react";
import { ApiError, downloadBlob, saveBlobAs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { canManageDocument } from "@/lib/permissions";
import { useProjectScope } from "@/lib/project-scope";
import { useToast } from "@/lib/toast";
import {
  DOCUMENT_KIND_OPTIONS,
  documentIcon,
  documentKindStyle,
  formatBytes,
} from "@/lib/constants";
import { useDocumentLibrary } from "@/hooks/useDocumentLibrary";
import Header from "@/components/layout/Header";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import EmptyState from "@/components/ui/EmptyState";
import ErrorState from "@/components/ui/ErrorState";
import Pagination from "@/components/ui/Pagination";
import { SkeletonRows } from "@/components/ui/Skeleton";
import DocumentPreviewModal from "@/components/documents/DocumentPreviewModal";
import DocumentTextEditorModal from "@/components/documents/DocumentTextEditorModal";
import DocumentUploadZone from "@/components/documents/DocumentUploadZone";
import DocumentVersionTimeline from "@/components/documents/DocumentVersionTimeline";
import type { DocumentSummary, DocumentVersion } from "@/lib/types";

// 与后端 pagination.DEFAULT_LIMIT 对齐，便于对照排查。
const PAGE_SIZE = 50;

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

// 文档库（ticket-document-management §3.4 / §6.1 触点 2）：跨工单的检索、管理与复用来源。
export default function DocumentsPage() {
  const toast = useToast();
  const { user } = useAuth();
  const { projects, scope } = useProjectScope();

  const [keyword, setKeyword] = useState("");
  const [debounced, setDebounced] = useState("");
  const [kind, setKind] = useState("");
  const [offset, setOffset] = useState(0);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [previewing, setPreviewing] = useState<
    { doc: DocumentSummary; version?: DocumentVersion | null } | null
  >(null);
  const [editing, setEditing] = useState<DocumentSummary | null>(null);
  const [versionsOf, setVersionsOf] = useState<DocumentSummary | null>(null);
  const [deleting, setDeleting] = useState<DocumentSummary | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(keyword.trim()), 300);
    return () => clearTimeout(t);
  }, [keyword]);

  // 换筛选条件就回到第一页——否则用户会看到一个「第 3 页却只有 2 条」的空表。
  const filterSignature = `${debounced}|${kind}|${String(scope ?? "")}`;
  const lastSignature = useRef(filterSignature);
  useEffect(() => {
    if (lastSignature.current !== filterSignature) {
      lastSignature.current = filterSignature;
      setOffset(0);
    }
  }, [filterSignature]);

  const projectId = typeof scope === "number" ? scope : undefined;
  const { documents, total, isLoading, error, refresh, upload, remove } =
    useDocumentLibrary({
      q: debounced || undefined,
      kind: kind || undefined,
      projectId,
      limit: PAGE_SIZE,
      offset,
    });

  async function onDownload(doc: DocumentSummary) {
    const version = doc.current_version;
    if (!version) return;
    try {
      const { blob, filename } = await downloadBlob(`/documents/${doc.id}/download`);
      saveBlobAs(blob, filename || version.original_filename);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "下载失败");
    }
  }

  return (
    <>
      <Header
        title="文档"
        subtitle={
          isLoading && documents.length === 0
            ? "需求与 BUG 的交付物都在这里"
            : `共 ${total} 份 · 一份文档可以同时服务多张单`
        }
        action={
          <Button size="sm" onClick={() => setUploadOpen((v) => !v)}>
            {uploadOpen ? "收起上传" : "＋ 上传文档"}
          </Button>
        }
      />

      <div className="space-y-4 p-6">
        {uploadOpen && (
          <div className="rounded-xl border border-border bg-surface p-4 shadow-card">
            <DocumentUploadZone
              onUpload={async (file, fields, options) =>
                upload(file, fields as Record<string, string>, options)
              }
            />
            <p className="mt-2 text-xs text-ink-muted">
              上传到文档库的文档暂不绑定任何工单——到需求 / BUG 的抽屉里用「绑定已有」把它挂上去。
            </p>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="按标题 / 描述搜索"
            aria-label="搜索文档"
            className="h-9 min-w-[12rem] flex-1 rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
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

        <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs uppercase tracking-wide text-ink-muted">
                  <th className="px-4 py-3 font-medium">标题</th>
                  <th className="px-4 py-3 font-medium">类型</th>
                  <th className="px-4 py-3 font-medium">文件</th>
                  <th className="px-4 py-3 font-medium">版本</th>
                  <th className="px-4 py-3 font-medium">被引用</th>
                  <th className="px-4 py-3 font-medium">上传人</th>
                  <th className="px-4 py-3 font-medium">更新</th>
                  <th className="px-4 py-3 text-right font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => {
                  const version = doc.current_version;
                  const mine = canManageDocument(user, doc);
                  return (
                    <tr
                      key={doc.id}
                      className="border-b border-border/60 last:border-0 hover:bg-black/[0.015]"
                    >
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          onClick={() => setPreviewing({ doc })}
                          className="flex items-center gap-2 text-left font-medium text-ink hover:text-clay"
                        >
                          <span aria-hidden="true">
                            {documentIcon(version?.original_filename)}
                          </span>
                          <span className="max-w-[18rem] truncate">{doc.title}</span>
                        </button>
                      </td>
                      <td className="px-4 py-3">
                        <Badge style={documentKindStyle(doc.kind)} />
                      </td>
                      <td className="px-4 py-3 text-ink-muted">
                        <span className="block max-w-[14rem] truncate">
                          {version?.original_filename ?? "—"}
                        </span>
                        <span className="text-xs">{formatBytes(version?.size_bytes)}</span>
                      </td>
                      <td className="px-4 py-3 text-ink-muted">
                        v{version?.version_no ?? 0}
                      </td>
                      <td className="px-4 py-3 text-ink-muted">
                        {doc.link_count > 0 ? `${doc.link_count} 张单` : "未绑定"}
                      </td>
                      <td className="px-4 py-3 text-ink-muted">
                        {doc.uploader?.name ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-xs text-ink-muted">
                        {fullTime(doc.updated_at)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex justify-end gap-1.5">
                          <Button size="sm" variant="ghost" onClick={() => onDownload(doc)}>
                            下载
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setVersionsOf(doc)}>
                            版本
                          </Button>
                          {doc.editable && mine && (
                            <Button size="sm" variant="ghost" onClick={() => setEditing(doc)}>
                              编辑
                            </Button>
                          )}
                          {mine && (
                            <Button size="sm" variant="danger" onClick={() => setDeleting(doc)}>
                              删除
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {error ? (
            <ErrorState message="无法加载文档库" onRetry={() => refresh()} />
          ) : isLoading && documents.length === 0 ? (
            <SkeletonRows />
          ) : documents.length === 0 ? (
            <EmptyState
              title={debounced || kind ? "没有匹配的文档" : "文档库还是空的"}
              hint={
                debounced || kind
                  ? "换个关键词或类型再试试。"
                  : "把需求说明、技术方案、测试报告传上来——它们可以被任意数量的需求与 BUG 复用。"
              }
              action={
                !debounced && !kind ? (
                  <Button size="sm" onClick={() => setUploadOpen(true)}>＋ 上传文档</Button>
                ) : undefined
              }
            />
          ) : null}
        </div>

        <Pagination
          offset={offset}
          limit={PAGE_SIZE}
          total={total}
          onOffset={setOffset}
          disabled={isLoading}
        />
      </div>

      <DocumentPreviewModal
        open={previewing != null}
        document={previewing?.doc ?? null}
        version={previewing?.version ?? null}
        onClose={() => setPreviewing(null)}
      />

      <DocumentTextEditorModal
        open={editing != null}
        document={editing}
        onClose={() => setEditing(null)}
        onSaved={() => refresh()}
      />

      <DocumentVersionTimeline
        open={versionsOf != null}
        document={versionsOf}
        onClose={() => setVersionsOf(null)}
        onPreview={(version) => {
          if (versionsOf) setPreviewing({ doc: versionsOf, version });
          setVersionsOf(null);
        }}
      />

      <ConfirmDialog
        open={deleting != null}
        title={`删除文档「${deleting?.title ?? ""}」`}
        description={
          deleting && deleting.link_count > 0 ? (
            <>
              这份文档仍被 <strong className="text-ink">{deleting.link_count} 张工单</strong> 引用。
              删除会同时解除这些绑定，并在每张单的时间线上留下记录，且
              <strong className="text-ink">不可恢复</strong>。
              如果只是想从某一张单上撤下它，请到那张单的抽屉里「解除绑定」。
            </>
          ) : (
            <>将永久删除这份文档及其全部历史版本，且不可恢复。</>
          )
        }
        onConfirm={async () => {
          if (!deleting) return;
          // 仍有绑定时后端返 409；带 ?force=1 才会连同绑定一起删（限 pm/admin）。
          await remove(deleting.id, deleting.link_count > 0);
          toast.success("已删除");
        }}
        onClose={() => setDeleting(null)}
      />
    </>
  );
}
