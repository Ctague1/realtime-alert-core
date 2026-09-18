export interface PillOption {
  value: string;
  label: string;
}

interface Props {
  options: PillOption[];
  value: string;
  onChange: (value: string) => void;
  ariaLabel?: string;
}

export function PillFilter({ options, value, onChange, ariaLabel }: Props) {
  return (
    <div className="pill-filters" role="group" aria-label={ariaLabel}>
      {options.map((opt) => (
        <button
          key={opt.value}
          className={`pill ${opt.value === value ? "active" : ""}`}
          onClick={() => onChange(opt.value)}
          aria-pressed={opt.value === value}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}