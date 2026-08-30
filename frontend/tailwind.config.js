/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        dark: {
          900: "#0f1117",
          800: "#161922",
          700: "#1f2330",
          600: "#2a2f40",
        },
        brand: {
          500: "#3b82f6",
          600: "#2563eb",
          accent: "#6366f1",
        }
      }
    },
  },
  plugins: [],
}
