# AgentTrust — Design Tokens

**Status:** Phase 6 (design system). Tokens live in `apps/web/app/tokens.css`;
Tailwind utilities reference them via `apps/web/tailwind.config.js`.
Default theme is **dark** (`<html class="dark">`); light is opt-in via the
header theme toggle, persisted to `localStorage` as `agenttrust_theme`.

## How themes work

- `:root` defines the **light** theme. `.dark` overrides every token for the
  **dark** theme.
- The root layout renders `<html class="dark">` statically and runs a
  pre-paint script that removes the class only for a stored `"light"`
  preference — no flash, correct default.
- Both scopes set `color-scheme` so native controls (scrollbars, form
  controls) match.

## Token reference

### Neutrals

| Token | Light | Dark | Use |
|---|---|---|---|
| `--at-bg` | `#ffffff` | `#0a0a0d` | Page background |
| `--at-surface` | `#f7f7f9` | `#121216` | Cards, header, sidebar |
| `--at-surface-2` | `#efeff2` | `#1a1a20` | Hover fills, table heads, skeleton base |
| `--at-border` | `#e2e2e8` | `#27272e` | Borders, dividers |
| `--at-text-1` | `#17171b` | `#f0f0f4` | Primary text, headings |
| `--at-text-2` | `#52525c` | `#b4b4bf` | Secondary text, labels |
| `--at-text-3` | `#8d8d99` | `#7d7d8a` | Tertiary text, placeholders, muted |

### Brand accent

| Token | Light | Dark | Use |
|---|---|---|---|
| `--at-brand` | `#1d4ed8` | `#2563eb` | Primary buttons, active nav indicator |
| `--at-brand-hover` | `#1e40af` | `#3b82f6` | Primary button hover |
| `--at-brand-text` | `#ffffff` | `#ffffff` | Text on brand backgrounds |

### Semantic security colors

Each semantic color has three slots: `-bg` (tinted fill), `-text`
(foreground), `-border`. A status indicator must always use **all three
together as icon + text label** — never a bare colored dot or bare colored
text.

| Slot | allow (green) | deny (red) | review (amber) | info (blue) | neutral (slate) |
|---|---|---|---|---|---|
| Light bg | `#e7f6ee` | `#fdecec` | `#fdf3e0` | `#e9f1fd` | `#f1f1f5` |
| Light text | `#14703c` | `#b42318` | `#9a5b0b` | `#1d4ed8` | `#52525c` |
| Light border | `#a9dfc0` | `#f3b8b3` | `#f0d29a` | `#b4cdf6` | `#d4d4dc` |
| Dark bg | `#0e2a1b` | `#2e1518` | `#2e2410` | `#122539` | `#16161b` |
| Dark text | `#7ee2a8` | `#f08a8a` | `#f2c66d` | `#8fc3ff` | `#bcbdc9` |
| Dark border | `#1d4d33` | `#5c2222` | `#5c451a` | `#24496f` | `#33333b` |

Mapping to product meaning:

- **allow / green** — ALLOW decisions, connected/live states, success.
- **deny / red** — DENY decisions, offline/error states, destructive actions.
- **review / amber** — REVIEW decisions, pending approvals, reconnecting,
  warnings.
- **info / blue** — informational callouts, environment label, links.
- **neutral / slate** — expired, dismissed, unknown, or metadata states.

### Spacing, radii, fonts

- Spacing: `--at-space-1` (0.25rem), `-2` (0.5rem), `-3` (0.75rem),
  `-4` (1rem), `-6` (1.5rem), `-8` (2rem). Identical in both themes.
- Radii: `--at-radius-sm` 4px, `-md` 8px, `-lg` 12px, `-xl` 16px.
- `--at-font-sans`: Inter via `next/font` (`--font-sans` variable), then
  `system-ui, -apple-system, "Segoe UI", Arial, sans-serif`.
- `--at-font-mono`: `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`.

### Focus

- `--at-focus-ring`: `#1d4ed8` (light) / `#5b9bff` (dark). Applied globally
  on `:focus-visible` (2px outline, 2px offset) in `globals.css`. Every
  interactive element must keep a visible focus indicator — do not suppress
  focus outlines on components.

### Elevation

- `--at-shadow-card`, `--at-shadow-popover`. Dark theme separates surfaces
  with borders rather than shadows (`--at-shadow-card: none`); light theme
  uses soft shadows.

## Usage rules

1. **Status is never color alone.** Every status carries an icon AND a text
   label (`Badge` and `ConnectionBadge` enforce this structurally).
2. **No hard-coded colors in components.** Reference tokens (directly or via
   the Tailwind color aliases: `bg-surface`, `text-text-1`, `bg-allow-bg`,
   `text-deny-text`, `border-review-border`, ...). A hex/rgb literal in a
   component is a bug.
3. **No emojis in the UI.** Inline SVG icons only (`components/icons.tsx`).
4. **Dark is the default; light must also work.** Check both themes before
   calling a page done. The toggle is in the shell header.
5. **Secrets never render.** API keys appear only in password inputs and
   `Authorization` headers; never in labels, titles, tooltips, or logs.
   The SSE query param key is used only to construct the `EventSource` —
   never rendered.
6. **Reduced motion is respected** globally in `globals.css`
   (`prefers-reduced-motion` disables the reconnect pulse and transitions).

## Contrast notes

Target is WCAG AA (4.5:1 for normal text, 3:1 for large text and UI
components). Spot-checked pairs (dark default first):

- `text-1` on `bg`: ~15:1 (dark) / ~16:1 (light) — AA.
- `text-2` on `bg`: ~8:1 (dark) / ~7:1 (light) — AA.
- `text-3` on `bg`: ~4:1 (dark) / ~3.5:1 (light) — decorative/large use only;
  never for body copy.
- Semantic text on its own `-bg`: allow ~7:1, deny ~6:1, review ~6:1,
  info ~7:1 (both themes) — AA for the badge labels.
- `brand-text` on `brand`: ~5:1 (dark) / ~8:1 (light) — AA for button text.

`text-3` is deliberately the weakest pair; use it for placeholders, hints,
and captions — not for information the user must read to act safely.
