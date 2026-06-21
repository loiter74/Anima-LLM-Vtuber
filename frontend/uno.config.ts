import { defineConfig, presetUno, presetIcons, transformerDirectives } from 'unocss'

export default defineConfig({
  presets: [
    presetUno({
      dark: 'class'
    }),
    presetIcons({
      scale: 1.2
    })
  ],
  transformers: [
    transformerDirectives()
  ],
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
      'c-bg': 'var(--c-bg)',
      'c-surface': 'var(--c-surface)',
      'c-panel': 'var(--c-panel)',
      'c-card': 'var(--c-card)',
      'c-text': 'var(--c-text)',
      'c-text-dim': 'var(--c-text-dim)',
      'c-text-muted': 'var(--c-text-muted)',
      'c-accent': 'var(--c-accent)',
      'c-accent-hover': 'var(--c-accent-hover)',
      'c-accent-soft': 'var(--c-accent-soft)',
      'c-blue': 'var(--c-blue)',
      'c-mint': 'var(--c-mint)',
      'c-gold': 'var(--c-gold)',
      'c-violet': 'var(--c-violet)',
      'c-violet-soft': 'var(--c-violet-soft)',
      'c-violet-glow': 'var(--c-violet-glow)',
      'c-success': 'var(--c-success)',
      'c-warning': 'var(--c-warning)',
      'c-error': 'var(--c-error)',
      'c-border': 'var(--c-border)',
      'c-border-accent': 'var(--c-border-accent)',
      'c-user-bubble': 'var(--c-user-bubble)',
      'c-ai-bubble': 'var(--c-ai-bubble)',
      'c-glow': 'var(--c-glow)',
      'c-glow-soft': 'var(--c-glow-soft)',
    },
    fontFamily: {
      sans: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Hiragino Sans", "Noto Sans SC", "Microsoft YaHei", sans-serif',
      quicksand: '"Quicksand", sans-serif',
    }
  },
  shortcuts: {
    // Glassmorphism 面板 — rounded-2xl (16px) for AIRI-inspired softness
    'glass': 'bg-c-surface/70 backdrop-blur-xl border border-c-border rounded-2xl',
    'glass-strong': 'bg-c-surface/85 backdrop-blur-2xl border border-c-border rounded-2xl',
    // 按钮
    'btn-accent': 'bg-c-accent hover:bg-c-accent-hover text-white rounded-xl px-4 py-2 transition-all duration-200 active:scale-95',
    'btn-ghost': 'bg-transparent hover:bg-c-accent-soft text-c-text-dim hover:text-c-accent rounded-xl px-3 py-2 transition-all duration-200',
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
  }
})
