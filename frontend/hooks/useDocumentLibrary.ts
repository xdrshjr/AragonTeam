"use client";

import { useCallback, useMemo } from "react";
import useSWR, { useSWRConfig } from "swr";
import {
  api,
  listFetcher,
  swrFetcher,
  uploadWithProgress,
  type UploadOptions,
} from "@/lib/api";
import { invalidateDocumentViews, invalidateTicketViews } from "@/lib/swr-keys";
import type { DocumentDetail, DocumentSummary } from "@/lib/types";

export interface LibraryFilters {
  q?: string;
  kind?: string;
  projectId?: number | null;
  limit?: number;
  offset?: number;
}

/** 文档库分页 / 筛选 / 上传 / 删除（ticket-document-management §3.4）。 */
export function useDocumentLibrary(filters: LibraryFilters = {}) {
  const { mutate } = useSWRConfig();
  const { q, kind, projectId, limit = 50, offset = 0 } = filters;

  const key = useMemo(() => {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (kind) params.set("kind", kind);
    if (projectId != null) params.set("project_id", String(projectId));
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    return `/documents?${params.toString()}`;
  }, [q, kind, projectId, limit, offset]);

  const { data, error, isLoading, mutate: mutateList } =
    useSWR<{ items: DocumentSummary[]; total: number }>(key, listFetcher);

  const settle = useCallback(() => {
    mutateList();
    invalidateDocumentViews(mutate);
    // 删除文档会连带解绑，工单侧的 document_count 徽章必须同步（评审 R7）。
    invalidateTicketViews(mutate);
  }, [mutate, mutateList]);

  const upload = useCallback(
    async (file: File, fields: Record<string, string | undefined> = {},
           options: UploadOptions = {}) => {
      const form = new FormData();
      form.append("file", file);
      for (const [k, v] of Object.entries(fields)) {
        if (v) form.append(k, v);
      }
      const created = await uploadWithProgress<DocumentSummary>("/documents", form, options);
      settle();
      return created;
    },
    [settle]
  );

  const remove = useCallback(
    async (documentId: number, force = false) => {
      await api.del(`/documents/${documentId}${force ? "?force=1" : ""}`);
      settle();
    },
    [settle]
  );

  const patch = useCallback(
    async (documentId: number, body: Record<string, unknown>) => {
      const updated = await api.patch<DocumentSummary>(`/documents/${documentId}`, body);
      settle();
      return updated;
    },
    [settle]
  );

  return {
    documents: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error,
    refresh: settle,
    upload,
    remove,
    patch,
  };
}

/** 单份文档的详情（版本历史 + 绑定关系）。 */
export function useDocumentDetail(documentId: number | null) {
  const key = documentId != null && documentId > 0 ? `/documents/${documentId}` : null;
  const { data, error, isLoading, mutate } = useSWR<DocumentDetail>(key, swrFetcher);
  return { document: data, error, isLoading, refresh: mutate };
}
