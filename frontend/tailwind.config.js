/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Simple brand-ish palette; swap these to rebrand the demo.
        ink: "#0f172a",
        accent: "#4f46e5",
      },
    },
  },
  plugins: [],
};
