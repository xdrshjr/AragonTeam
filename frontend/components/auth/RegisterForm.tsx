"use client";

// 自助注册表单（self-service-registration §6.1）。
//
// 交互总则：**失焦即校验，键入即消错**——避免「打字过程中被红字追着骂」，也避免
// 「提交后才知道错在哪」。服务端的字段级错误（邀请码不对 / 口令不达标 / 重名）一律
// 渲染到**对应字段下方**并把焦点还给它，而不是弹一个无处着落的 toast。

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import type { SignupPayload } from "@/lib/types";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import PasswordStrength, { isPasswordAcceptable } from "@/components/auth/PasswordStrength";
import { useRegistrationMeta } from "@/hooks/useRegistrationMeta";
import type { PasswordPolicy } from "@/lib/types";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Field = "username" | "display_name" | "email" | "password" | "confirm" | "invite_code";
type Errors = Partial<Record<Field, string>>;
type Form = Record<Field, string>;

const EMPTY: Form = {
  username: "", display_name: "", email: "", password: "", confirm: "", invite_code: "",
};

/** 单字段校验；返回错误文案或 undefined。规则与后端逐条对应（§6.1 第 2 条）。
 *
 * 【account-security-and-governance §2.1 A-3 ②】`policy` **必须**一路传到
 * `isPasswordAcceptable`：它是带默认值的可选参数，漏传不会有任何编译错误，
 * 但后果正是本产品反复承诺要避免的「界面说没问题、提交却 400」。 */
function validateField(field: Field, form: Form, policy: PasswordPolicy): string | undefined {
  const value = form[field].trim();
  if (field === "username") {
    if (!value) return "请填写用户名";
    if (value.length > 64) return "用户名最多 64 个字符";
  }
  if (field === "display_name" && value.length > 128) return "显示名称最多 128 个字符";
  if (field === "email" && value && !EMAIL_RE.test(value)) return "邮箱格式不正确";
  if (field === "password" && !isPasswordAcceptable(form.password, form.username, policy)) {
    return "密码不满足下方的强度要求";
  }
  // 确认密码只在两次都非空且不一致时报错，不阻塞输入（§6.1 第 3 条）。
  if (field === "confirm" && form.confirm && form.password !== form.confirm) {
    return "两次输入的密码不一致";
  }
  if (field === "invite_code" && !value) return "请填写邀请码";
  return undefined;
}

// 提交前逐个过一遍的字段。**不是「必填字段」**——`display_name` / `email` 都是选填，
// 列在这里只是因为「填了但填错」同样要在提交前拦住（validateField 对空值恒返回 undefined）。
const VALIDATED_FIELDS: Field[] = [
  "username", "display_name", "email", "password", "confirm", "invite_code",
];

function validateAll(form: Form, policy: PasswordPolicy): Errors {
  const errors: Errors = {};
  for (const field of VALIDATED_FIELDS) {
    const message = validateField(field, form, policy);
    if (message) errors[field] = message;
  }
  return errors;
}

/** 把服务端错误翻译成「字段名 + 文案」。无法归到具体字段时返回 null，交给 toast。 */
function serverError(err: unknown): { field: Field; message: string } | null {
  if (!(err instanceof ApiError)) return null;
  if (err.status === 409) return { field: "username", message: "该用户名已被占用，换一个试试" };
  if (err.status === 429) {
    return { field: "invite_code", message: "尝试过于频繁，请 5 分钟后再试" };
  }
  const detail = err.detail as { field?: string } | undefined;
  const field = detail?.field as Field | undefined;
  if (field === "invite_code") return { field, message: "邀请码不正确，请向管理员确认" };
  if (field && field in EMPTY) return { field, message: err.message };
  return null;
}

/** 错误文案容器：`role="alert"` + `aria-live` 让读屏能读到刚出现的校验错误（§6.2）。 */
function FieldError({ message }: { message?: string }) {
  return (
    <div role="alert" aria-live="polite" className="min-h-[1rem] text-xs text-[#B23B1E]">
      {message}
    </div>
  );
}

export default function RegisterForm() {
  const router = useRouter();
  const { signup } = useAuth();
  const toast = useToast();
  const { policy } = useRegistrationMeta();
  const [form, setForm] = useState<Form>(EMPTY);
  const [errors, setErrors] = useState<Errors>({});
  const [submitting, setSubmitting] = useState(false);
  const refs = useRef<Partial<Record<Field, HTMLInputElement | null>>>({});

  function set(field: Field, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
    // 键入即消错：只清掉这一个字段的错误，不动别的。
    setErrors((prev) => (prev[field] ? { ...prev, [field]: undefined } : prev));
  }

  function blur(field: Field) {
    setErrors((prev) => ({ ...prev, [field]: validateField(field, form, policy) }));
  }

  function focusField(field: Field) {
    refs.current[field]?.focus();
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const found = validateAll(form, policy);
    if (Object.keys(found).length > 0) {
      setErrors(found);
      focusField(Object.keys(found)[0] as Field);
      return;
    }
    setSubmitting(true);
    try {
      await signup(buildPayload(form));
      toast.success("注册成功，欢迎加入");
      // 用 replace 不用 push：注册页不该留在返回栈里。
      router.replace("/dashboard");
    } catch (err) {
      handleFailure(err);
    } finally {
      setSubmitting(false);
    }
  }

  function handleFailure(err: unknown) {
    const mapped = serverError(err);
    if (!mapped) {
      toast.error(err instanceof ApiError ? err.message : "注册失败，请稍后重试");
      return;
    }
    setErrors((prev) => ({ ...prev, [mapped.field]: mapped.message }));
    focusField(mapped.field);
  }

  function bind(field: Field) {
    return {
      value: form[field],
      onChange: (e: React.ChangeEvent<HTMLInputElement>) => set(field, e.target.value),
      onBlur: () => blur(field),
      ref: (el: HTMLInputElement | null) => {
        refs.current[field] = el;
      },
    };
  }

  return (
    <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-3" noValidate>
      <div>
        <Input label="用户名" name="username" autoComplete="username" maxLength={64}
               placeholder="登录时使用，字母 / 数字 / 下划线" {...bind("username")} />
        <FieldError message={errors.username} />
      </div>
      <div>
        <Input label="显示名称（选填）" name="display_name" maxLength={128}
               placeholder="留空则同用户名" {...bind("display_name")} />
        <FieldError message={errors.display_name} />
      </div>
      <div>
        <Input label="邮箱（选填）" name="email" type="email" autoComplete="email"
               placeholder="name@example.com" {...bind("email")} />
        <FieldError message={errors.email} />
      </div>
      <div className="flex flex-col gap-2">
        <Input label="密码" name="password" type="password" autoComplete="new-password"
               placeholder="••••••••" {...bind("password")} />
        <PasswordStrength password={form.password} username={form.username} policy={policy} />
        <FieldError message={errors.password} />
      </div>
      <div>
        <Input label="确认密码" name="confirm" type="password" autoComplete="new-password"
               placeholder="再输入一次" {...bind("confirm")} />
        <FieldError message={errors.confirm} />
      </div>
      <div>
        <Input label="邀请码" name="invite_code" autoComplete="off" spellCheck={false}
               maxLength={64} placeholder="请向管理员索取" {...bind("invite_code")} />
        <FieldError message={errors.invite_code} />
      </div>
      <Button type="submit" disabled={submitting} className="mt-1 w-full">
        {submitting ? "注册中…" : "注册并进入"}
      </Button>
    </form>
  );
}

function buildPayload(form: Form): SignupPayload {
  return {
    username: form.username.trim(),
    password: form.password,
    invite_code: form.invite_code.trim(),
    display_name: form.display_name.trim() || undefined,
    email: form.email.trim() || undefined,
  };
}
