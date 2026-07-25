/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#14121C",
        surface: "#1E1B29",
        raised: "#272335",
        line: "#322D45",
        muted: "#9891B0",
        paper: "#F4F1FA",
        brand: {
          DEFAULT: "#7C5CFC",
          dim: "#5B3FE0",
          glow: "#A78BFA",
        },
        pulse: {
          DEFAULT: "#FFB454",
          dim: "#B9803A",
        },
        rasp: {
          DEFAULT: "#FB6F92",
          dim: "#B24E68",
        },
      },
      fontFamily: {
        display: ["'Fraunces'", "serif"],
        sans: ["'Manrope'", "sans-serif"],
        mono: ["'JetBrains Mono'", "monospace"],
      },
      borderRadius: {
        xl2: "1.25rem",
      },
      boxShadow: {
        soft: "0 8px 30px -10px rgba(0,0,0,0.45)",
        glow: "0 0 0 1px rgba(124,92,252,0.35), 0 8px 24px -8px rgba(124,92,252,0.45)",
      },
      backgroundImage: {
        "grain": "radial-gradient(circle at 20% 10%, rgba(124,92,252,0.14), transparent 40%), radial-gradient(circle at 80% 0%, rgba(255,180,84,0.08), transparent 35%)",
      },
      keyframes: {
        pulseBar: {
          "0%, 100%": { transform: "scaleY(0.4)" },
          "50%": { transform: "scaleY(1)" },
        },
        floatUp: {
          "0%": { opacity: 0, transform: "translateY(8px)" },
          "100%": { opacity: 1, transform: "translateY(0)" },
        },
      },
      animation: {
        pulseBar: "pulseBar 1.1s ease-in-out infinite",
        floatUp: "floatUp 0.4s ease-out both",
      },
    },
  },
  plugins: [],
};
