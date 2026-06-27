"use client";

interface Props {
  label: string;
  value: string;
  queryId: string;
  onOpen: (queryId: string) => void;
}

export function SourceChip({ label, value, queryId, onOpen }: Props) {
  return (
    <button
      type="button"
      onClick={() => onOpen(queryId)}
      className="inline-flex items-baseline gap-1 rounded-md border border-primary/30 bg-primary/5 px-1.5 py-0.5 font-mono text-[12px] font-semibold text-primary hover:bg-primary/10 transition-colors align-baseline"
      title={`From: ${label}`}
    >
      {value}
      <span className="text-[8px] opacity-70">◆</span>
    </button>
  );
}
