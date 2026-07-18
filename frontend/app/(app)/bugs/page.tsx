"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { api, swrFetcher, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useAuth } from "@/lib/auth";
import type { Bug } from "@/lib/types";
import { statusStyle, SEVERITY_STYLES } from "@/lib/constants";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import Modal from "@/components/ui/Modal";
import { AssigneeAvatar } from "@/components/ui/Avatar";
import BugForm from "@/components/bugs/BugForm";
import AssigneePicker, { AssigneeValue } from "@/components/AssigneePicker";

export default function BugsPage() {
  const toast = useToast();
  const { user } = useAuth();
  // 后端 POST /bugs 限 admin|pm（§2.4），member 隐藏新建入口，避免提交后才 403。
  const canCreate = user?.role === "admin" || user?.role === "pm";
  const { data: bugs, mutate } = useSWR<Bug[]>("/bugs", swrFetcher);
  const [creating, setCreating] = useState(false);
  const [assignTarget, setAssignTarget] = useState<Bug | null>(null);
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
      await api.patch(`/bugs/${assignTarget.id}/assign`, assignee);
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
        title="BUG"
        subtitle="创建、指派与跟踪缺陷单"
        action={
          <div className="flex items-center gap-2">
            <Link href="/bugs/board">
              <Button variant="ghost" size="sm">
                看板视图
              </Button>
            </Link>
            {canCreate && (
              <Button size="sm" onClick={() => setCreating(true)}>
                + 新建 BUG
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
                <th className="px-4 py-3 font-medium">严重度</th>
                <th className="px-4 py-3 font-medium">负责人</th>
                <th className="px-4 py-3 font-medium">源需求</th>
                <th className="px-4 py-3 font-medium text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {bugs?.map((b) => (
                <tr key={b.id} className="border-b border-border last:border-0 hover:bg-black/[0.015]">
                  <td className="px-4 py-3 text-ink-muted">BUG-{b.id}</td>
                  <td className="px-4 py-3 font-medium text-ink">{b.title}</td>
                  <td className="px-4 py-3">
                    <Badge style={statusStyle(b.status)} />
                  </td>
                  <td className="px-4 py-3">
                    <Badge style={SEVERITY_STYLES[b.severity]} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <AssigneeAvatar assignee={b.assignee} size={24} />
                      <span className="text-ink-muted">
                        {b.assignee ? b.assignee.name : "未指派"}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-ink-muted">
                    {b.related_requirement_id ? `REQ-${b.related_requirement_id}` : "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setAssignTarget(b);
                        setAssignee({
                          assignee_type: b.assignee_type,
                          assignee_id: b.assignee_id,
                        });
                      }}
                    >
                      指派
                    </Button>
                  </td>
                </tr>
              ))}
              {bugs && bugs.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-ink-muted">
                    {canCreate
                      ? "还没有 BUG，点击右上角「新建 BUG」开始。"
                      : "还没有 BUG。"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </main>

      <Modal open={creating} onClose={() => setCreating(false)} title="新建 BUG">
        <BugForm
          onCancel={() => setCreating(false)}
          onCreated={() => {
            setCreating(false);
            mutate();
          }}
        />
      </Modal>

      <Modal
        open={!!assignTarget}
        onClose={() => setAssignTarget(null)}
        title={`指派 BUG · BUG-${assignTarget?.id ?? ""}`}
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
