import type { ParamDef } from "../types";

export function ParamForm({
  defs,
  values,
  onChange,
  disabled,
}: {
  defs: ParamDef[];
  values: Record<string, number | boolean>;
  onChange: (v: Record<string, number | boolean>) => void;
  disabled?: boolean;
}) {
  return (
    <div className="grid-form">
      {defs.map((p) => {
        const v = values[p.key] ?? p.default;
        if (p.type === "bool") {
          return (
            <label key={p.key} className="check">
              <input
                type="checkbox"
                checked={Boolean(v)}
                disabled={disabled}
                onChange={(e) => onChange({ ...values, [p.key]: e.target.checked })}
              />
              {p.label}
            </label>
          );
        }
        return (
          <label key={p.key} className="field">
            <span className="field-label">{p.label}</span>
            <input
              type="number"
              value={String(v)}
              min={p.min ?? undefined}
              max={p.max ?? undefined}
              step={p.step ?? (p.type === "int" ? 1 : "any")}
              disabled={disabled}
              onChange={(e) => {
                const n = p.type === "int" ? parseInt(e.target.value, 10) : parseFloat(e.target.value);
                onChange({ ...values, [p.key]: Number.isNaN(n) ? (e.target.value as unknown as number) : n });
              }}
            />
          </label>
        );
      })}
    </div>
  );
}

export function defaultsOf(defs: ParamDef[]): Record<string, number | boolean> {
  return Object.fromEntries(defs.map((d) => [d.key, d.default]));
}
