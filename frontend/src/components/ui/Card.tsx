interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode
  className?: string
  onClick?: () => void
  hoverable?: boolean
}

export default function Card({ children, className = '', onClick, hoverable, ...props }: CardProps) {
  return (
    <div
      onClick={onClick}
      {...props}
      className={`bg-surface border border-border rounded-xl p-4
        ${hoverable ? 'cursor-pointer hover:border-primary/50 hover:bg-surface2 transition-colors' : ''}
        ${className}`}
    >
      {children}
    </div>
  )
}
