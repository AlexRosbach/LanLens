import { InputHTMLAttributes, forwardRef } from 'react'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  hint?: string
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, className = '', ...props }, ref) => (
    <div className="flex flex-col gap-1">
      {label && (
        <label className="text-sm font-medium text-text-muted">{label}</label>
      )}
      <input
        ref={ref}
        className={`input-field ${error ? 'border-danger focus:border-danger focus:ring-danger' : ''} ${className}`}
        {...props}
      />
      {error && <p className="text-xs text-danger">{error}</p>}
      {hint && !error && <p className="text-xs text-text-subtle">{hint}</p>}
    </div>
  ),
)
Input.displayName = 'Input'
export default Input
