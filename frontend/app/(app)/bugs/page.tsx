"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import useSWR, { useSWRConfig } from "swr";
import { api, listFetcher, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useAuth } from "@/lib/auth";
import { EMPTY_HIERARCHY, isHierarchyParam, toHierarchyQuery } from "@/lib/hierarchy";
import type { HierarchyFilterValue } from "@/lib/hierarchy";
import { invalidateHierarchyViews } from "@/lib/swr-keys";
import { useProjectScope } from "@/lib/project-scope";
import { useHierarchyOptions } from "@/hooks/useHierarchyOptions";
import type { Bug } from "@/lib/types";
import { statusStyle, SEVERITY_STYLES, BUG_COLUMNS } from "@/lib/constants";
import Header from "@/components/layout/Header";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import Modal from "@/components/ui/Modal";
import { AssigneeAvatar } from "@/components/ui/Avatar";
import { SkeletonRows } from "@/components/ui/Skeleton";
import EmptyState from "@/components/ui/EmptyState";
import ErrorState from "@/components/ui/ErrorState";
import Pagination from "@/components/ui/Pagination";
import BugForm from "@/components/bugs/BugForm";
import AssigneePicker, { AssigneeValue } from "@/components/AssigneePicker";
import TicketDrawer from "@/components/TicketDrawer";
import FilterBar from "@/components/FilterBar";
import PlanBadge from "@/components/planning/PlanBadge";
import Checkbox from "@/components/ui/Checkbox";
import BulkToolbar from "@/components/bulk/BulkToolbar";
import { useBulkSelection } from "@/hooks/useBulkSelection";

// 与后端 pagination.DEFAULT_LIMIT 对齐，便于对照排查。
const PAGE_SIZE = 50;

export default function BugsPage() {
  const toast = useToast();
  const { user } = useAuth();
  const { mutate: globalMutate } = useSWRConfig();
  const { scopeParam, scopeLabel, setScope } = useProjectScope();
  // 后端 POST /bugs 限 admin|pm（§2.4），member 隐藏新建入口，避免提交后才 403。
  const canCreate = user?.role === "admin" || user?.role === "pm";
  // 【§2.9-C1】/assign 后端限 pm/admin；判据同 canCreate，member 不应看到点了必 403 的「指派」按钮。
  const canAssign = canCreate;

  // 【Phase-3 §2.6】过滤条状态（BUG 侧的等级为 severity）。
  const [keyword, setKeyword] = useState("");
  const [debounced, setDebounced] = useState("");
  const [status, setStatus] = useState("");
  const [severity, setSeverity] = useState("");
  const [assignee, setFilterAssignee] = useState<AssigneeValue>({
    assignee_type: null,
    assignee_id: null,
  });
  // 【version-plan-console §3.3】「版本 → 计划」级联筛选（与需求页同构）。
  const [hierarchy, setHierarchy] = useState<HierarchyFilterValue>(EMPTY_HIERARCHY);
  const hierarchyOptions = useHierarchyOptions();

  // Header 全局搜索：跨页导航时携带 ?q=（进入页面 mount 读取）；已在本页时靠事件即时刷新（B6，与需求页对称）。
  useEffect(() => {
    const search = new URLSearchParams(window.location.search);
    const q = search.get("q") || "";
    if (q) {
      setKeyword(q);
      setDebounced(q);
    }
    // 【lifecycle-and-governance §2.8】承接看板被截断列的「查看全部」出口（?status=<key>）。
    const s = search.get("status") || "";
    if (s && BUG_COLUMNS.some((c) => c.key === s)) setStatus(s);
    // 【version-plan-console §3.3】承接 /versions 页计划行的「BUG N」深链（同需求页）。
    const v = search.get("version_id") || "";
    const p = search.get("plan_id") || "";
    if (isHierarchyParam(v) || isHierarchyParam(p)) {
      setHierarchy({
        version: isHierarchyParam(v) ? v : "",
        plan: isHierarchyParam(p) ? p : "",
      });
    }
    // 深链同时带 project_id，否则「全部项目」视图里点过来的计划会被当前作用域 AND 成空表。
    const proj = search.get("project_id") || "";
    if (/^[1-9]\d*$/.test(proj)) setScope(Number(proj));
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

  const [offset, setOffset] = useState(0);

  const params = new URLSearchParams();
  if (debounced) params.set("q", debounced);
  if (status) params.set("status", status);
  if (severity) params.set("severity", severity);
  if (assignee.assignee_type && assignee.assignee_id != null) {
    params.set("assignee_type", assignee.assignee_type);
    params.set("assignee_id", String(assignee.assignee_id));
  }
  if (scopeParam) params.set("project_id", scopeParam);
  params.set("limit", String(PAGE_SIZE));
  params.set("offset", String(offset));
  const hierarchyQuery = toHierarchyQuery(hierarchy);
  const listKey = `/bugs?${params.toString()}${hierarchyQuery ? `&${hierarchyQuery}` : ""}`;
  const { data, error, mutate } = useSWR(listKey, listFetcher<Bug>, {
    keepPreviousData: true, // 翻页保留上一页数据，消除骨架闪烁
  });
  const bugs = data?.items;

  // 任一筛选条件（含项目作用域）变化 → 回第一页，避免「筛出 3 条却停在 offset=50」的空表误读。
  const filterSignature =
    `${debounced}|${status}|${severity}|${assignee.assignee_type}|${assignee.assignee_id}|${scopeParam}`
    + `|${hierarchy.version}|${hierarchy.plan}`;
  useEffect(() => {
    setOffset(0);
  }, [filterSignature]);

  // 越界自愈：他人删单致 total 缩小、或刷新到深页。
  useEffect(() => {
    if (data && offset > 0 && offset >= data.total) setOffset(0);
  }, [data, offset]);

  // 【bulk-operations §3.3】页内作用域的批量选择（与需求页同构）。
  const selection = useBulkSelection(bugs, `${filterSignature}|${offset}`);

  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const [assignTarget, setAssignTarget] = useState<Bug | null>(null);
  const [assignee2, setAssignee] = useState<AssigneeValue>({
    assignee_type: null,
    assignee_id: null,
  });
  const [assigning, setAssigning] = useState(false);

  async function doAssign() {
    if (!assignTarget || !assignee2.assignee_type) {
      toast.error("请选择指派对象");
      return;
    }
    if (assigning) return; // 【§2.10-D2】防重复提交（慢网双击）。
    setAssigning(true);
    try {
      await api.patch(`/bugs/${assignTarget.id}/assign`, assignee2);
      toast.success("指派成功");
      setAssignTarget(null);
      setAssignee({ assignee_type: null, assignee_id: null });
      mutate();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "指派失败");
    } finally {
      setAssigning(false);
    }
  }

  return (
    <>
      <Header
        title="BUG"
        subtitle={
          data
            ? `共 ${data.total} 条 · 点击行查看详情与协作${scopeLabel ? ` · ${scopeLabel}` : ""}`
            : "创建、指派与跟踪缺陷单"
        }
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
      {/* 【bulk-operations §3.4】选中时给正文留出动作栏的让位空间（与需求页同构）。 */}
      <main className={`flex-1 overflow-y-auto p-6${selection.count > 0 ? " pb-28" : ""}`}>
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
          hierarchy={{
            value: hierarchy,
            onChange: setHierarchy,
            versions: hierarchyOptions.versions,
            plans: hierarchyOptions.plans,
            loading: hierarchyOptions.isLoading,
            versionsTruncated: hierarchyOptions.versionsTruncated,
            plansTruncated: hierarchyOptions.plansTruncated,
          }}
        />

        <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
          {error && !bugs ? (
            <ErrorState message="无法加载 BUG 列表" onRetry={() => mutate()} />
          ) : !bugs ? (
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
            <>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-ink-muted">
                  <th scope="col" className="w-10 px-4 py-3">
                    <Checkbox
                      aria-label={selection.allSelected ? "取消全选本页" : "全选本页"}
                      checked={selection.allSelected}
                      indeterminate={selection.someSelected}
                      onToggleSelected={selection.toggleAll}
                    />
                  </th>
                  <th className="px-4 py-3 font-medium">编号</th>
                  <th className="px-4 py-3 font-medium">标题</th>
                  <th className="px-4 py-3 font-medium">状态</th>
                  <th className="px-4 py-3 font-medium">严重度</th>
                  <th className="px-4 py-3 font-medium">负责人</th>
                  {/* 【version-plan-console §7.3】计划列（与需求页同构）。 */}
                  <th className="px-4 py-3 font-medium">计划</th>
                  {/* 【ticket-document-management §3.5】文档数列：只读指示，与看板的
                      回形针徽章同源（后端 additive `document_count`）。 */}
                  <th className="px-4 py-3 font-medium">文档</th>
                  <th className="px-4 py-3 font-medium">源需求</th>
                  {canAssign && <th className="px-4 py-3 font-medium text-right">操作</th>}
                </tr>
              </thead>
              <tbody>
                {bugs.map((b) => (
                  <tr
                    key={b.id}
                    onClick={() => setOpenId(b.id)}
                    data-selected={selection.isSelected(b.id)}
                    className={[
                      "cursor-pointer border-b border-border last:border-0",
                      selection.isSelected(b.id)
                        ? "bg-clay-soft/25 hover:bg-clay-soft/35"
                        : "hover:bg-black/[0.015]",
                    ].join(" ")}
                  >
                    <td className="px-4 py-3">
                      <Checkbox
                        aria-label={`选择 BUG-${b.id}`}
                        checked={selection.isSelected(b.id)}
                        onToggleSelected={(extend) => selection.toggle(b.id, extend)}
                      />
                    </td>
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
                    <td className="px-4 py-3">
                      <PlanBadge plan={b.plan} linkVersion />
                    </td>
                    <td className="px-4 py-3 text-ink-muted">
                      {(b.document_count ?? 0) > 0 ? (
                        <span
                          title={`${(b.document_count)} 份文档`}
                          className="inline-flex items-center gap-0.5"
                        >
                          <span aria-hidden="true">📎</span>
                          {b.document_count}
                        </span>
                      ) : (
                        <span className="text-ink-muted/50">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-ink-muted">
                      {b.related_requirement_id ? `REQ-${b.related_requirement_id}` : "—"}
                    </td>
                    {canAssign && (
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
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
            <Pagination
              offset={offset}
              limit={PAGE_SIZE}
              total={data?.total ?? 0}
              onOffset={setOffset}
              disabled={!data}
            />
            </>
          )}
        </div>
      </main>

      {/* 【bulk-operations §3.4】选中态浮动动作栏 + 全部批量弹窗 */}
      <BulkToolbar
        entity="bugs"
        selection={selection}
        pageTotal={bugs?.length ?? 0}
        canManage={canAssign}
        onDone={() => mutate()}
      />

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
            // 【version-plan-console §3.2 落点⑥】新单可能带 plan_id，计划行的「BUG N」
            // 与版本聚合进度必须跟着变；页内 mutate 只刷当前列表。
            void invalidateHierarchyViews(globalMutate);
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
            <Button onClick={doAssign} disabled={assigning}>
              {assigning ? "指派中…" : "确认指派"}
            </Button>
          </>
        }
      >
        <p className="mb-4 text-sm text-ink-muted">{assignTarget?.title}</p>
        <AssigneePicker value={assignee2} onChange={setAssignee} />
      </Modal>
    </>
  );
}
