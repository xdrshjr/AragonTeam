"use client";

// 一键复制（account-security-and-governance §6.2）。
//
// 从 `components/settings/RegistrationCard.tsx` 的内联实现提取而来：本轮是全仓第三处
// 需要「复制一段凭据」的地方（邀请码 ×2、一次性口令 ×1），正是提取的时机。
//
// **复制失败必须说出来**：`navigator.clipboard` 在非安全上下文（http 局域网部署）与
// 用户拒绝授权时会 reject。假装成功的代价是管理员关掉对话框才发现剪贴板里什么都没有，
// 而一次性口令**关掉就再也读不到了**。

import { useToast } from "@/lib/toast";
import Button from "@/components/ui/Button";

interface Props {
  value: string;
  /** 用于成功提示的名词，如「邀请码」「一次性密码」。 */
  label: string;
  variant?: "ghost" | "primary" | "danger";
  size?: "sm" | "md";
  children?: React.ReactNode;
}

export default function CopyButton({
  value,
  label,
  variant = "ghost",
  size = "sm",
  children,
}: Props) {
  const toast = useToast();

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(value);
      toast.success(`${label}已复制`);
    } catch {
      toast.error("浏览器拒绝了复制，请手动选中");
    }
  }

  return (
    <Button variant={variant} size={size} onClick={onCopy}>
      {children ?? "复制"}
    </Button>
  );
}
