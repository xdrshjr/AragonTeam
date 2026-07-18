import type { Config } from "tailwindcss";

// §2.5 Anthropic 设计系统令牌（仅浅色，暖色系）。
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: "#F7F4EE",           // ivory 页面背景
        surface: "#FFFFFF",       // 卡片/面板
        border: "#E7E1D6",        // 分隔线/描边
        ink: {
          DEFAULT: "#1A1A17",     // 主文本
          muted: "#6E6A62",       // 次文本
        },
        clay: {
          DEFAULT: "#C15F3C",     // 主强调/按钮
          soft: "#E8C9BC",        // 强调浅底
          dark: "#A44E30",        // hover/active
        },
        accent: {
          blue: "#3B6EA5",        // 信息态
        },
      },
      fontFamily: {
        serif: ['Georgia', 'Tiempos', 'serif'],
        sans: ['system-ui', 'Inter', 'sans-serif'],
      },
      borderRadius: {
        xl: "12px",
        lg: "8px",
      },
      boxShadow: {
        card: "0 1px 2px rgba(0,0,0,0.04)",
        panel: "0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)",
        lift: "0 8px 24px rgba(26,26,23,0.10)",
      },
    },
  },
  plugins: [],
};

export default config;
