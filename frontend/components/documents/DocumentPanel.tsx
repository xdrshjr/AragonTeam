"use client";

import { useState } from "react";
import { ApiError, downloadBlob, saveBlobAs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { canManageDocument } from "@/lib/permissions";
import { useToast } from "@/lib/toast";
import { useTicketDocuments } from "@/hooks/useTicketDocuments";
import Button from "@/components/ui/Button";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import ErrorState from "@/components/ui/ErrorState";
import DocumentBindModal from "@/components/documents/DocumentBindModal";
import DocumentDiffModal from "@/components/documents/DocumentDiffModal";
import DocumentPreviewModal from "@/components/documents/DocumentPreviewModal";
import DocumentRow, { type RowAction } from "@/components/documents/DocumentRow";
import DocumentTextEditorModal from "@/components/documents/DocumentTextEditorModal";
import DocumentUploadZone from "@/components/documents/DocumentUploadZone";
import DocumentVersionTimeline from "@/components/documents/DocumentVersionTimeline";
import StageChecklist from "@/components/documents/StageChecklist";
import { useDocumentMeta } from "@/hooks/useDocumentTrash";
import type { DocumentSummary, DocumentVersion, TicketDocument } from "@/lib/types";

type Entity = "requirements" | "bugs";

interface Props {
  entity: Entity;
  id: number;
  /** can_manage_ticket 的结果——绑定 / 解绑的门禁与工单一致。 */
  canManage: boolean;
  /** 上传成功后通知外层（抽屉据此刷新自身的 ticket）。 */
  onChanged?: () => void;
  /** 面板级拖放：抽屉把整块面板上 drop 的文件转进来（§6.3）。 */
  droppedFiles?: File[] | null;
  onDroppedConsumed?: () => void;
}

// 抽屉内的「文档」区块（ticket-document-management §6.2）。
//
// 位置刻意放在「协作时间线」**之上**：文档是流转的输入，时间线是流转的结果，
// 用户的阅读动线应当先看材料、再看过程。
export default function DocumentPanel({
  entity, id, canManage, onChanged, droppedFiles, onDroppedConsumed,
}: Props) {
  const { user } = useAuth();
  const toast = useToast();
  const {
    documents, checklist, isLoading, error, refresh, upload, bindExisting, unbind,
    createFromTemplate,
  } = useTicketDocuments(entity, id);
  const { templates } = useDocumentMeta();

  const [presetKind, setPresetKind] = useState<string | undefined>(undefined);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [bindOpen, setBindOpen] = useState(false);
  const [previewing, setPreviewing] = useState<
    { doc: DocumentSummary; version?: DocumentVersion | null } | null
  >(null);
  const [editing, setEditing] = useState<DocumentSummary | null>(null);
  const [versionsOf, setVersionsOf] = useState<DocumentSummary | null>(null);
  const [unbinding, setUnbinding] = useState<TicketDocument | null>(null);
  const [diffing, setDiffing] = useState<
    { doc: DocumentSummary; versions: [DocumentVersion, DocumentVersion] } | null
  >(null);

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

  function actionsFor(doc: TicketDocument): RowAction[] {
    const actions: RowAction[] = [
      { key: "preview", label: "预览", onSelect: () => setPreviewing({ doc }) },
      { key: "download", label: "下载", onSelect: () => onDownload(doc) },
      { key: "versions", label: "版本历史", onSelect: () => setVersionsOf(doc) },
      // 「对比版本」与「版本历史」入口相同：勾选两版是对比的必经一步，做成两个
      // 并列入口只会让用户点错一次再退回来。
      { key: "compare", label: "对比版本", onSelect: () => setVersionsOf(doc) },
    ];
    // 「在线编辑」只在文档结构上可编辑、且用户有权改版时出现。后端在 POST /versions
    // 里独立复核同一判据——前端隐藏只是收敛，不是防线。
    if (doc.editable && canManageDocument(user, doc)) {
      actions.push({ key: "edit", label: "在线编辑", onSelect: () => setEditing(doc) });
    }
    if (canManage) {
      actions.push({
        key: "unbind", label: "解除绑定", danger: true,
        onSelect: () => setUnbinding(doc),
      });
    }
    return actions;
  }

  function fillMissing(kind: string) {
    setPresetKind(kind);
    setUploadOpen(true);
  }

  async function fillFromTemplate(kind: string) {
    try {
      await createFromTemplate(kind);
      onChanged?.();
      toast.success("已按模板新建并绑定，去补全内容吧");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "模板新建失败");
    }
  }

  return (
    <section className="border-b border-border px-5 py-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-ink">
          文档
          <span className="ml-1.5 font-normal text-ink-muted">({documents.length})</span>
        </h3>
        {canManage && (
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" onClick={() => { setPresetKind(undefined); setUploadOpen((v) => !v); }}>
              {uploadOpen ? "收起上传" : "＋ 上传"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setBindOpen(true)}>
              🔗 绑定已有
            </Button>
          </div>
        )}
      </div>

      <div className="space-y-3">
        <StageChecklist
          checklist={checklist}
          onFill={fillMissing}
          onCreateFromTemplate={fillFromTemplate}
          templates={templates}
          canUpload={canManage}
        />

        {error ? (
          <ErrorState message="无法加载本工单的文档" onRetry={() => refresh()} />
        ) : isLoading && documents.length === 0 ? (
          <div className="py-4 text-center text-sm text-ink-muted">加载文档…</div>
        ) : documents.length === 0 ? (
          <p className="px-2 py-3 text-xs text-ink-muted">
            还没有文档。{canManage ? "把需求说明、方案、测试报告传上来，它们会跟着这张单一起流转。" : ""}
          </p>
        ) : (
          <div className="-mx-2">
            {documents.map((doc) => (
              <DocumentRow
                key={doc.link.id}
                document={doc}
                showStage
                actions={actionsFor(doc)}
                onOpen={() => setPreviewing({ doc })}
              />
            ))}
          </div>
        )}

        {canManage && (uploadOpen || (droppedFiles && droppedFiles.length > 0)) && (
          <DocumentUploadZone
            presetKind={presetKind}
            externalFiles={droppedFiles}
            onExternalConsumed={onDroppedConsumed}
            onUpload={async (file, fields, options) => {
              const result = await upload(file, fields, options);
              onChanged?.();
              return result;
            }}
          />
        )}
      </div>

      <DocumentBindModal
        open={bindOpen}
        boundIds={documents.map((d) => d.id)}
        onBind={async (documentId, label) => {
          await bindExisting(documentId, label);
          onChanged?.();
        }}
        onClose={() => setBindOpen(false)}
      />

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
        onSaved={() => { refresh(); onChanged?.(); }}
      />

      <DocumentVersionTimeline
        open={versionsOf != null}
        document={versionsOf}
        canManage={canManageDocument(user, versionsOf)}
        onClose={() => setVersionsOf(null)}
        onPreview={(version) => {
          if (versionsOf) setPreviewing({ doc: versionsOf, version });
          setVersionsOf(null);
        }}
        onCompare={(versions) => {
          if (!versionsOf) return;
          setDiffing({ doc: versionsOf, versions });
          setVersionsOf(null);
        }}
        onRolledBack={() => { refresh(); onChanged?.(); }}
      />

      <DocumentDiffModal
        open={diffing != null}
        document={diffing?.doc ?? null}
        versions={diffing?.versions ?? null}
        onClose={() => setDiffing(null)}
      />

      <ConfirmDialog
        open={unbinding != null}
        title="解除文档绑定"
        confirmLabel="解除绑定"
        description={
          <>
            将把「{unbinding?.title}」从本{entity === "bugs" ? " BUG" : "需求"}上解除绑定。
            <strong className="text-ink">文档本身不会被删除</strong>
            ，它仍保留在文档库中，也不影响它绑定的其他工单。
          </>
        }
        onConfirm={async () => {
          if (!unbinding) return;
          await unbind(unbinding.id);
          toast.success("已解除绑定");
          onChanged?.();
        }}
        onClose={() => setUnbinding(null)}
      />
    </section>
  );
}
