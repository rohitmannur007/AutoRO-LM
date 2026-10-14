/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#071018",
        panel: "#0e1b2a",
        panel2: "#132536",
        line: "#234056",
        mist: "#9eb2c6",
        foam: "#e7eef6",
        teal: "#2ec4b6",
        amber: "#e2b340",
      },
      fontFamily: {
        sans: ['"Avenir Next"', "Segoe UI", "sans-serif"],
        mono: ['"SF Mono"', "ui-monospace", "Menlo", "monospace"],
      },
      boxShadow: {
        inset: "inset 0 1px 0 rgba(255,255,255,0.04)",
      },
    },
  },
  plugins: [],
};
