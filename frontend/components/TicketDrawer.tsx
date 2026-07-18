"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useTicket } from "@/hooks/useTicket";
import type { Requirement, Bug, Priority, Severity } from "@/lib/types";
import { statusStyle, PRIORITY_STYLES, SEVERITY_STYLES } from "@/lib/constants";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import { AssigneeAvatar } from "@/components/ui/Avatar";
import AssigneePicker, { AssigneeValue } from "@/components/AssigneePicker";
import FeedTimeline from "@/components/collab/FeedTimeline";
import CommentComposer from "@/components/collab/CommentComposer";
import { SkeletonDrawer } from "@/components/ui/Skeleton";

type Entity = "requirements" | "bugs";

interface Props {
  entity: Entity;
  id: number | null;
  onClose: () => void;
  // 抽屉内写操作成功后回调，供外层 mutate 看板 / 列表，保证同步（§2.4）。
  onChanged?: () => void;
}

const PRIORITY_OPTIONS = (Object.keys(PRIORITY_STYLES) as Priority[]).map((k) => ({
  value: k,
  label: PRIORITY_STYLES[k].label,
}));
const SEVERITY_OPTIONS = (Object.keys(SEVERITY_STYLES) as Severity[]).map((k) => ({
  value: k,
  label: SEVERITY_STYLES[k].label,
}));

function shortTime(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

// 工单详情右侧抽屉（§2.4）：详情 + 协作 feed + 评论框 + 让 Agent 处理。
// 需求 / BUG 共用（以 entity 区分）。a11y：role=dialog、aria-modal、Esc/遮罩关闭、焦点管理。
export default function TicketDrawer({ entity, id, onClose, onChanged }: Props) {
  const router = useRouter();
  const toast = useToast();
  const isBug = entity === "bugs";
  const {
    ticket, feed, isLoading,
    refresh, addComment, advanceAgent, assign, patch, convertToBug,
  } = useTicket(entity, id);

  const [entered, setEntered] = useState(false);
  const [advancing, setAdvancing] = useState(false);
  const [savingDetails, setSavingDetails] = useState(false);
  const [titleInput, setTitleInput] = useState("");
  const [descInput, setDescInput] = useState("");

  const panelRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const loadedRef = useRef<number | null>(null);

  // 进出滑动动画（enter）。
  useEffect(() => {
    if (id == null) {
      setEntered(false);
      loadedRef.current = null;
      return;
    }
    const raf = requestAnimationFrame(() => setEntered(true));
    return () => cancelAnimationFrame(raf);
  }, [id]);

  // Esc 关闭 + 打开时锁滚动。
  useEffect(() => {
    if (id == null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [id, onClose]);

  // 焦点管理：打开移入面板，关闭归还触发元素。
  useEffect(() => {
    if (id == null) return;
    restoreRef.current = document.activeElement as HTMLElement;
    const t = setTimeout(() => panelRef.current?.focus(), 60);
    return () => {
      clearTimeout(t);
      restoreRef.current?.focus?.();
    };
  }, [id]);

  // 当 ticket 首次为该 id 加载时，用其值初始化可编辑字段（后续 revalidate 不覆盖用户编辑）。
  useEffect(() => {
    if (ticket && loadedRef.current !== ticket.id) {
      loadedRef.current = ticket.id;
      setTitleInput(ticket.title);
      setDescInput(ticket.description || "");
    }
  }, [ticket]);

  if (id == null) return null;

  const priorityBadge = ticket
    ? isBug
      ? SEVERITY_STYLES[(ticket as Bug).severity]
      : PRIORITY_STYLES[(ticket as Requirement).priority]
    : null;

  const assigneeValue: AssigneeValue = {
    assignee_type: ticket?.assignee_type ?? null,
    assignee_id: ticket?.assignee_id ?? null,
  };

  const canAdvance = ticket?.assignee_type === "agent";
  const canConvert =
    !isBug &&
    ((ticket as Requirement | undefined)?.status === "testing" ||
      (ticket as Requirement | undefined)?.status === "reviewing");

  async function onAdvance() {
    setAdvancing(true);
    try {
      await advanceAgent();
      toast.success("Agent 已推进到下一步");
      onChanged?.();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast.info(err.message); // 无预置动作 / 未指派 Agent
      } else {
        toast.error(err instanceof ApiError ? err.message : "推进失败");
      }
    } finally {
      setAdvancing(false);
    }
  }

  async function onAssignChange(v: AssigneeValue) {
    if (!v.assignee_type || v.assignee_id == null) {
      toast.info("暂不支持在此取消指派");
      return;
    }
    try {
      await assign(v);
      toast.success("指派已更新");
      onChanged?.();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "指派失败");
    }
  }

  async function onSaveDetails() {
    if (!titleInput.trim()) {
      toast.error("标题不能为空");
      return;
    }
    setSavingDetails(true);
    try {
      await patch({ title: titleInput.trim(), description: descInput });
      toast.success("已保存");
      onChanged?.();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "保存失败");
    } finally {
      setSavingDetails(false);
    }
  }

  async function onLevelChange(value: string) {
    try {
      await patch(isBug ? { severity: value } : { priority: value });
      toast.success("已更新");
      onChanged?.();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "更新失败");
    }
  }

  async function onConvert() {
    try {
      const bug = await convertToBug();
      toast.success(`已转为 BUG-${bug?.id}`);
      onChanged?.();
      onClose();
      router.push("/bugs/board");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "转 BUG 失败");
    }
  }

  async function onComment(body: string) {
    await addComment(body);
    // 评论不改看板，仅刷新 feed（已在 hook 内 mutate）。
  }

  const prefix = isBug ? "BUG" : "REQ";
  const levelOptions = isBug ? SEVERITY_OPTIONS : PRIORITY_OPTIONS;
  const levelValue = ticket
    ? isBug
      ? (ticket as Bug).severity
      : (ticket as Requirement).priority
    : "";

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="工单详情">
      {/* 遮罩 */}
      <div
        className={[
          "absolute inset-0 bg-ink/30 transition-opacity duration-200",
          entered ? "opacity-100" : "opacity-0",
        ].join(" ")}
        onClick={onClose}
      />

      {/* 面板 */}
      <div
        ref={panelRef}
        tabIndex={-1}
        className={[
          "absolute inset-y-0 right-0 flex w-full max-w-[480px] flex-col bg-bg shadow-lift outline-none",
          "transition-transform duration-200 ease-out",
          entered ? "translate-x-0" : "translate-x-full",
        ].join(" ")}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-border bg-surface px-5 py-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-ink-muted">
                {prefix}-{id}
              </span>
              {ticket && <Badge style={statusStyle(ticket.status)} />}
              {priorityBadge && <Badge style={priorityBadge} />}
            </div>
            <h2 className="mt-1 truncate font-serif text-lg text-ink">
              {ticket?.title ?? "加载中…"}
            </h2>
          </div>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="rounded-md p-1 text-ink-muted hover:bg-black/[0.04] hover:text-ink"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        {!ticket ? (
          <SkeletonDrawer />
        ) : (
          <>
            <div className="flex-1 overflow-y-auto">
              {/* 详情区 */}
              <section className="space-y-4 border-b border-border px-5 py-4">
                <div className="flex flex-col gap-1.5">
                  <label className="text-sm font-medium text-ink">标题</label>
                  <input
                    value={titleInput}
                    onChange={(e) => setTitleInput(e.target.value)}
                    className="h-10 rounded-lg border border-border bg-surface px-3 text-sm text-ink focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="text-sm font-medium text-ink">描述</label>
                  <textarea
                    value={descInput}
                    onChange={(e) => setDescInput(e.target.value)}
                    rows={3}
                    className="resize-y rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
                  />
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex flex-col gap-1.5">
                    <label className="text-sm font-medium text-ink">
                      {isBug ? "严重度" : "优先级"}
                    </label>
                    <select
                      value={levelValue}
                      onChange={(e) => onLevelChange(e.target.value)}
                      className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
                    >
                      {levelOptions.map((o) => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                  </div>
                  <Button size="sm" variant="ghost" onClick={onSaveDetails} disabled={savingDetails}>
                    {savingDetails ? "保存中…" : "保存标题/描述"}
                  </Button>
                </div>

                <AssigneePicker value={assigneeValue} onChange={onAssignChange} />

                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
                  <span className="inline-flex items-center gap-1">
                    负责人：
                    <AssigneeAvatar assignee={ticket.assignee} size={18} />
                    {ticket.assignee ? ticket.assignee.name : "未指派"}
                  </span>
                  <span>创建：{shortTime(ticket.created_at)}</span>
                  <span>更新：{shortTime(ticket.updated_at)}</span>
                </div>

                {canConvert && (
                  <Button size="sm" variant="danger" onClick={onConvert}>
                    转为 BUG（源需求转入「修复中」）
                  </Button>
                )}
              </section>

              {/* 协作区 */}
              <section className="px-5 py-4">
                <div className="mb-3 flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-ink">协作时间线</h3>
                  {canAdvance && (
                    <Button size="sm" onClick={onAdvance} disabled={advancing}>
                      {advancing
                        ? "处理中…"
                        : `▶ 让 ${ticket.assignee?.name || "Agent"} 处理下一步`}
                    </Button>
                  )}
                </div>
                {isLoading && !feed ? (
                  <div className="py-6 text-center text-sm text-ink-muted">加载协作记录…</div>
                ) : (
                  <FeedTimeline items={feed?.items ?? []} />
                )}
              </section>
            </div>

            {/* 评论输入（固定底部） */}
            <div className="border-t border-border bg-surface px-5 py-3">
              <CommentComposer onSubmit={onComment} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
