/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      colors: {
        ink: { 950: "#05070d", 900: "#0a0e1a", 850: "#0d1222", 800: "#111830", 700: "#1a2342" },
      },
      boxShadow: {
        glow: "0 0 40px -8px rgba(99,102,241,0.45)",
        "glow-rose": "0 0 50px -6px rgba(244,63,94,0.55)",
        "glow-emerald": "0 0 40px -8px rgba(16,185,129,0.5)",
      },
      keyframes: {
        shimmer: { "0%": { transform: "translateX(-100%)" }, "100%": { transform: "translateX(200%)" } },
        wave: { "0%,100%": { transform: "scaleY(0.35)" }, "50%": { transform: "scaleY(1)" } },
        ring: { "0%": { transform: "scale(0.9)", opacity: "0.7" }, "100%": { transform: "scale(1.8)", opacity: "0" } },
      },
      animation: {
        shimmer: "shimmer 1.6s ease-in-out infinite",
        wave: "wave 1s ease-in-out infinite",
        ring: "ring 2.2s cubic-bezier(0.2,0.6,0.3,1) infinite",
      },
    },
  },
  plugins: [],
};
