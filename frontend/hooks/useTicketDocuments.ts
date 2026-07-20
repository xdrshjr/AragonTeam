"use client";

import { useCallback } from "react";
import useSWR, { useSWRConfig } from "swr";
import {
  api,
  swrFetcher,
  uploadWithProgress,
  type UploadOptions,
} from "@/lib/api";
import { invalidateDocumentViews, invalidateTicketViews } from "@/lib/swr-keys";
import type { StageChecklist, TicketDocument } from "@/lib/types";

type Entity = "requirements" | "bugs";

export interface UploadFields {
  title?: string;
  kind?: string;
  description?: string;
  label?: string;
}

/**
 * 一张工单的文档列表 + 阶段清单 + 上传 / 绑定 / 解绑（ticket-document-management §3.4）。
 *
 * 【收尾的四次失效缺一不可，评审 R7】文档动作会改变四类视图：
 *   1. 本抽屉的文档列表；
 *   2. 本抽屉的时间线（doc_attached / doc_detached 是 Activity）；
 *   3. 本阶段清单的 `satisfied`；
 *   4. **看板与列表上的 `document_count` 回形针徽章** —— 只失效前三个，用户上传完
 *      关掉抽屉，看板上的数字仍是旧的，直到整页刷新。那正是上一轮通篇在消灭的
 *      「静默说谎的 UI」。第 4 项直接调现网 `invalidateTicketViews`（其前缀表已覆盖
 *      `/requirements`、`/bugs`、`/board/`），不必新造轮子。
 */
export function useTicketDocuments(entity: Entity, id: number | null) {
  const { mutate } = useSWRConfig();
  const isValidId = id !== null && Number.isInteger(id) && id > 0;
  const listKey = isValidId ? `/${entity}/${id}/documents` : null;
  const checklistKey = isValidId ? `/${entity}/${id}/document-checklist` : null;

  const {
    data: documents,
    error,
    isLoading,
    mutate: mutateList,
  } = useSWR<TicketDocument[]>(listKey, swrFetcher);

  const { data: checklist, mutate: mutateChecklist } =
    useSWR<StageChecklist>(checklistKey, swrFetcher);

  const settle = useCallback(() => {
    mutateList();
    mutateChecklist();
    if (isValidId) mutate(`/${entity}/${id}/feed`);
    invalidateTicketViews(mutate);
    invalidateDocumentViews(mutate);
  }, [entity, id, isValidId, mutate, mutateList, mutateChecklist]);

  const upload = useCallback(
    async (file: File, fields: UploadFields = {}, options: UploadOptions = {}) => {
      if (!isValidId) return null;
      const form = new FormData();
      form.append("file", file);
      for (const [key, value] of Object.entries(fields)) {
        if (value) form.append(key, value);
      }
      const result = await uploadWithProgress<{ document: TicketDocument }>(
        `/${entity}/${id}/documents`, form, options);
      settle();
      return result;
    },
    [entity, id, isValidId, settle]
  );

  const bindExisting = useCallback(
    async (documentId: number, label?: string) => {
      if (!isValidId) return null;
      const result = await api.post(`/${entity}/${id}/documents`,
                                    { document_id: documentId, label: label || undefined });
      settle();
      return result;
    },
    [entity, id, isValidId, settle]
  );

  const unbind = useCallback(
    async (documentId: number) => {
      if (!isValidId) return;
      await api.del(`/${entity}/${id}/documents/${documentId}`);
      settle();
    },
    [entity, id, isValidId, settle]
  );

  /** 用模板即时生成一份骨架并绑定（document-lifecycle-depth §2.3 C-1）。
   *
   * 走的是**同一个** `POST /{entity}/:id/documents` 端点的第三态，不新开路由——
   * 后端落库路径也与人工上传完全同一条（内容寻址 / 建 v1 / 写 doc_attached）。
   */
  const createFromTemplate = useCallback(
    async (templateKind: string, title?: string) => {
      if (!isValidId) return null;
      const result = await api.post(`/${entity}/${id}/documents`,
                                    { template_kind: templateKind,
                                      title: title || undefined });
      settle();
      return result;
    },
    [entity, id, isValidId, settle]
  );

  return {
    documents: documents ?? [],
    checklist,
    createFromTemplate,
    isLoading,
    error,
    refresh: settle,
    upload,
    bindExisting,
    unbind,
  };
}
