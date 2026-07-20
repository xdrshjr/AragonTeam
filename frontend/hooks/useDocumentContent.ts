"use client";

import { useCallback } from "react";
import useSWR, { useSWRConfig } from "swr";
import { api, swrFetcher } from "@/lib/api";
import { invalidateDocumentViews, invalidateTicketViews } from "@/lib/swr-keys";
import type { DocumentContent, DocumentRevisionResult } from "@/lib/types";

/**
 * 文本正文读取 + 保存为新版本（ticket-document-management §3.4）。
 *
 * `save` 携带 `expected_version_id`：与 `document.current_version_id` 不符时后端返 409，
 * 前端据此提示「已被他人改过」。这是本轮对「多人同时编辑」给出的**冲突可检测**下限——
 * 真正的协同编辑需要 OT/CRDT + WebSocket，量级远超本轮（§10 Non-Goals）。
 */
export function useDocumentContent(documentId: number | null, versionId?: number | null) {
  const { mutate } = useSWRConfig();
  const key =
    documentId != null && documentId > 0
      ? `/documents/${documentId}/content${versionId ? `?version_id=${versionId}` : ""}`
      : null;

  const { data, error, isLoading, mutate: mutateContent } =
    useSWR<DocumentContent>(key, swrFetcher);

  const save = useCallback(
    async (content: string, note?: string) => {
      if (documentId == null) return null;
      const result = await api.post<DocumentRevisionResult>(
        `/documents/${documentId}/versions`,
        { content, note: note || undefined, expected_version_id: data?.version_id }
      );
      mutateContent();
      mutate(`/documents/${documentId}`);
      invalidateDocumentViews(mutate);
      // 改版会向绑定的工单扇出 doc_revised 时间线，工单视图必须一并失效（评审 R7）。
      invalidateTicketViews(mutate);
      return result;
    },
    [documentId, data?.version_id, mutate, mutateContent]
  );

  return { content: data, error, isLoading, refresh: mutateContent, save };
}
