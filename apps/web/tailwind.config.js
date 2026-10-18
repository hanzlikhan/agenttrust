/** @type {import('tailwindcss').Config} */
module.exports = {
  // Class-based dark mode: the shell toggles `dark` on <html> and persists
  // the choice to localStorage. Default theme is dark.
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./hooks/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Neutral surfaces — resolved from CSS custom properties in
        // app/tokens.css so both themes ship without duplicating utilities.
        bg: "var(--at-bg)",
        surface: "var(--at-surface)",
        "surface-2": "var(--at-surface-2)",
        border: "var(--at-border)",
        "text-1": "var(--at-text-1)",
        "text-2": "var(--at-text-2)",
        "text-3": "var(--at-text-3)",
        brand: {
          DEFAULT: "var(--at-brand)",
          hover: "var(--at-brand-hover)",
          text: "var(--at-brand-text)",
        },
        // Semantic security colors. Always pair with an icon + text label;
        // color is never the only signal (see docs/DESIGN_TOKENS.md).
        allow: {
          DEFAULT: "var(--at-allow-text)",
          bg: "var(--at-allow-bg)",
          border: "var(--at-allow-border)",
          text: "var(--at-allow-text)",
        },
        deny: {
          DEFAULT: "var(--at-deny-text)",
          bg: "var(--at-deny-bg)",
          border: "var(--at-deny-border)",
          text: "var(--at-deny-text)",
        },
        review: {
          DEFAULT: "var(--at-review-text)",
          bg: "var(--at-review-bg)",
          border: "var(--at-review-border)",
          text: "var(--at-review-text)",
        },
        info: {
          DEFAULT: "var(--at-info-text)",
          bg: "var(--at-info-bg)",
          border: "var(--at-info-border)",
          text: "var(--at-info-text)",
        },
        neutral: {
          DEFAULT: "var(--at-neutral-text)",
          bg: "var(--at-neutral-bg)",
          border: "var(--at-neutral-border)",
          text: "var(--at-neutral-text)",
        },
      },
      borderRadius: {
        sm: "var(--at-radius-sm)",
        md: "var(--at-radius-md)",
        lg: "var(--at-radius-lg)",
        xl: "var(--at-radius-xl)",
      },
      fontFamily: {
        sans: "var(--at-font-sans)",
        mono: "var(--at-font-mono)",
      },
      spacing: {
        // Mirror of the token scale for one-off use; prefer tokens in CSS.
        "at-1": "var(--at-space-1)",
        "at-2": "var(--at-space-2)",
        "at-3": "var(--at-space-3)",
        "at-4": "var(--at-space-4)",
        "at-6": "var(--at-space-6)",
        "at-8": "var(--at-space-8)",
      },
      boxShadow: {
        card: "var(--at-shadow-card)",
        popover: "var(--at-shadow-popover)",
      },
    },
  },
  plugins: [],
};
