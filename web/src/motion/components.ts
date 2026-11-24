export interface MotionComponent {
  render(): void;
  seek(timeMs: number): void;
  duration(): number;
  keyframe?(): number;
}

export interface MotionSpec {
  name: string;
  config: Record<string, unknown>;
  layout: { x: number; y: number; w: number; h: number };
}

function text(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function shell(el: HTMLElement, spec: MotionSpec): HTMLElement {
  el.className = "motion-component";
  el.style.position = "absolute";
  el.style.left = `${(spec.layout.x / 12) * 100}%`;
  el.style.top = `${spec.layout.y}%`;
  el.style.width = `${(spec.layout.w / 12) * 100}%`;
  el.style.height = `${spec.layout.h}%`;
  el.style.overflow = "hidden";
  return el;
}

abstract class BaseMotion implements MotionComponent {
  protected durationMs = 1200;
  constructor(protected host: HTMLElement, protected spec: MotionSpec, protected level: number) {}
  abstract render(): void;
  abstract seek(timeMs: number): void;
  duration(): number {
    return Math.max(0, this.durationMs * this.level);
  }
}

class StepReveal extends BaseMotion {
  private steps: HTMLElement[] = [];
  render(): void {
    const steps = list(this.spec.config.steps);
    this.steps = steps.map((entry) => {
      const row = document.createElement("div");
      row.className = "motion-step";
      row.textContent = text(entry);
      row.style.padding = "6px 10px";
      row.style.borderLeft = "3px solid var(--color-primary)";
      row.style.marginBottom = "8px";
      this.host.appendChild(row);
      return row;
    });
  }
  seek(timeMs: number): void {
    const duration = this.duration();
    const progress = duration === 0 ? 1 : Math.min(1, Math.max(0, timeMs / duration));
    this.steps.forEach((step, index) => {
      step.style.opacity = index < Math.ceil(progress * this.steps.length) ? "1" : "0.12";
      step.style.transform = `translateX(${(1 - progress) * 18}px)`;
    });
  }
}

class ChartReveal extends BaseMotion {
  private bars: SVGRectElement[] = [];
  render(): void {
    const series = list(this.spec.config.series);
    const points = series.length
      ? list((series[0] as Record<string, unknown>).points)
      : list(this.spec.config.points);
    const values = points.map((entry) => Number((entry as Record<string, unknown>).value) || 0);
    const max = Math.max(1, ...values);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 640 320");
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "100%");
    values.forEach((value, index) => {
      const bar = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      const width = 560 / Math.max(1, values.length);
      bar.setAttribute("x", String(40 + index * width));
      bar.setAttribute("y", String(280 - (value / max) * 240));
      bar.setAttribute("width", String(width * 0.62));
      bar.setAttribute("height", String((value / max) * 240));
      bar.setAttribute("fill", "var(--color-primary)");
      svg.appendChild(bar);
      this.bars.push(bar);
    });
    this.host.appendChild(svg);
  }
  seek(timeMs: number): void {
    const duration = this.duration();
    this.bars.forEach((bar, index) => {
      const start = duration * (index / Math.max(1, this.bars.length));
      bar.style.opacity = String(
        duration === 0 || timeMs >= start ? 1 : Math.max(0, (timeMs - start + 120) / 120),
      );
      bar.style.transformOrigin = "bottom";
    });
  }
}

class FlowDiagram extends BaseMotion {
  private nodes: HTMLElement[] = [];
  render(): void {
    this.host.style.display = "flex";
    this.host.style.alignItems = "center";
    this.host.style.justifyContent = "space-around";
    this.host.style.gap = "12px";
    this.nodes = list(this.spec.config.nodes).map((entry) => {
      const node = document.createElement("div");
      node.textContent = text((entry as Record<string, unknown>).label ?? entry);
      node.style.padding = "14px";
      node.style.border = "1px solid var(--color-border)";
      node.style.borderRadius = "10px";
      node.style.background = "var(--color-surface)";
      this.host.appendChild(node);
      return node;
    });
  }
  seek(timeMs: number): void {
    const duration = this.duration();
    this.nodes.forEach((node, index) => {
      const threshold = duration * (index / Math.max(1, this.nodes.length));
      node.style.opacity = timeMs >= threshold ? "1" : "0.15";
    });
  }
}

class FormulaStep extends StepReveal {
  render(): void {
    const formulas = list(this.spec.config.formulas ?? this.spec.config.steps);
    this.spec = { ...this.spec, config: { ...this.spec.config, steps: formulas } };
    super.render();
  }
}

class CodeType extends BaseMotion {
  private code = "";
  private output = document.createElement("pre");
  render(): void {
    this.code = text(this.spec.config.code);
    this.output.style.margin = "0";
    this.output.style.whiteSpace = "pre-wrap";
    this.output.style.fontFamily = "var(--font-mono)";
    this.output.style.fontSize = "16px";
    this.host.appendChild(this.output);
  }
  seek(timeMs: number): void {
    const duration = this.duration();
    const progress = duration === 0 ? 1 : Math.min(1, Math.max(0, timeMs / duration));
    this.output.textContent = this.code.slice(0, Math.ceil(this.code.length * progress));
  }
}

class FlowParticles extends BaseMotion {
  private canvas = document.createElement("canvas");
  render(): void {
    this.canvas.width = 640;
    this.canvas.height = 320;
    this.canvas.style.width = "100%";
    this.canvas.style.height = "100%";
    this.host.appendChild(this.canvas);
  }
  seek(timeMs: number): void {
    const context = this.canvas.getContext("2d");
    if (!context) return;
    context.clearRect(0, 0, this.canvas.width, this.canvas.height);
    const count = Math.round((Number(this.spec.config.count) || 80) * this.level);
    context.fillStyle = String(this.spec.config.color ?? "#7A1F1F");
    for (let index = 0; index < count; index += 1) {
      const phase = timeMs / 900 + index * 0.37;
      const x = ((index * 97 + Math.cos(phase) * 60) % 620) + 10;
      const y = ((index * 53 + Math.sin(phase * 1.3) * 40) % 300) + 10;
      context.beginPath();
      context.arc(x, y, 2 + (index % 3), 0, Math.PI * 2);
      context.fill();
    }
  }
}

export function installMotionComponents(
  container: HTMLElement,
  specs: MotionSpec[],
  level: number,
  autoPlay = true,
): void {
  const classes: Record<
    string,
    new (host: HTMLElement, spec: MotionSpec, level: number) => MotionComponent
  > = {
    StepReveal,
    ChartReveal,
    FlowDiagram,
    FormulaStep,
    CodeType,
    FlowParticles,
  };
  const instances = specs.map((spec) => {
    const host = shell(document.createElement("div"), spec);
    container.appendChild(host);
    const Component = classes[spec.name] ?? StepReveal;
    const instance = new Component(host, spec, Math.max(0, Math.min(1, level)));
    instance.render();
    return instance;
  });
  const seek = (timeMs: number) => instances.forEach((instance) => instance.seek(timeMs));
  (window as unknown as { presentaMotion?: { seek: (timeMs: number) => void } }).presentaMotion = {
    seek,
  };
  if (autoPlay && instances.some((instance) => instance.duration() > 0)) {
    const started = performance.now();
    const tick = () => {
      seek((performance.now() - started) % 3000);
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }
}
