"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useSWRConfig } from "swr";
import { ApiError } from "@/lib/api";
import { invalidateHierarchyViews, invalidateTicketViews } from "@/lib/swr-keys";
import { useOverlayLayer } from "@/lib/overlay-stack";
import { useToast } from "@/lib/toast";
import { useAuth } from "@/lib/auth";
import { useTicket } from "@/hooks/useTicket";
import { canManageTicket } from "@/lib/permissions";
import { useProjectScope } from "@/lib/project-scope";
import type { Requirement, Bug, Priority, Severity } from "@/lib/types";
import { statusStyle, PRIORITY_STYLES, SEVERITY_STYLES } from "@/lib/constants";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import { AssigneeAvatar } from "@/components/ui/Avatar";
import AssigneePicker, { AssigneeValue } from "@/components/AssigneePicker";
import PlanPicker from "@/components/planning/PlanPicker";
import FeedTimeline from "@/components/collab/FeedTimeline";
import CommentComposer from "@/components/collab/CommentComposer";
import { SkeletonDrawer } from "@/components/ui/Skeleton";
import ErrorState from "@/components/ui/ErrorState";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import DocumentPanel from "@/components/documents/DocumentPanel";

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
  const { user } = useAuth();
  const { projects } = useProjectScope();
  const isBug = entity === "bugs";
  const { mutate } = useSWRConfig();
  const {
    ticket, feed, isLoading, error: ticketError,
    refresh, addComment, advanceAgent, assign, patch, convertToBug, remove,
  } = useTicket(entity, id);

  const [entered, setEntered] = useState(false);
  const [advancing, setAdvancing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [savingDetails, setSavingDetails] = useState(false);
  const [titleInput, setTitleInput] = useState("");
  const [descInput, setDescInput] = useState("");

  const [droppedFiles, setDroppedFiles] = useState<File[] | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const panelRef = useRef<HTMLDivElement>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const loadedRef = useRef<number | null>(null);

  // 抽屉是层栈的底层：模态开在它之上，Esc 与滚动锁的仲裁都经这里。
  const layer = useOverlayLayer(id != null);

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
  //
  // 【ticket-document-management §6.4 / 评审 R9】这个 window 级监听是本轮**唯一**必须
  // 改动的既有 a11y 代码：本轮的预览 / 编辑模态都开在抽屉之内，若它继续无条件响应 Esc，
  // 按一下就会把模态与抽屉一起关掉。现在先过层栈判定——只有栈顶层才消费 Esc。
  // 滚动锁同样交给层栈按引用计数管理，不再各层自行 set/restore `body.style`。
  useEffect(() => {
    if (id == null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && layer.isTop()) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [id, onClose, layer]);

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

  // 【§2.7-C1】写操作门禁：后端仍是权威，前端仅收敛「可见即可用」，避免无权成员点出 403。
  // 判据统一走 lib/permissions（与看板拖拽门禁共用，**不得**在此再内联一份——两份会漂移）。
  const canAssign = user?.role === "admin" || user?.role === "pm";
  const canManage = canManageTicket(user, ticket ?? null);

  const canAdvance = ticket?.assignee_type === "agent" && canManage;
  const canConvert =
    canAssign && // 转 BUG 后端限 pm/admin
    !isBug &&
    ((ticket as Requirement | undefined)?.status === "testing" ||
      (ticket as Requirement | undefined)?.status === "reviewing");

  async function onAdvance() {
    setAdvancing(true);
    try {
      await advanceAgent();
      toast.success("Agent 已推进到下一步");
      // 【version-plan-console §3.2 落点③】Agent 推进可能把单推进终态 → 分子变了。
      // 这是抽屉里**唯一**能改状态的入口（抽屉不提供状态下拉，status 只是只读徽章）。
      invalidateHierarchyViews(mutate);
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
    // 【lifecycle-and-governance §2.4-B2】「未指派」真正生效：此前这里弹一句
    // 「暂不支持在此取消指派」就返回，把一个渲染出来的选项做成了死控件。
    const clearing = !v.assignee_type || v.assignee_id == null;
    try {
      await assign(v);
      toast.success(clearing ? "已取消指派" : "指派已更新");
      onChanged?.();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : clearing ? "取消指派失败" : "指派失败");
    }
  }

  async function onDelete() {
    await remove();
    toast.success("已删除");
    onClose();          // 抽屉必须关闭：其 SWR key 已 404
    invalidateTicketViews(mutate);
    // 【version-plan-console §3.2 落点②】删单同时改分子与分母（若它归属某个计划）。
    invalidateHierarchyViews(mutate);
    onChanged?.();      // 外层列表 / 看板自身的 mutate
  }

  // 【Phase-3 §2.5】并发冲突（409 且无 allowed）→ 提示刷新并拉取最新，区别于状态机 409。
  function handleWriteError(err: unknown, fallback: string) {
    if (err instanceof ApiError && err.status === 409 && !err.allowed) {
      toast.error("该工单已被他人更新，已为你刷新最新内容");
      refresh();
      loadedRef.current = null; // 允许下次用最新值重置可编辑字段
      return;
    }
    toast.error(err instanceof ApiError ? err.message : fallback);
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
      handleWriteError(err, "保存失败");
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
      handleWriteError(err, "更新失败");
    }
  }

  /** 【version-plan-console §7.5 / §3.2 落点①】改计划归属。形状照抄 onLevelChange。
   *
   *  失效**必须**挂在这里：改归属会让**两个**计划的分母一进一出（原计划 -1、新计划 +1），
   *  两个版本的聚合进度随之变。抽屉里那个既有的 `invalidateTicketViews` 只挂在
   *  `onDelete` 上，跟这条路径毫无关系。 */
  async function onPlanChange(planId: number | null) {
    try {
      await patch({ plan_id: planId });
      toast.success(planId == null ? "已解除计划归属" : "已更新计划归属");
      invalidateHierarchyViews(mutate);
      onChanged?.();
    } catch (err) {
      // 跨项目 400 的中文来自后端，原样透出即可——`failureText` 那套翻译只服务
      // 批量结果弹窗，不要在这里再搭一层。
      handleWriteError(err, "更新计划归属失败");
    }
  }

  async function onConvert() {
    try {
      const bug = await convertToBug();
      toast.success(`已转为 BUG-${bug?.id}`);
      onChanged?.();
      onClose();
      // 【§2.7-C2】直达新 BUG 卡：带 ?ticket= 并派发 open-ticket 事件（看板据此自动打开抽屉），
      // 避免落到空看板；无 id 时兜底回看板首页。
      if (bug?.id != null) {
        router.push(`/bugs/board?ticket=${bug.id}`);
        window.dispatchEvent(
          new CustomEvent("aragon:open-ticket", { detail: { entity: "bugs", id: bug.id } })
        );
      } else {
        router.push("/bugs/board");
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "转 BUG 失败");
    }
  }

  async function onComment(body: string) {
    await addComment(body);
    // 评论不改看板，仅刷新 feed（已在 hook 内 mutate）。
  }

  // 确认文案要写清级联范围（§2.4-B1）：评论条数直接数 feed，不额外发请求。
  const commentCount = (feed?.items ?? []).filter((i) => i.kind === "comment").length;
  // 【§6.4】删除确认必须如实说明「文档不会被删」——对用户真实数据的推定是保留，
  // 而一句没说清的确认文案会让用户以为自己刚刚毁掉了一份 PRD。
  const documentCount = ticket?.document_count ?? 0;

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
          dragOver ? "ring-2 ring-clay/40" : "",
        ].join(" ")}
        onDragOver={(e) => {
          // 【§6.3】拖放区是**整个抽屉面板**，不只是那条虚线框：用户拖着文件时
          // 的目标是「这张单」，不是「那个小方框」。
          if (!canManage) return;
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOver(false);
        }}
        onDrop={(e) => {
          if (!canManage) return;
          e.preventDefault();
          setDragOver(false);
          const files = Array.from(e.dataTransfer.files || []);
          if (files.length) setDroppedFiles(files);
        }}
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

        {ticketError && !ticket ? (
          // 【§2.7-A2】深链 ?ticket=<已删 id> / 过期通知点击 → 接 useTicket().error，
          // 不再永久卡骨架；复用全站 ErrorState 原语（可重试），另给一个「关闭」出口
          // （header 右上的 × 亦可用）。
          <div className="flex flex-1 flex-col items-center justify-center">
            <ErrorState message="无法加载该工单（可能已被删除）" onRetry={() => refresh()} />
            <Button size="sm" variant="ghost" onClick={onClose}>
              关闭
            </Button>
          </div>
        ) : !ticket ? (
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
                    readOnly={!canManage}
                    className="h-10 rounded-lg border border-border bg-surface px-3 text-sm text-ink read-only:opacity-70 focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="text-sm font-medium text-ink">描述</label>
                  <textarea
                    value={descInput}
                    onChange={(e) => setDescInput(e.target.value)}
                    rows={3}
                    readOnly={!canManage}
                    className="resize-y rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink read-only:opacity-70 focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
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
                      disabled={!canManage}
                      className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink disabled:opacity-60 focus:border-clay focus:outline-none focus:ring-2 focus:ring-clay/20"
                    >
                      {levelOptions.map((o) => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                  </div>
                  {/* 【§2.7-C1】仅 canManage 显示保存按钮，避免无权成员点击必得 403。 */}
                  {canManage && (
                    <Button size="sm" variant="ghost" onClick={onSaveDetails} disabled={savingDetails}>
                      {savingDetails ? "保存中…" : "保存标题/描述"}
                    </Button>
                  )}
                </div>

                {/* 【§2.7-C1】改派仅 pm/admin 可见（后端 assign 限 pm/admin）。 */}
                {canAssign && <AssigneePicker value={assigneeValue} onChange={onAssignChange} />}

                {/* 【§7.5】改计划归属。`disabled` 用的是 `:147` 那个**行级** canManage
                    （canManageTicket），与后端 `PATCH /:id` 的门禁一致——**不是** /versions
                    页那个 admin｜pm 判据。两处同名不同义，极易串。 */}
                <PlanPicker
                  label="计划"
                  value={ticket.plan_id}
                  context={ticket.plan}
                  projectId={ticket.project_id}
                  disabled={!canManage}
                  onChange={onPlanChange}
                />

                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
                  <span className="inline-flex items-center gap-1">
                    负责人：
                    <AssigneeAvatar assignee={ticket.assignee} size={18} />
                    {ticket.assignee ? ticket.assignee.name : "未指派"}
                  </span>
                  {/* 【§2.4⑦】显示所属项目：此前抽屉里完全看不到工单归属哪个项目。 */}
                  <span>
                    项目：
                    {ticket.project_id == null
                      ? "未归属"
                      : projects?.find((p) => p.id === ticket.project_id)?.name ??
                        `#${ticket.project_id}`}
                  </span>
                  {/* 【version-plan-console §7.5】四层归属一眼可见。`plan` 是可选字段
                      （某些端点不富化），故一律按「缺省即无」渲染。 */}
                  <span>
                    版本 · 计划：
                    {ticket.plan
                      ? `${ticket.plan.version_name ?? "—"} · ${ticket.plan.name}`
                      : "未归属"}
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

              {/* 文档区（置于「协作时间线」之上：文档是流转的输入，时间线是流转的结果，
                  用户的阅读动线应当先看材料再看过程，§6.1）。 */}
              <DocumentPanel
                entity={entity}
                id={ticket.id}
                canManage={canManage}
                onChanged={onChanged}
                droppedFiles={droppedFiles}
                onDroppedConsumed={() => setDroppedFiles(null)}
              />

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

              {/* 【§2.4-B1】危险区：删除入口只放在「已经打开、已经读过内容」的抽屉里，
                  不放到看板卡片 / 列表行上——那里与「指派」相邻，误触代价不对等。 */}
              {canAssign && (
                <section className="border-t border-border px-5 py-4">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                    危险区
                  </h3>
                  <div className="mt-2 flex items-center justify-between gap-3">
                    <p className="text-xs text-ink-muted">
                      删除后不可恢复，其评论与协作时间线会一并清除。
                    </p>
                    <Button size="sm" variant="danger" onClick={() => setConfirmingDelete(true)}>
                      删除此{isBug ? " BUG" : "需求"}
                    </Button>
                  </div>
                </section>
              )}
            </div>

            {/* 评论输入（固定底部） */}
            <div className="border-t border-border bg-surface px-5 py-3">
              <CommentComposer onSubmit={onComment} />
            </div>
          </>
        )}
      </div>

      <ConfirmDialog
        open={confirmingDelete}
        title={`删除${isBug ? " BUG" : "需求"} ${prefix}-${id}`}
        description={
          <>
            将永久删除「{ticket?.title}」，
            <strong className="text-ink">
              连同它的 {commentCount} 条评论与全部协作时间线
            </strong>
            ，且不可恢复。
            {documentCount > 0 && (
              <>
                {" "}
                其绑定的 <strong className="text-ink">{documentCount} 份文档不会被删除</strong>
                ，将保留在文档库中。
              </>
            )}
          </>
        }
        onConfirm={onDelete}
        onClose={() => setConfirmingDelete(false)}
      />
    </div>
  );
}
