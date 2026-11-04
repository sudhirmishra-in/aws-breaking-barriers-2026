import { ref } from "vue";
const read = () => { try { return localStorage.getItem("theme"); } catch { return null; } };
// Light by default, like the Fair Trade site; dark only when the viewer chooses it.
export const dark = ref(read() === "dark");
export function applyTheme() { document.documentElement.classList.toggle("dark", dark.value); }
export function toggleTheme() {
  dark.value = !dark.value; applyTheme();
  try { localStorage.setItem("theme", dark.value ? "dark" : "light"); } catch { /* per-viewer convenience only */ }
}
