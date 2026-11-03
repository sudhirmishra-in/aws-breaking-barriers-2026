import { createApp } from "vue";
import App from "./App.vue";
import { router } from "./router";
import { applyTheme } from "./lib/theme";
import "./style.css";
applyTheme();
async function boot() {
  const mock = import.meta.env.DEV ? new URLSearchParams(location.search).get("mock") : null;
  if (mock === "producer" || mock === "reviewer") (await import("./devMock")).installDevMock(mock);
  createApp(App).use(router).mount("#app");
}
boot();
