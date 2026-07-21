"use client";

// 口令强度反馈（self-service-registration §6.1 第 2 条 / §6.2）。
//
// 规则与后端 `services/passwords.py::validate_signup_password` **逐条对应**：
// 前端提前拦下的一定是后端也会拒的，反之亦然。任何一侧单方面收紧，都会制造
// 「界面说没问题、提交却 400」或「界面标红、其实能过」的困惑。
//
// a11y：进度条本身 `aria-hidden`——它对读屏用户是纯噪音；真实语义由下方的规则清单
// 文本承载。强度等级**不单靠颜色**表达，必须同时有「弱 / 中 / 强」文字。

export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_LENGTH = 128;
const MIN_CHAR_CLASSES = 2;

/** 命中的字符类别数：小写 / 大写 / 数字 / 其他可打印（与后端 count_char_classes 同口径）。
 *
 * 判据用 Unicode 属性类而不是 `[a-z]` / `[^a-zA-Z0-9\s]`：后端用的是 Python 的
 * `str.islower/isupper/isdigit` 与 `isalnum()`，它们对**全体 Unicode** 生效。用 ASCII
 * 字符类近似会在中文口令上分叉——`密码密码密码密码a` 在后端只命中「小写」一类（汉字
 * 是 alnum，不计入「其他」）而被 400，ASCII 版前端却会把汉字算成「符号」判为两类通过，
 * 于是界面全打勾、提交却报错。这正是本文件开头那条不变量要防的事。
 */
export function countCharClasses(password: string): number {
  let hit = 0;
  if (/\p{Ll}/u.test(password)) hit += 1;
  if (/\p{Lu}/u.test(password)) hit += 1;
  if (/\p{Nd}/u.test(password)) hit += 1;
  if (/[^\p{L}\p{N}\s]/u.test(password)) hit += 1;
  return hit;
}

export interface PasswordRule {
  label: string;
  passed: boolean;
}

/** 三条规则的命中情况。注册表单据此决定能否提交，卡片据此打勾。 */
export function passwordRules(password: string, username: string): PasswordRule[] {
  return [
    {
      label: `至少 ${PASSWORD_MIN_LENGTH} 位（最多 ${PASSWORD_MAX_LENGTH} 位）`,
      passed: password.length >= PASSWORD_MIN_LENGTH && password.length <= PASSWORD_MAX_LENGTH,
    },
    {
      label: "至少包含两类字符（小写 / 大写 / 数字 / 符号）",
      passed: countCharClasses(password) >= MIN_CHAR_CLASSES,
    },
    {
      label: "不与用户名相同",
      passed: password.length > 0 && password.toLowerCase() !== username.trim().toLowerCase(),
    },
  ];
}

export function isPasswordAcceptable(password: string, username: string): boolean {
  return passwordRules(password, username).every((r) => r.passed);
}

const LEVELS = [
  { label: "太弱", className: "bg-[#B23B1E]" },
  { label: "弱", className: "bg-[#B23B1E]" },
  { label: "中", className: "bg-[#C99A2E]" },
  { label: "强", className: "bg-[#6E8B3D]" },
];

/** 0~4 的强度分：三条规则各 1 分，长度 ≥12 再加 1 分。 */
function scoreOf(password: string, username: string): number {
  if (!password) return 0;
  const passed = passwordRules(password, username).filter((r) => r.passed).length;
  return Math.min(4, passed + (password.length >= 12 ? 1 : 0));
}

interface Props {
  password: string;
  username: string;
}

export default function PasswordStrength({ password, username }: Props) {
  const score = scoreOf(password, username);
  const level = LEVELS[Math.max(0, score - 1)];
  const rules = passwordRules(password, username);

  return (
    <div className="flex flex-col gap-2">
      {/* 四段式进度条。motion-reduce 下去掉过渡（§6.2 尊重 prefers-reduced-motion）。 */}
      <div aria-hidden="true" className="flex gap-1.5">
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className={[
              "h-1 flex-1 rounded-full transition-colors motion-reduce:transition-none",
              i < score ? level.className : "bg-border",
            ].join(" ")}
          />
        ))}
      </div>
      <div className="text-xs text-ink-muted">
        强度：<span className="text-ink">{password ? level.label : "—"}</span>
      </div>
      <ul className="flex flex-col gap-1">
        {rules.map((rule) => (
          <li
            key={rule.label}
            className={[
              "flex items-start gap-1.5 text-xs",
              rule.passed ? "text-[#4F6B2A]" : "text-ink-muted",
            ].join(" ")}
          >
            <span aria-hidden="true" className="mt-px w-3 shrink-0 text-center">
              {rule.passed ? "✓" : "·"}
            </span>
            <span>{rule.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
