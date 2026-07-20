"use client";

// 列表页多选状态机（bulk-operations §3.3）。
//
// 【为什么选择是「页内作用域」】跨页累积选择听起来更强，实则每一处都在说谎：翻页后
// 用户看不到已选中的行，动作栏上的数字与屏幕上的内容对不上；筛选一变，选中集里还
// 躺着不再匹配条件的单。Gmail / GitHub 的做法都是页内选择 + 显式「全选本页」，
// 本 hook 采用同一取舍：`resetKey` 一变（筛选 / 项目作用域 / 翻页）立即清空选择。
//
// 由此还换来一个实打实的好处：选中项的**完整行对象**永远在手，动作栏可以据此展示
// 「当前状态分布」这类需要行数据的信息，而不必再发一次请求。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export interface BulkSelection<T> {
  /** 已选中的 id，按当前列表顺序排列（提交顺序 = 用户看到的行序）。 */
  selectedIds: number[];
  /** 已选中的完整行对象，同上顺序。 */
  selectedRows: T[];
  count: number;
  isSelected: (id: number) => boolean;
  /** 单行切换；`extend` 为真（Shift 点击）时把上一次锚点到本行之间整段选中。 */
  toggle: (id: number, extend?: boolean) => void;
  /** 全选 / 取消全选当前页。 */
  toggleAll: () => void;
  /** 当前页是否已全部选中（空列表恒 false）。 */
  allSelected: boolean;
  /** 部分选中——供表头复选框显示 indeterminate。 */
  someSelected: boolean;
  clear: () => void;
  /** 覆盖选择集（批量动作后「只保留失败项」用）。 */
  replace: (ids: number[]) => void;
}

export function useBulkSelection<T extends { id: number }>(
  rows: T[] | undefined,
  resetKey: string
): BulkSelection<T> {
  const [selected, setSelected] = useState<Set<number>>(() => new Set());
  const anchorRef = useRef<number | null>(null);

  // 筛选 / 作用域 / 页码变化 → 清空。本就为空时返回原引用，免得挂载时白白多渲染一次。
  useEffect(() => {
    setSelected((prev) => (prev.size === 0 ? prev : new Set()));
    anchorRef.current = null;
  }, [resetKey]);

  // 行集合变化后剔除已消失的 id（批量删除后重新验证时必然发生）。
  // rows 为 undefined 表示加载中，此时**不能**剪枝——那会在骨架屏一闪之间清空选择。
  useEffect(() => {
    if (!rows) return;
    setSelected((prev) => {
      if (prev.size === 0) return prev;
      const alive = new Set(rows.map((r) => r.id));
      const next = new Set([...prev].filter((id) => alive.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [rows]);

  const toggle = useCallback(
    (id: number, extend = false) => {
      setSelected((prev) => {
        const next = new Set(prev);
        const list = rows ?? [];
        const anchor = anchorRef.current;
        const from = anchor === null ? -1 : list.findIndex((r) => r.id === anchor);
        const to = list.findIndex((r) => r.id === id);
        if (extend && from >= 0 && to >= 0) {
          // Shift 范围选择恒为「选中」而非「切换」：范围内混杂选中/未选中时，
          // 逐个取反的结果没人能预测，而「补齐整段」是所有列表 UI 的共同约定。
          const [lo, hi] = from <= to ? [from, to] : [to, from];
          for (let i = lo; i <= hi; i += 1) next.add(list[i].id);
          return next;
        }
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
      // 锚点只在非范围点击时更新，连续 Shift 点击才能围绕同一锚点扩展。
      if (!extend) anchorRef.current = id;
    },
    [rows]
  );

  const allSelected = !!rows && rows.length > 0 && rows.every((r) => selected.has(r.id));

  const toggleAll = useCallback(() => {
    const list = rows ?? [];
    setSelected(allSelected ? new Set() : new Set(list.map((r) => r.id)));
    anchorRef.current = null;
  }, [rows, allSelected]);

  const clear = useCallback(() => {
    setSelected(new Set());
    anchorRef.current = null;
  }, []);

  const replace = useCallback((ids: number[]) => {
    setSelected(new Set(ids));
    anchorRef.current = null;
  }, []);

  const selectedRows = useMemo(
    () => (rows ?? []).filter((r) => selected.has(r.id)),
    [rows, selected]
  );

  return {
    selectedIds: selectedRows.map((r) => r.id),
    selectedRows,
    count: selectedRows.length,
    isSelected: (id: number) => selected.has(id),
    toggle,
    toggleAll,
    allSelected,
    someSelected: selectedRows.length > 0 && !allSelected,
    clear,
    replace,
  };
}
