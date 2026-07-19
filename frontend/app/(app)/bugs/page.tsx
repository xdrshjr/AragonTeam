"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import useSWR from "swr";
import { api, listFetcher, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useAuth } from "@/lib/auth";
import type { Bug } from "@/lib/types";
import { statusStyle, SEVERITY_STYLES, BUG_COLUMNS } from "@/lib/constants";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import Modal from "@/components/ui/Modal";
import { AssigneeAvatar } from "@/components/ui/Avatar";
import { SkeletonRows } from "@/components/ui/Skeleton";
import EmptyState from "@/components/ui/EmptyState";
import BugForm from "@/components/bugs/BugForm";
import AssigneePicker, { AssigneeValue } from "@/components/AssigneePicker";
import TicketDrawer from "@/components/TicketDrawer";
import FilterBar from "@/components/FilterBar";

export default function BugsPage() {
  const toast = useToast();
  const { user } = useAuth();
  // 后端 POST /bugs 限 admin|pm（§2.4），member 隐藏新建入口，避免提交后才 403。
  const canCreate = user?.role === "admin" || user?.role === "pm";

  // 【Phase-3 §2.6】过滤条状态（BUG 侧的等级为 severity）。
  const [keyword, setKeyword] = useState("");
  const [debounced, setDebounced] = useState("");
  const [status, setStatus] = useState("");
  const [severity, setSeverity] = useState("");
  const [assignee, setFilterAssignee] = useState<AssigneeValue>({
    assignee_type: null,
    assignee_id: null,
  });

  // Header 全局搜索：跨页导航时携带 ?q=（进入页面 mount 读取）；已在本页时靠事件即时刷新（B6，与需求页对称）。
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("q") || "";
    if (q) {
      setKeyword(q);
      setDebounced(q);
    }
    function onSearch(e: Event) {
      const term = (e as CustomEvent<string>).detail?.trim();
      if (!term) return;
      setKeyword(term);
      setDebounced(term);
    }
    window.addEventListener("aragon:search", onSearch);
    return () => window.removeEventListener("aragon:search", onSearch);
  }, []);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(keyword.trim()), 300);
    return () => clearTimeout(t);
  }, [keyword]);

  const params = new URLSearchParams();
  if (debounced) params.set("q", debounced);
  if (status) params.set("status", status);
  if (severity) params.set("severity", severity);
  if (assignee.assignee_type && assignee.assignee_id != null) {
    params.set("assignee_type", assignee.assignee_type);
    params.set("assignee_id", String(assignee.assignee_id));
  }
  const listKey = `/bugs${params.toString() ? `?${params.toString()}` : ""}`;
  const { data, mutate } = useSWR(listKey, listFetcher<Bug>);
  const bugs = data?.items;

  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const [assignTarget, setAssignTarget] = useState<Bug | null>(null);
  const [assignee2, setAssignee] = useState<AssigneeValue>({
    assignee_type: null,
    assignee_id: null,
  });

  async function doAssign() {
    if (!assignTarget || !assignee2.assignee_type) {
      toast.error("请选择指派对象");
      return;
    }
    try {
      await api.patch(`/bugs/${assignTarget.id}/assign`, assignee2);
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
        subtitle={data ? `共 ${data.total} 条 · 点击行查看详情与协作` : "创建、指派与跟踪缺陷单"}
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
        <FilterBar
          keyword={keyword}
          onKeyword={setKeyword}
          status={status}
          onStatus={setStatus}
          statusOptions={BUG_COLUMNS.map((c) => ({ value: c.key, label: c.title }))}
          level={severity}
          onLevel={setSeverity}
          levelLabel="严重度"
          levelOptions={(Object.keys(SEVERITY_STYLES) as (keyof typeof SEVERITY_STYLES)[]).map(
            (k) => ({ value: k, label: SEVERITY_STYLES[k].label })
          )}
          assignee={assignee}
          onAssignee={setFilterAssignee}
        />

        <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
          {!bugs ? (
            <SkeletonRows rows={6} />
          ) : bugs.length === 0 ? (
            <EmptyState
              title="没有符合条件的 BUG"
              hint={canCreate ? "调整筛选，或点击右上角「新建 BUG」，或从需求「转 BUG」流转过来。" : "调整筛选条件试试。"}
              action={canCreate ? (
                <Button size="sm" onClick={() => setCreating(true)}>+ 新建 BUG</Button>
              ) : undefined}
            />
          ) : (
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
                {bugs.map((b) => (
                  <tr
                    key={b.id}
                    onClick={() => setOpenId(b.id)}
                    className="cursor-pointer border-b border-border last:border-0 hover:bg-black/[0.015]"
                  >
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
                        onClick={(e) => {
                          e.stopPropagation();
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
              </tbody>
            </table>
          )}
        </div>
      </main>

      <TicketDrawer
        entity="bugs"
        id={openId}
        onClose={() => setOpenId(null)}
        onChanged={() => mutate()}
      />

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
        <AssigneePicker value={assignee2} onChange={setAssignee} />
      </Modal>
    </>
  );
}
