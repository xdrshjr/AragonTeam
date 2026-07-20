"use client";

import { InputHTMLAttributes, MouseEvent, useEffect, useRef } from "react";

interface Props
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "onChange" | "onToggle"> {
  checked: boolean;
  /** 半选态（表头「部分选中」）。DOM 里没有对应属性，只能由 JS 赋值。 */
  indeterminate?: boolean;
  /** 鼠标点击带 shiftKey，用于范围选择；键盘空格触发的合成 click 恒为 false。 */
  onToggleSelected: (extend: boolean) => void;
  /** 屏幕阅读器读到的名字，必填——一列没有标签的复选框对读屏用户等于噪音。 */
  "aria-label": string;
}

/**
 * 原生复选框 + 项目色系（bulk-operations §3.3）。
 *
 * 刻意不用 div 模拟：原生 `<input type="checkbox">` 自带键盘可达、读屏语义与
 * `indeterminate` 视觉，自绘一个只会把这三样都做丢。这里只做两件事——用 accent-color
 * 换成 clay，以及把「Shift 范围选择」需要的 shiftKey 从 click 事件里递出去。
 *
 * 事件选 click 而非 change：change 事件不带 shiftKey。键盘空格也会派发合成 click，
 * 故两种输入方式都被这一个处理器覆盖。
 */
export default function Checkbox({
  checked,
  indeterminate = false,
  onToggleSelected,
  className = "",
  ...rest
}: Props) {
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate && !checked;
  }, [indeterminate, checked]);

  function handleClick(e: MouseEvent<HTMLInputElement>) {
    // 行级复选框位于「点击整行打开抽屉」的 <tr> 内，必须掐断冒泡。
    e.stopPropagation();
    onToggleSelected(e.shiftKey);
  }

  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      onChange={() => undefined} // 受控输入必须有 onChange；真正的处理在 onClick
      onClick={handleClick}
      className={[
        "h-4 w-4 cursor-pointer rounded border-border accent-clay",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-clay/40",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      ].join(" ")}
      {...rest}
    />
  );
}
