import { defineConfig, presetUno, presetIcons, transformerDirectives } from 'unocss'

export default defineConfig({
  presets: [
    presetUno({
      dark: 'class',
    }),
    presetIcons({
      scale: 1.2,
    }),
  ],
  transformers: [transformerDirectives()],
  theme: {
    // Responsive breakpoints — aligned with useMobile composable
    // sm:640 md:768 lg:1024 xl:1280 2xl:1536 (UnoCSS defaults, explicit for clarity)
    breakpoints: {
      sm: '640px',
      md: '768px',
      lg: '1024px',
      xl: '1280px',
      '2xl': '1536px',
    },
    colors: {
      // 日系二次元主题色 — CSS custom properties 支持亮色/暗色双模式
      // Hex-backed colors use the `rgb(var(--c-X-rgb) / <alpha-value>)` form so
      // UnoCSS opacity modifiers (bg-c-accent/20) inject real alpha. The plain
      // `var()` form dropped `/NN`, making tinted backgrounds identical to the
      // full-strength color and hiding same-color text/icons (e.g. play ▶).
      'c-bg': 'rgb(var(--c-bg-rgb) / <alpha-value>)',
      'c-surface': 'rgb(var(--c-surface-rgb) / <alpha-value>)',
      'c-panel': 'rgb(var(--c-panel-rgb) / <alpha-value>)',
      'c-card': 'rgb(var(--c-card-rgb) / <alpha-value>)',
      'c-text': 'rgb(var(--c-text-rgb) / <alpha-value>)',
      'c-text-dim': 'rgb(var(--c-text-dim-rgb) / <alpha-value>)',
      'c-text-muted': 'rgb(var(--c-text-muted-rgb) / <alpha-value>)',
      'c-accent': 'rgb(var(--c-accent-rgb) / <alpha-value>)',
      'c-accent-hover': 'rgb(var(--c-accent-hover-rgb) / <alpha-value>)',
      'c-accent-soft': 'var(--c-accent-soft)',
      'c-blue': 'rgb(var(--c-blue-rgb) / <alpha-value>)',
      'c-mint': 'rgb(var(--c-mint-rgb) / <alpha-value>)',
      'c-gold': 'rgb(var(--c-gold-rgb) / <alpha-value>)',
      'c-violet': 'rgb(var(--c-violet-rgb) / <alpha-value>)',
      'c-violet-soft': 'var(--c-violet-soft)',
      'c-violet-glow': 'var(--c-violet-glow)',
      'c-success': 'rgb(var(--c-success-rgb) / <alpha-value>)',
      'c-warning': 'rgb(var(--c-warning-rgb) / <alpha-value>)',
      'c-error': 'rgb(var(--c-error-rgb) / <alpha-value>)',
      'c-border': 'var(--c-border)',
      'c-border-accent': 'var(--c-border-accent)',
      'c-user-bubble': 'var(--c-user-bubble)',
      'c-ai-bubble': 'var(--c-ai-bubble)',
      'c-glow': 'var(--c-glow)',
      'c-glow-soft': 'var(--c-glow-soft)',
    },
    fontFamily: {
      sans: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Hiragino Sans", "Noto Sans SC", "Microsoft YaHei", sans-serif',
    },
  },
  shortcuts: {
    // Glassmorphism 面板 — rounded-2xl (16px) for AIRI-inspired softness
    glass: 'bg-c-surface/70 backdrop-blur-xl border border-c-border rounded-2xl',
    'glass-strong': 'bg-c-surface/85 backdrop-blur-2xl border border-c-border rounded-2xl',
    // 按钮
    'btn-accent':
      'cursor-pointer bg-c-accent hover:bg-c-accent-hover text-white rounded-xl px-4 py-2 transition-all duration-200 active:scale-95 disabled:cursor-not-allowed disabled:bg-c-card disabled:text-c-text-muted disabled:opacity-60 disabled:hover:bg-c-card disabled:active:scale-100',
    'btn-ghost':
      'cursor-pointer bg-transparent hover:bg-c-accent-soft text-c-text-dim hover:text-c-accent rounded-xl px-3 py-2 transition-all duration-200 active:scale-95 disabled:cursor-not-allowed disabled:text-c-text-muted disabled:opacity-50 disabled:hover:bg-transparent disabled:hover:text-c-text-muted disabled:active:scale-100',
    // 渐变
    'gradient-accent': 'bg-gradient-to-br from-c-accent to-c-accent-hover',
    'gradient-accent-soft': 'bg-gradient-to-br from-c-accent/20 to-c-blue/20',
    // 动画
    'animate-fade-in': 'animate-[fadeIn_var(--d-base)_var(--ease-out-expo)]',
    'animate-slide-up': 'animate-[slideUp_var(--d-slow)_var(--ease-out-expo)]',
    'animate-slide-in-right': 'animate-[slideInRight_var(--d-slow)_var(--ease-out-expo)]',
    'animate-slide-out-right': 'animate-[slideOutRight_var(--d-slow)_var(--ease-out-expo)]',
    // Mobile utilities
    'touch-manipulation': '[touch-action:manipulation]',
    'safe-bottom': 'pb-[env(safe-area-inset-bottom)]',
    'safe-top': 'pt-[env(safe-area-inset-top)]',
  },
})
