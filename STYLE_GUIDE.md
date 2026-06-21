# STYLE GUIDE

## §1 Quick Decision

New code uses UnoCSS utility classes exclusively. Existing CSS-variable code migrates to UnoCSS when the file is modified.

## §2 CSS Variable → UnoCSS Mapping Table

### Color Tokens

| CSS Variable | UnoCSS Classes |
|---|---|
| `var(--c-bg)` | `bg-c-bg`, `text-c-bg` |
| `var(--c-surface)` | `bg-c-surface`, `text-c-surface` |
| `var(--c-panel)` | `bg-c-panel`, `text-c-panel` |
| `var(--c-card)` | `bg-c-card`, `text-c-card` |
| `var(--c-text)` | `text-c-text` |
| `var(--c-text-dim)` | `text-c-text-dim` |
| `var(--c-text-muted)` | `text-c-text-muted` |
| `var(--c-accent)` | `text-c-accent`, `bg-c-accent`, `border-c-accent` |
| `var(--c-accent-hover)` | `bg-c-accent-hover` |
| `var(--c-accent-soft)` | `bg-c-accent-soft` |
| `var(--c-blue)` | `text-c-blue`, `bg-c-blue` |
| `var(--c-mint)` | `text-c-mint`, `bg-c-mint` |
| `var(--c-gold)` | `text-c-gold`, `bg-c-gold` |
| `var(--c-violet)` | `text-c-violet`, `bg-c-violet` |
| `var(--c-violet-soft)` | `bg-c-violet-soft` |
| `var(--c-violet-glow)` | Use `shadow` or inline `style` — no direct UnoCSS class |
| `var(--c-success)` | `text-c-success`, `bg-c-success` |
| `var(--c-warning)` | `text-c-warning`, `bg-c-warning` |
| `var(--c-error)` | `text-c-error`, `bg-c-error` |
| `var(--c-border)` | `border-c-border` |
| `var(--c-border-accent)` | `border-c-border-accent` |
| `var(--c-user-bubble)` | `bg-c-user-bubble` |
| `var(--c-ai-bubble)` | `bg-c-ai-bubble` |
| `var(--c-glow)` | Use `shadow` or inline `style` — no direct UnoCSS class |
| `var(--c-glow-soft)` | Use `shadow` or inline `style` — no direct UnoCSS class |

### Spacing

UnoCSS uses the Tailwind-compatible spacing scale with a 4px base unit: `p-1` (4px) through `p-96` (384px). Margin and gap follow the same scale (`m-*`, `gap-*`).

### Border Radius

| UnoCSS Class | Value |
|---|---|
| `rounded-sm` | 2px |
| `rounded` | 4px |
| `rounded-lg` | 8px |
| `rounded-xl` | 12px (default for Animetta UI) |
| `rounded-2xl` | 16px |

### Shadows

| UnoCSS Class | Description |
|---|---|
| `shadow-sm` | Subtle shadow |
| `shadow` | Default shadow |
| `shadow-md` | Medium shadow |
| `shadow-lg` | Large shadow |
| `shadow-xl` | Extra-large shadow |
| `shadow-2xl` | Maximum shadow |

### Typography

| UnoCSS Class | Description |
|---|---|
| `font-sans` | System CJK font stack |
| `font-quicksand` | Quicksand (UI chrome, labels) |

### Motion

| UnoCSS Class | CSS Variable | Duration |
|---|---|---|
| `duration-150` | `--d-fast` | 150ms |
| `duration-200` | `--d-base` | 200ms |
| `duration-300` | `--d-slow` | 300ms |

### Shortcuts

| Shortcut | Resolves To |
|---|---|
| `glass` | Glass-panel background with subtle transparency |
| `glass-strong` | Heavier glass effect for overlays |
| `btn-accent` | Accent-colored action button |
| `btn-ghost` | Ghost/outline button |
| `gradient-accent` | Accent gradient background |
| `animate-fade-in` | Fade-in entrance animation |
| `animate-slide-up` | Slide-up entrance animation |

## §3 Component Template

```vue
<script setup lang="ts">
// Composition API only
</script>

<template>
  <div class="glass p-4 rounded-2xl">
    <h2 class="text-lg font-semibold text-c-text">Title</h2>
    <p class="text-sm text-c-text-dim">Description text</p>
    <button class="btn-accent">Action</button>
    <button class="btn-ghost">Cancel</button>
  </div>
</template>
```

## §4 Naming Conventions

- Use `c-*` for design-system color tokens exposed through UnoCSS.
- Use semantic names (`c-error`, `c-violet`) instead of raw color-family utility classes.
- Keep component-local CSS class names descriptive and scoped to the component role.
- Prefer existing shortcuts (`glass`, `btn-accent`, `btn-ghost`) before adding new classes.
- New visual tokens must be added to `frontend/uno.config.ts`, `frontend/src/styles/themes.css`, and the matching `design-system/*.html` spec.

## §5 Code Review Checklist

- [ ] New code uses UnoCSS (no raw `var(--c-*)` in `<style>` blocks)
- [ ] Colors use design tokens (no hardcoded hex like `#e879a8`)
- [ ] Default border-radius is `rounded-xl` (12px), no sharp corners
- [ ] Animation durations use `duration-*` tokens, max 300ms
- [ ] Glass panels use `glass` or `glass-strong` shortcut
- [ ] New components have corresponding cards in `design-system/components.html` (or noted as pending)

## §6 Migration Example

**Before** (using CSS variables):

```css
.my-panel {
  background: var(--c-surface);
  color: var(--c-text);
  border: 1px solid var(--c-border);
  border-radius: 12px;
  padding: 16px;
}
```

**After** (using UnoCSS):

```html
<div class="bg-c-surface text-c-text border border-c-border rounded-xl p-4">
```
