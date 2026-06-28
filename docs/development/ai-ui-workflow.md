# Asking AI to optimize Animetta's UI using this design system

The trick is to give the AI three things in every request:
**(1) the source Vue file**, **(2) the spec page that governs it**, **(3) one specific task**.
Vague asks like "make this prettier" don't work; targeted asks do.

---

## 0 · One-time setup

Drop this whole project into your Animetta repo as `design-system/`, and copy
`AGENTS.md` / `CLAUDE.md` / `.cursorrules` to the repo root.
The AI will then auto-read the spec map before answering anything UI-related.

---

## 1 · Visual audit (do this first)

> "Open `frontend/src/components/chat/MessageBubble.vue` and compare it line by line against `design-system/components.html § Chat bubbles`. List **every** deviation as a bullet — wrong color token, wrong padding, missing tail corner radius, anything. Don't fix anything yet. Just the list."

Auditing first gives you a checklist you can prioritize, instead of letting the AI rewrite things you didn't want changed.

Run this against each Vue file in turn. Good targets:

```
src/components/chat/MessageBubble.vue        ← components.html § Chat bubbles
src/components/chat/InputBar.vue             ← components.html § Input bar
src/components/chat/TypingIndicator.vue      ← components.html § Activity indicators
src/components/layout/TitleBar.vue           ← components.html § Title bar
src/components/shared/GlassPanel.vue         ← components.html § Glass panel
src/components/shared/AnimatedButton.vue     ← components.html § Buttons
src/components/live2d/SubtitleOverlay.vue    ← components.html § Subtitle overlay
```

---

## 2 · Single-component refactor

Once you have the audit, pick one file and say:

> "Refactor `frontend/src/components/chat/MessageBubble.vue` to match the spec in `design-system/components.html § Chat bubbles`. Use only tokens that exist in `frontend/uno.config.ts`. Do not change the component's public props or emit signature."

The last sentence ("don't change props/emits") is what stops AI from quietly redesigning the API while it's fixing styles.

---

## 3 · New component

> "Add a new `<Toast>` component in `frontend/src/components/shared/Toast.vue`. Follow the patterns in `design-system/components.html` for: glass surface, accent border for success, motion budget. Use UnoCSS shortcuts from `uno.config.ts` where possible. Then add a new card to `design-system/components.html` documenting it."

The "then add a card" step is critical — it keeps the design system in sync. Without it, the system drifts the moment new components ship.

---

## 4 · Full-screen layout review

Hard to do well in chat, easier with screenshots:

> "Take a screenshot of the running Animetta app. Compare it to `design-system/ui-kit.html`. For each region (titlebar / left drawer / Live2D stage / right chat panel), tell me one thing that's off."

If your AI tool can't screenshot, just describe:

> "In the current build the left drawer is 320 px wide. The spec in `ui-kit.html` says 280 px. Update `AppLayout.vue` to match, and check whether the right chat panel needs to widen to 340 px accordingly."

---

## 5 · Color cleanup

The single biggest source of visual drift is hard-coded hex values that should be tokens.

> "Search `frontend/src/` for any `#` hex color or `rgb(`/`rgba(` literal. For each one, find the matching token in `design-system/colors.html § Where each color goes` and replace it. If you can't find a matching token, **stop and ask** — don't invent."

The "stop and ask" rule is what keeps the palette from growing.

---

## 6 · Type cleanup

> "Search `frontend/src/` for any `font-size:` or `text-[NNpx]` UnoCSS class. List every size used. Compare against the 9-step scale in `design-system/typography.html`. Flag anything outside the scale."

---

## 7 · Motion audit

> "Search for any `transition:` or `animation:` rule in `frontend/src/`. List every duration and easing function. Compare against `design-system/spacing.html § Motion`. Flag anything that isn't 150/200/300 ms × `ease-out-expo`/`ease-back-soft`."

---

## 8 · Iterative refinement (the loop you'll actually use)

For tricky cases, run this loop:

1. **You:** "Show me the current `<InputBar>` rendered next to the spec card from `components.html § Input bar`. What's different?"
2. **AI:** lists 3 things
3. **You:** pick one. "Fix #2 only."
4. **AI:** patches it
5. **You:** "Now screenshot the result. Is #2 actually resolved?"
6. Repeat until the AI's list is empty.

This is slower than "make it match the spec," but it stops the AI from regressing other things while fixing the one you cared about.

---

## Anti-patterns to avoid

- **"Make it look better."** — too vague, AI will redesign things you wanted to keep.
- **"Apply the design system."** — too broad. Always scope to one file.
- **Asking AI to "improve" the spec.** — if the spec changes, that's a human conversation, not an AI task.
- **Letting AI silently add a new color.** — if it does, ask it to justify the addition and document it in `colors.html`. Otherwise revert.

---

## Quick reference — which spec governs which file

| Vue file | Spec card |
|---|---|
| `MessageBubble.vue` | `components.html § Chat bubbles` |
| `InputBar.vue` | `components.html § Input bar` |
| `TypingIndicator.vue`, `SpeakingIndicator.vue` | `components.html § Activity indicators` |
| `TitleBar.vue` | `components.html § Title bar` |
| `GlassPanel.vue` | `components.html § Glass panel` |
| `AnimatedButton.vue` | `components.html § Buttons` |
| `SubtitleOverlay.vue` | `components.html § Subtitle overlay` |
| `PersonalityPanel.vue` | `components.html § Glass panel` + voice rules in `brand.html` |
| `SettingsPanel.vue` | `iconography.html § In context` (tabs + rows) |
| `BackgroundSettings.vue` | `iconography.html § Composition rules` |
| `AppLayout.vue` | `ui-kit.html` (the full assembly) |
