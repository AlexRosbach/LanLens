import { NavLink } from 'react-router-dom'
import { useDeviceStore } from '../../store/deviceStore'

const navItems = [
  {
    to: '/',
    label: 'Dashboard',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
          d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
      </svg>
    ),
  },
  {
    to: '/notifications',
    label: 'Notifications',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
          d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
      </svg>
    ),
  },
  {
    to: '/settings',
    label: 'Settings',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
          d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
    ),
  },
]

export default function Sidebar() {
  const { stats } = useDeviceStore()

  return (
    <aside className="w-56 bg-surface border-r border-border flex flex-col h-screen sticky top-0">
      {/* Logo */}
      <div className="flex items-center gap-3 px-5 py-5 border-b border-border">
        <img src="/logo.svg" alt="LanLens" className="w-8 h-8" />
        <span className="text-lg font-bold text-text-base tracking-tight">LanLens</span>
      </div>

      {/* Network summary */}
      <div className="px-4 py-3 border-b border-border">
        <div className="flex justify-between text-xs text-text-subtle mb-1">
          <span>Network</span>
          <span className="text-text-muted">{stats.online}/{stats.total}</span>
        </div>
        <div className="h-1.5 bg-surface2 rounded-full overflow-hidden">
          <div
            className="h-full bg-success rounded-full transition-all"
            style={{ width: stats.total ? `${(stats.online / stats.total) * 100}%` : '0%' }}
          />
        </div>
        <div className="flex justify-between text-xs mt-1.5">
          <span className="text-success">{stats.online} online</span>
          <span className="text-danger">{stats.offline} offline</span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-3 flex flex-col gap-1">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors
              ${isActive
                ? 'bg-primary-dim text-primary'
                : 'text-text-muted hover:text-text-base hover:bg-surface2'
              }`
            }
          >
            {item.icon}
            {item.label}
            {item.to === '/notifications' && stats.unregistered > 0 && (
              <span className="ml-auto text-xs bg-warning text-background font-bold px-1.5 py-0.5 rounded-full">
                {stats.unregistered}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Version */}
      <div className="px-5 py-4 border-t border-border">
        <p className="text-xs text-text-subtle">LanLens v1.0.0</p>
      </div>
    </aside>
  )
}
