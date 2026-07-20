"use client";

// 全局层栈（ticket-document-management §6.4 / 评审 R9）。
//
// 【为什么必须有这个模块】本轮所有文档模态都开在**工单抽屉之内**。而现网抽屉与
// `components/ui/Modal.tsx` 各自把 Esc 处理器挂在 `window` 上、各自对
// `document.body.style.overflow` 做 set/restore。两层叠起来会得到两个必现缺陷：
//
//   ① 按 Esc → 模态与抽屉**一起消失**，用户丢失整个工单上下文，
//      编辑器的「未保存」二次确认也被绕过；
//   ② 模态卸载时把 overflow 恢复成它进入时读到的值（很可能是 ""）→
//      **抽屉还开着，背景却已经能滚动**。
//
// 两条契约，全站唯一实现：
//   - **Esc 只由栈顶层消费**：非栈顶层的监听直接 return；
//   - **滚动锁按引用计数**：栈从空变非空时加锁，从非空变空时解锁，
//     中间的 push/pop 一律不动 `body.style`。
//
// 本轮**有意不做**全站焦点陷阱（Tab 循环）——那需要同时改造抽屉、5 个既有模态与
// ConfirmDialog，是一次独立的 a11y 改造，混进本轮会让文档功能的回归面无法收敛。

import { useEffect, useRef } from "react";

const stack: string[] = [];
/** 栈从空变非空的那一刻，`body.style.overflow` 的原值。只有它有资格被恢复。 */
let lockedFrom: string | null = null;
let counter = 0;

export function nextLayerId(prefix = "layer"): string {
  counter += 1;
  return `${prefix}-${counter}`;
}

export function pushLayer(id: string): void {
  if (stack.includes(id)) return;
  stack.push(id);
  if (stack.length === 1 && typeof document !== "undefined") {
    lockedFrom = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
}

export function popLayer(id: string): void {
  const index = stack.lastIndexOf(id);
  if (index === -1) return;
  stack.splice(index, 1);
  if (stack.length === 0 && typeof document !== "undefined") {
    document.body.style.overflow = lockedFrom ?? "";
    lockedFrom = null;
  }
}

/** 该层是否位于栈顶（唯一有资格消费 Esc / 遮罩点击的层）。 */
export function isTopLayer(id: string): boolean {
  return stack.length > 0 && stack[stack.length - 1] === id;
}

/** 仅供测试与排查：当前层数。 */
export function layerDepth(): number {
  return stack.length;
}

/**
 * 把一个覆盖层接入层栈。
 *
 * @param active 该层当前是否可见。为假时不入栈，也不参与滚动锁。
 * @returns `isTop()` —— 在键盘 / 点击处理器里调用它来决定「这一下是不是给我的」。
 *   刻意返回**函数**而不是布尔值：事件处理器往往被 `useEffect` 闭包捕获，
 *   捕获一个布尔快照会在上层打开后仍读到过期的 true。
 */
export function useOverlayLayer(active: boolean): { isTop: () => boolean } {
  const idRef = useRef<string | null>(null);
  if (idRef.current === null) idRef.current = nextLayerId();
  const id = idRef.current;

  useEffect(() => {
    if (!active) return;
    pushLayer(id);
    return () => popLayer(id);
  }, [active, id]);

  return { isTop: () => isTopLayer(id) };
}
