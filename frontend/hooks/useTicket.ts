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
  // 【H1】id 守卫与 TicketDrawer 统一为「正整数才有效」：此前 hook 判 falsy、抽屉判 `id == null`，
  // 二者不一致 → `?ticket=0` 会让抽屉铺开全屏遮罩却永远停在骨架态（key 为 null，永不返回数据）。
  const isValidId = id !== null && Number.isInteger(id) && id > 0;
  const ticketKey = isValidId ? `/${entity}/${id}` : null;
  const feedKey = isValidId ? `/${entity}/${id}/feed` : null;

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
      // 【§2.10-D4】用 PATCH 返回体（含新 updated_at）落缓存，使下一次乐观并发写携带新鲜时间戳，
      // 避免连续自我编辑（如连改优先级/严重度）在 mutate 回来前触发假 409（并发冲突误报）。
      const updated = await api.patch<Ticket>(`/${entity}/${id}`, payload);
      mutateTicket(updated, { revalidate: false });
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
