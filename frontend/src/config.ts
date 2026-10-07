export interface AppConfig {
  apiBaseUrl: string;
  oidcAuthority: string;
  oidcClientId: string;
}

declare global {
  interface Window {
    __APP_CONFIG__?: Partial<AppConfig>;
  }
}

const defaults: AppConfig = {
  apiBaseUrl: "/api/v1",
  oidcAuthority: "http://localhost:8080/realms/incident",
  oidcClientId: "incident-manager",
};

export const config: AppConfig = { ...defaults, ...window.__APP_CONFIG__ };
