/// <reference types="vite/client" />

declare namespace ImportMeta {
  interface Env {
    readonly VITE_API_BASE_URL?: string;
  }

  interface ImportMeta {
    readonly env: Env;
  }
}
