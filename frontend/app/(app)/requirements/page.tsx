"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { api, swrFetcher, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useAuth } from "@/lib/auth";
import type { Requirement } from "@/lib/types";
import { statusStyle, PRIORITY_STYLES } from "@/lib/constants";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import Modal from "@/components/ui/Modal";
import { AssigneeAvatar } from "@/components/ui/Avatar";
import RequirementForm from "@/components/requirements/RequirementForm";
import AssigneePicker, { AssigneeValue } from "@/components/AssigneePicker";

export default function RequirementsPage() {
  const toast = useToast();
  const { user } = useAuth();
  // 后端 POST /requirements 限 admin|pm（§2.4），member 隐藏新建入口，避免提交后才 403。
  const canCreate = user?.role === "admin" || user?.role === "pm";
  const { data: reqs, mutate } = useSWR<Requirement[]>("/requirements", swrFetcher);
  const [creating, setCreating] = useState(false);
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
        subtitle="创建、指派与跟踪需求"
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
              {reqs?.map((r) => (
                <tr key={r.id} className="border-b border-border last:border-0 hover:bg-black/[0.015]">
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
                      onClick={() => {
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
              {reqs && reqs.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-ink-muted">
                    {canCreate
                      ? "还没有需求，点击右上角「新建需求」开始。"
                      : "还没有需求。"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </main>

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
