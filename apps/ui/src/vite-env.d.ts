/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ARENA_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
