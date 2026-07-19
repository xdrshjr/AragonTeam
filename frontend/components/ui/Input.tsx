import { InputHTMLAttributes, forwardRef, useId } from "react";

interface Props extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
}

const Input = forwardRef<HTMLInputElement, Props>(function Input(
  { label, className = "", id, ...rest },
  ref
) {
  // 【H7】多数调用方既不传 id 也不传 name → <label> 与控件未关联（点标签不聚焦、
  // 读屏播报「未命名输入框」）。useId() 是 React 18 内置且 SSR 安全的稳定兜底。
  const fallbackId = useId();
  const inputId = id || rest.name || fallbackId;
  return (
    <div className="flex flex-col gap-1.5">
      {label && (
        <label htmlFor={inputId} className="text-sm font-medium text-ink">
          {label}
        </label>
      )}
      <input
        ref={ref}
        id={inputId}
        className={[
          "h-10 rounded-lg border border-border bg-surface px-3 text-sm text-ink",
          "placeholder:text-ink-muted/70",
          "focus:outline-none focus:border-clay focus:ring-2 focus:ring-clay/20",
          className,
        ].join(" ")}
        {...rest}
      />
    </div>
  );
});

export default Input;
