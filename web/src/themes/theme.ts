import type { ThemeManifest } from "@/types";

export interface ThemeTokens {
  vars: Record<string, string>;
  typographyScale: number;
}

const FALLBACK_VARS: Record<string, string> = {
  "--color-bg": "#FBFAF7",
  "--color-surface": "#FFFFFF",
  "--color-text": "#1B1B1F",
  "--color-muted": "#5B5B66",
  "--color-primary": "#7A1F1F",
  "--color-accent": "#1F4E79",
  "--color-border": "#D9D5CC",
  "--color-on-primary": "#FFFFFF",
  "--size-1": "16px",
  "--size-2": "20px",
  "--size-3": "28px",
  "--size-4": "40px",
  "--size-5": "64px",
  "--radius-sm": "4px",
  "--radius-md": "8px",
  "--radius-lg": "12px",
  "--shadow-sm": "0 1px 2px rgba(27,27,31,0.08)",
  "--shadow-md": "0 8px 24px rgba(27,27,31,0.10)",
};

export function themeTokens(theme: ThemeManifest | null): ThemeTokens {
  const vars = { ...FALLBACK_VARS, ...(theme?.cssVariables ?? {}) };
  return {
    vars,
    typographyScale: theme?.typography?.scale ?? 1,
  };
}

export function tokenVarsCss(tokens: ThemeTokens): string {
  const declarations = Object.entries(tokens.vars)
    .filter(([key]) => key.startsWith("--"))
    .map(([key, value]) => `${key}: ${value};`)
    .join("\n  ");
  return `:root {\n  ${declarations}\n}`;
}

export function assetUrl(documentId: string | null | undefined, assetId: string): string {
  if (!documentId) return "";
  return `/api/documents/${documentId}/assets/${assetId}`;
}