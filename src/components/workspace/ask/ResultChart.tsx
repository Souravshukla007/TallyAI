"use client";

interface DataPoint {
  label: string;
  value: number;
}

interface Props {
  data: DataPoint[];
  yLabel?: string;
}

export function ResultChart({ data, yLabel }: Props) {
  const max = Math.max(...data.map((d) => d.value));
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-end gap-3 h-56">
        {data.map((d) => {
          const h = (d.value / max) * 100;
          return (
            <div key={d.label} className="flex-1 flex flex-col items-center gap-2">
              <div className="w-full flex-1 flex items-end">
                <div
                  className="w-full rounded-t-md bg-gradient-to-t from-primary to-primary/70 transition-all hover:from-primary hover:to-primary"
                  style={{ height: `${h}%` }}
                />
              </div>
              <div className="text-[11px] text-muted-foreground text-center font-mono truncate w-full" title={d.label}>
                {d.label}
              </div>
            </div>
          );
        })}
      </div>
      {yLabel && (
        <div className="mt-3 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground text-center">
          {yLabel}
        </div>
      )}
    </div>
  );
}
