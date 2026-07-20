"use client";

import { useCallback, useMemo } from "react";
import useSWR, { useSWRConfig } from "swr";
import { api, listFetcher, swrFetcher } from "@/lib/api";
import { invalidateDocumentViews, invalidateTicketViews } from "@/lib/swr-keys";
import type { DocumentMeta, DocumentSummary } from "@/lib/types";

/**
 * 回收站列表 + 恢复 + 彻底删除（document-lifecycle-depth §3.3）。
 *
 * 失效逻辑收敛在这里而不是散在三个按钮上：软删 / 恢复 / purge 都会改变**工单侧**的
 * 徽章数字与阶段清单，因此每次写操作都必须**同时**调 `invalidateTicketViews`——
 * 上一轮 R7 的同一课，只调 `invalidateDocumentViews` 会让看板上的回形针数字停在旧值。
 */
export function useDocumentTrash(enabled = true) {
  const { mutate } = useSWRConfig();
  const key = enabled ? "/documents?deleted=1&limit=100" : null;

  const { data, error, isLoading, mutate: mutateList } =
    useSWR<{ items: DocumentSummary[]; total: number }>(key, listFetcher);

  const settle = useCallback(() => {
    mutateList();
    invalidateDocumentViews(mutate);
    invalidateTicketViews(mutate);
  }, [mutate, mutateList]);

  const restore = useCallback(
    async (documentId: number) => {
      const restored = await api.post<DocumentSummary>(
        `/documents/${documentId}/restore`, {});
      settle();
      return restored;
    },
    [settle]
  );

  const purge = useCallback(
    async (documentId: number) => {
      await api.del(`/documents/${documentId}?purge=1`);
      settle();
    },
    [settle]
  );

  return {
    documents: data?.items ?? [],
    total: data?.total ?? 0,
    isLoading,
    error,
    refresh: settle,
    restore,
    purge,
  };
}

/**
 * `GET /api/documents/meta`——模板清单 + 回收站保留期。
 *
 * 保留期**必须**由后端下发：前端硬编码 30 天而运维配了 7 天，用户就会按错误信息决定
 * 「这份文档还能放几天再说」（R-11）。响应是只读配置，SWR 长缓存即可。
 */
export function useDocumentMeta() {
  const { data, error, isLoading } = useSWR<DocumentMeta>("/documents/meta", swrFetcher, {
    revalidateOnFocus: false,
    dedupingInterval: 5 * 60 * 1000,
  });
  const templates = useMemo(() => data?.templates ?? [], [data]);
  return {
    templates,
    retentionDays: data?.trash_retention_days ?? null,
    previewMaxBytes: data?.text_preview_max_bytes ?? null,
    isLoading,
    error,
  };
}
