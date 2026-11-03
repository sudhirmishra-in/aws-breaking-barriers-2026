export interface AppConfig { region: string; apiBaseUrl: string; clientId: string; issuer: string; authority: string; cognitoDomain: string; redirectUri: string; logoutUri: string }
let cfg: AppConfig | undefined;
export async function loadConfig(): Promise<AppConfig> {
  if (cfg) return cfg;
  const r = await fetch("/config.json", { cache: "no-store" });
  if (!r.ok) throw new Error("config.json missing");
  cfg = (await r.json()) as AppConfig;
  return cfg;
}
