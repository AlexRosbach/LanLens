interface SpinnerProps { size?: 'sm' | 'md' | 'lg'; className?: string }

const sizes = { sm: 'w-4 h-4', md: 'w-6 h-6', lg: 'w-8 h-8' }

export default function Spinner({ size = 'md', className = '' }: SpinnerProps) {
  return (
    <svg
      className={`animate-spin text-primary ${sizes[size]} ${className}`}
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
    </svg>
  )
}
