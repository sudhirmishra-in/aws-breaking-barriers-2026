import { ref } from "vue";
const read = () => { try { return localStorage.getItem("theme"); } catch { return null; } };
export const dark = ref((read() ?? (window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark");
export function applyTheme() { document.documentElement.classList.toggle("dark", dark.value); }
export function toggleTheme() {
  dark.value = !dark.value; applyTheme();
  try { localStorage.setItem("theme", dark.value ? "dark" : "light"); } catch { /* per-viewer convenience only */ }
}
