import type { Config } from "tailwindcss";
export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: { extend: { fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui"], mono: ["ui-monospace", "SFMono-Regular", "Menlo"] } } },
  plugins: [],
} satisfies Config;
