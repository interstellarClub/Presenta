export interface FontPackage {
  display: string;
  body: string;
  mono: string;
}

export const DEFAULT_FONTS: FontPackage = {
  display: 'Inter, "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif',
  body: 'Inter, "Source Sans 3", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif',
  mono: '"JetBrains Mono", SFMono-Regular, Consolas, monospace',
};

export const CJK_SIZE_COMPENSATION = 1.03;

export function buildTypographyCss(): string {
  return `
  :root {
    --cjk-scale: ${CJK_SIZE_COMPENSATION};
    --line-height-cjk: 1.75;
    --line-height-mixed: 1.65;
    --line-height-heading: 1.25;
  }
  body {
    font-family: var(--font-body, ${DEFAULT_FONTS.body});
    text-autospace: normal;
    line-break: strict;
    word-break: normal;
    overflow-wrap: anywhere;
    -webkit-font-smoothing: antialiased;
  }
  h1, h2, h3, h4 {
    font-family: var(--font-display, ${DEFAULT_FONTS.display});
    line-height: var(--line-height-heading);
    text-wrap: balance;
  }
  .zh-heavy { line-height: var(--line-height-cjk); }
  .mixed { line-height: var(--line-height-mixed); }
  .mono { font-family: var(--font-mono, ${DEFAULT_FONTS.mono}); }
  .cjk-compensate { font-size: calc(1em * var(--cjk-scale)); }
  code, pre { font-family: var(--font-mono, ${DEFAULT_FONTS.mono}); }
  `;
}