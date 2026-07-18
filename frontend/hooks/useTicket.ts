"use client";

import useSWR from "swr";
import { useCallback } from "react";
import { api, swrFetcher } from "@/lib/api";
import type {
  Requirement,
  Bug,
  Feed,
  AgentAdvanceResult,
} from "@/lib/types";
import type { AssigneeValue } from "@/components/AssigneePicker";

type Entity = "requirements" | "bugs";
type Ticket = Requirement | Bug;

// 工单详情抽屉的数据与写操作（§2.4）：拉 ticket + feed，
// 封装评论 / agent-advance / 指派 / 编辑 / 转 BUG，并在成功后 mutate 这两个 key。
export function useTicket(entity: Entity, id: number | null) {
  const ticketKey = id ? `/${entity}/${id}` : null;
  const feedKey = id ? `/${entity}/${id}/feed` : null;

  const {
    data: ticket,
    error: ticketError,
    isLoading: ticketLoading,
    mutate: mutateTicket,
  } = useSWR<Ticket>(ticketKey, swrFetcher);

  const {
    data: feed,
    isLoading: feedLoading,
    mutate: mutateFeed,
  } = useSWR<Feed>(feedKey, swrFetcher);

  const refresh = useCallback(() => {
    mutateTicket();
    mutateFeed();
  }, [mutateTicket, mutateFeed]);

  const addComment = useCallback(
    async (body: string) => {
      if (!id) return;
      await api.post(`/${entity}/${id}/comments`, { body });
      mutateFeed();
    },
    [entity, id, mutateFeed]
  );

  const advanceAgent = useCallback(async (): Promise<AgentAdvanceResult | null> => {
    if (!id) return null;
    const res = await api.post<AgentAdvanceResult>(`/${entity}/${id}/agent-advance`, {});
    mutateTicket();
    mutateFeed();
    return res;
  }, [entity, id, mutateTicket, mutateFeed]);

  const assign = useCallback(
    async (value: AssigneeValue) => {
      if (!id || !value.assignee_type || value.assignee_id == null) return;
      await api.patch(`/${entity}/${id}/assign`, value);
      mutateTicket();
      mutateFeed();
    },
    [entity, id, mutateTicket, mutateFeed]
  );

  const patch = useCallback(
    async (body: Record<string, unknown>) => {
      if (!id) return;
      // 【Phase-3 §2.5】乐观并发守卫：携当前已加载 ticket 的 updated_at；
      // 后端比对不一致 → 409（无 allowed），由调用方分流提示 + 刷新。
      const payload =
        ticket?.updated_at && body.expected_updated_at === undefined
          ? { ...body, expected_updated_at: ticket.updated_at }
          : body;
      await api.patch(`/${entity}/${id}`, payload);
      mutateTicket();
      mutateFeed();
    },
    [entity, id, ticket, mutateTicket, mutateFeed]
  );

  const convertToBug = useCallback(async (): Promise<Bug | null> => {
    if (!id || entity !== "requirements") return null;
    const bug = await api.post<Bug>(`/requirements/${id}/convert-to-bug`, {});
    mutateTicket();
    mutateFeed();
    return bug;
  }, [entity, id, mutateTicket, mutateFeed]);

  return {
    ticket,
    feed,
    isLoading: ticketLoading || feedLoading,
    error: ticketError,
    refresh,
    addComment,
    advanceAgent,
    assign,
    patch,
    convertToBug,
  };
}
