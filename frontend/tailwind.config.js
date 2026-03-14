/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          primary: "#0A0B0E",
          secondary: "#111318",
          card: "#161920",
          border: "#1E2028",
        },
        accent: {
          green: "#00D4AA",
          red: "#FF4757",
          blue: "#4C8BF5",
          orange: "#FF8C42",
          purple: "#8B5CF6",
          yellow: "#FFD166",
        },
        text: {
          primary: "#EAEAEA",
          secondary: "#8B8FA8",
          muted: "#4A4E61",
        }
      },
      fontFamily: {
        sans: ["Inter", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      }
    }
  },
  plugins: []
}
