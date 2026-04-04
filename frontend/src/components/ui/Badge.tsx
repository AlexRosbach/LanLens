interface BadgeProps {
  variant?: 'success' | 'danger' | 'warning' | 'primary' | 'muted'
  children: React.ReactNode
  dot?: boolean
}

const styles = {
  success: 'bg-success-dim text-success',
  danger: 'bg-danger-dim text-danger',
  warning: 'bg-warning-dim text-warning',
  primary: 'bg-primary-dim text-primary',
  muted: 'bg-surface2 text-text-muted',
}

const dotStyles = {
  success: 'bg-success',
  danger: 'bg-danger',
  warning: 'bg-warning',
  primary: 'bg-primary',
  muted: 'bg-text-muted',
}

export default function Badge({ variant = 'muted', children, dot }: BadgeProps) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${styles[variant]}`}>
      {dot && <span className={`w-1.5 h-1.5 rounded-full ${dotStyles[variant]}`} />}
      {children}
    </span>
  )
}
