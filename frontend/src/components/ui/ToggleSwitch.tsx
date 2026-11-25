export default function ToggleSwitch({
  checked,
  disabled = false,
  onChange,
  label,
  description,
}: {
  checked: boolean
  disabled?: boolean
  onChange: (checked: boolean) => void
  label: string
  description: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`flex w-full items-center justify-between gap-4 rounded-lg border px-4 py-3 text-left transition-colors ${
        checked ? 'border-primary/40 bg-primary-dim/20' : 'border-border bg-surface2/40'
      } ${disabled ? 'cursor-not-allowed opacity-50' : 'hover:border-primary/50'}`}
    >
      <span>
        <span className="block text-sm font-medium text-text-base">{label}</span>
        <span className="mt-1 block text-xs text-text-subtle">{description}</span>
      </span>
      <span className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${checked ? 'bg-primary' : 'bg-border'}`}>
        <span className={`absolute left-0 top-1 h-4 w-4 rounded-full bg-white transition-transform ${checked ? 'translate-x-6' : 'translate-x-1'}`} />
      </span>
    </button>
  )
}
