interface CardProps {
  children: React.ReactNode
  className?: string
  onClick?: () => void
  hoverable?: boolean
}

export default function Card({ children, className = '', onClick, hoverable }: CardProps) {
  return (
    <div
      onClick={onClick}
      className={`bg-surface border border-border rounded-xl p-4
        ${hoverable ? 'cursor-pointer hover:border-primary/50 hover:bg-surface2 transition-colors' : ''}
        ${className}`}
    >
      {children}
    </div>
  )
}
