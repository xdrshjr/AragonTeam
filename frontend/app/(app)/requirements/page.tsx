"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { api, listFetcher, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useAuth } from "@/lib/auth";
import type { Requirement } from "@/lib/types";
import { statusStyle, PRIORITY_STYLES } from "@/lib/constants";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import Modal from "@/components/ui/Modal";
import { AssigneeAvatar } from "@/components/ui/Avatar";
import { SkeletonRows } from "@/components/ui/Skeleton";
import EmptyState from "@/components/ui/EmptyState";
import RequirementForm from "@/components/requirements/RequirementForm";
import AssigneePicker, { AssigneeValue } from "@/components/AssigneePicker";
import TicketDrawer from "@/components/TicketDrawer";

export default function RequirementsPage() {
  const toast = useToast();
  const { user } = useAuth();
  // 后端 POST /requirements 限 admin|pm（§2.4），member 隐藏新建入口，避免提交后才 403。
  const canCreate = user?.role === "admin" || user?.role === "pm";
  const { data, mutate } = useSWR("/requirements", listFetcher<Requirement>);
  const reqs = data?.items;
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const [assignTarget, setAssignTarget] = useState<Requirement | null>(null);
  const [assignee, setAssignee] = useState<AssigneeValue>({
    assignee_type: null,
    assignee_id: null,
  });

  async function doAssign() {
    if (!assignTarget || !assignee.assignee_type) {
      toast.error("请选择指派对象");
      return;
    }
    try {
      await api.patch(`/requirements/${assignTarget.id}/assign`, assignee);
      toast.success("指派成功");
      setAssignTarget(null);
      setAssignee({ assignee_type: null, assignee_id: null });
      mutate();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "指派失败");
    }
  }

  return (
    <>
      <Header
        title="需求"
        subtitle={data ? `共 ${data.total} 条 · 点击行查看详情与协作` : "创建、指派与跟踪需求"}
        action={
          <div className="flex items-center gap-2">
            <Link href="/requirements/board">
              <Button variant="ghost" size="sm">
                看板视图
              </Button>
            </Link>
            {canCreate && (
              <Button size="sm" onClick={() => setCreating(true)}>
                + 新建需求
              </Button>
            )}
          </div>
        }
      />
      <main className="flex-1 overflow-y-auto p-6">
        <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
          {!reqs ? (
            <SkeletonRows rows={6} />
          ) : reqs.length === 0 ? (
            <EmptyState
              title="还没有需求"
              hint={canCreate ? "点击右上角「新建需求」开始，或指派给 Agent 让它自动推进。" : "还没有需求。"}
              action={canCreate ? (
                <Button size="sm" onClick={() => setCreating(true)}>+ 新建需求</Button>
              ) : undefined}
            />
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-ink-muted">
                  <th className="px-4 py-3 font-medium">编号</th>
                  <th className="px-4 py-3 font-medium">标题</th>
                  <th className="px-4 py-3 font-medium">状态</th>
                  <th className="px-4 py-3 font-medium">优先级</th>
                  <th className="px-4 py-3 font-medium">负责人</th>
                  <th className="px-4 py-3 font-medium text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {reqs.map((r) => (
                  <tr
                    key={r.id}
                    onClick={() => setOpenId(r.id)}
                    className="cursor-pointer border-b border-border last:border-0 hover:bg-black/[0.015]"
                  >
                    <td className="px-4 py-3 text-ink-muted">REQ-{r.id}</td>
                    <td className="px-4 py-3 font-medium text-ink">{r.title}</td>
                    <td className="px-4 py-3">
                      <Badge style={statusStyle(r.status)} />
                    </td>
                    <td className="px-4 py-3">
                      <Badge style={PRIORITY_STYLES[r.priority]} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <AssigneeAvatar assignee={r.assignee} size={24} />
                        <span className="text-ink-muted">
                          {r.assignee ? r.assignee.name : "未指派"}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          setAssignTarget(r);
                          setAssignee({
                            assignee_type: r.assignee_type,
                            assignee_id: r.assignee_id,
                          });
                        }}
                      >
                        指派
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </main>

      {/* 工单详情抽屉 */}
      <TicketDrawer
        entity="requirements"
        id={openId}
        onClose={() => setOpenId(null)}
        onChanged={() => mutate()}
      />

      {/* 新建需求 */}
      <Modal open={creating} onClose={() => setCreating(false)} title="新建需求">
        <RequirementForm
          onCancel={() => setCreating(false)}
          onCreated={() => {
            setCreating(false);
            mutate();
          }}
        />
      </Modal>

      {/* 指派 */}
      <Modal
        open={!!assignTarget}
        onClose={() => setAssignTarget(null)}
        title={`指派需求 · REQ-${assignTarget?.id ?? ""}`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setAssignTarget(null)}>
              取消
            </Button>
            <Button onClick={doAssign}>确认指派</Button>
          </>
        }
      >
        <p className="mb-4 text-sm text-ink-muted">{assignTarget?.title}</p>
        <AssigneePicker value={assignee} onChange={setAssignee} />
      </Modal>
    </>
  );
}
