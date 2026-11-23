export interface UserProfile {
  id: string;
  email: string;
  displayName?: string | null;
  status: string;
  createdAt: string;
}

export interface AuthResponse {
  user: UserProfile;
  expiresAt: string;
}

export interface SectionNode {
  id: string;
  title: string;
  level: number;
  parentId?: string | null;
  lineStart: number;
  lineEnd: number;
  preview: string;
}

export interface AssetSummary {
  id: string;
  kind: "image" | "table" | "formula";
  mime?: string | null;
  sourceRef?: Record<string, number> | null;
  meta?: Record<string, unknown> | null;
}

export interface DocumentSummary {
  id: string;
  title: string;
  sourceType: string;
  status: string;
  degraded: boolean;
  createdAt: string;
  updatedAt: string;
  sectionCount: number;
  assetCount: number;
  hasOutline: boolean;
}

export interface DocumentDetail extends DocumentSummary {
  normalizedMd: string;
  sections: SectionNode[];
  assets: AssetSummary[];
  outline?: Outline | null;
  error?: Record<string, unknown> | null;
}

export interface OutlineItem {
  id: string;
  title: string;
  points: string[];
  sectionId?: string | null;
  layoutHint?: string | null;
}

export interface Outline {
  title: string;
  subtitle: string;
  items: OutlineItem[];
}

export interface SourceRef {
  lineStart: number;
  colStart: number;
  lineEnd: number;
  colEnd: number;
}

export interface Provenance {
  type: "original" | "derived" | "external";
  documentId: string;
  sourceRef: SourceRef;
  quote: string;
  originalData?: unknown;
  externalUrl?: string | null;
  license?: string | null;
}

export interface AnimSpec {
  trigger: "enter" | "click" | "loop";
  effect: string;
  delay: number;
  duration: number;
  easing: string;
}

export interface ElementLayout {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface SlideElement {
  id: string;
  type: string;
  slotPath: string;
  layout?: ElementLayout | null;
  styleOverride: Record<string, string | number>;
  anim: AnimSpec[];
  component?: { name: string; config: Record<string, unknown> } | null;
  provenance?: Provenance | null;
}

export interface Slide {
  id: string;
  layout: string;
  slots: Record<string, unknown>;
  transition?: { effect: string; duration: number } | null;
  steps: string[];
  notes: string;
  degraded: boolean;
  degradedReason?: string | null;
  elements: SlideElement[];
  provenance: Provenance[];
}

export interface DeckMeta {
  title: string;
  subtitle: string;
  author: string;
  sourceDocumentId?: string | null;
  language: "zh" | "en" | "mixed";
}

export interface DeckPayload {
  schemaVersion: number;
  id: string;
  themeId: string;
  motionLevel: number;
  meta: DeckMeta;
  slides: Slide[];
  provenance: Provenance[];
}

export interface DeckResponse {
  deck: DeckPayload;
  versionSeq: number;
  degradedSlides: string[];
  wcag?: { checks: { pair: string; ratio: number; passesAA: boolean }[]; passesAA: boolean } | null;
}

export interface VersionSummary {
  id: string;
  seq: number;
  parentId?: string | null;
  kind: "autosave" | "milestone" | "anchor";
  label?: string | null;
  hasSnapshot: boolean;
  createdAt: string;
}

export interface JobView {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled" | "partial";
  progress: number;
  stage?: string | null;
  attempts: number;
  maxAttempts: number;
  result?: Record<string, unknown> | null;
  error?: Record<string, unknown> | null;
  createdAt: string;
  updatedAt: string;
}

export interface ThemeManifest {
  id: string;
  name: string;
  version: number;
  cssVariables: Record<string, string>;
  layouts: string[];
  motionCapabilities: string[];
  typography?: {
    scale: number;
    lineHeightBody: number;
    lineHeightCJK: number;
    lineHeightHeading: number;
  } | null;
  wcag: { checks: { pair: string; ratio: number; passesAA: boolean }[]; passesAA: boolean };
}

export interface DocumentCreated {
  document: DocumentSummary;
  jobId?: string | null;
}

export interface GenerateResponse {
  jobId: string;
  versionSeq: number;
}

export interface ShareSummary {
  id: string;
  slug: string;
  url: string;
  expiresAt: string;
  allowDownload: boolean;
  downloadFormats: string[];
  viewCount: number;
}

export interface ExportArtifact {
  id: string;
  format: string;
  bytes: number;
  degraded: boolean;
  degradedNotes: string[];
  downloadUrl: string;
  expiresAt: string;
}