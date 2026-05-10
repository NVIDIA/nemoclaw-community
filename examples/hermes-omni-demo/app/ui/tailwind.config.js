/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["'Geist'", "system-ui", "sans-serif"],
        mono: ["'Geist Mono'", "ui-monospace", "monospace"],
      },
      colors: {
        ink: {
          950: "#0a0a0a",
          900: "#111111",
          800: "#171717",
          700: "#1f1f1f",
          600: "#2a2a2a",
          500: "#3a3a3a",
          400: "#6b6b6b",
          300: "#8a8a8a",
          200: "#b4b4b4",
          100: "#e5e5e5",
          50: "#fafafa",
        },
        nv: {
          DEFAULT: "#76B900",
          bright: "#8FD900",
          soft: "#1f3000",
          glow: "rgba(118,185,0,0.5)",
        },
        hermes: {
          DEFAULT: "#F4C430",
          bright: "#FFD84D",
          soft: "#4a3c00",
          dim: "#B58B00",
        },
        danger: {
          DEFAULT: "#F26B3A",
        },
      },
      boxShadow: {
        soft: "0 1px 2px rgba(0,0,0,0.4), 0 8px 24px -12px rgba(0,0,0,0.6)",
        lift: "0 2px 6px rgba(0,0,0,0.3), 0 20px 60px -30px rgba(0,0,0,0.7)",
        glow: "0 0 0 1px rgba(118,185,0,0.35), 0 0 28px -8px rgba(118,185,0,0.45)",
      },
      animation: {
        "pulse-soft": "pulse-soft 2.2s ease-in-out infinite",
        "fade-up": "fade-up 0.45s cubic-bezier(0.2,0.7,0.2,1) both",
        "shimmer": "shimmer 2.5s linear infinite",
      },
      keyframes: {
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.55" },
        },
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
      },
    },
  },
  plugins: [],
};
