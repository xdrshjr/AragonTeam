import { InputHTMLAttributes, forwardRef } from "react";

interface Props extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
}

const Input = forwardRef<HTMLInputElement, Props>(function Input(
  { label, className = "", id, ...rest },
  ref
) {
  const inputId = id || rest.name;
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
