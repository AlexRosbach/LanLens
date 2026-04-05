import { NavLink, useNavigate } from 'react-router-dom'
import { useDeviceStore } from '../../store/deviceStore'
import { useNotificationStore } from '../../store/notificationStore'
import { useI18n } from '../../i18n'
import { APP_VERSION, GITHUB_REPO } from '../../version'
import { dismissUpdate, useUpdateCheck } from '../../hooks/useUpdateCheck'

interface Props {
  onClose?: () => void
}

export default function Sidebar({ onClose }: Props) {
  const { stats } = useDeviceStore()
  const { unreadCount } = useNotificationStore()
  const { t } = useI18n()
  const update = useUpdateCheck()
  const navigate = useNavigate()

  function handleNavClick() {
    onClose?.()
  }

  const navItems = [
    {
      to: '/',
      label: t('nav_dashboard'),
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
            d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
        </svg>
      ),
    },
    {
      to: '/notifications',
      label: t('nav_notifications'),
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
        </svg>
      ),
      badge: unreadCount,
    },
    {
      to: '/segments',
      label: t('nav_segments'),
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
            d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>
      ),
    },
    {
      to: '/settings',
      label: t('nav_settings'),
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
            d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      ),
    },
  ]

  return (
    <aside className="w-56 bg-surface border-r border-border flex flex-col h-full">
      {/* Logo — click navigates to home */}
      <div className="flex items-center gap-3 px-5 py-5 border-b border-border">
        <button
          onClick={() => { navigate('/'); handleNavClick() }}
          className="flex items-center gap-3 hover:opacity-80 transition-opacity"
        >
          <img src="/logo.svg" alt="LanLens" className="w-8 h-8" />
          <span className="text-lg font-bold text-text-base tracking-tight">LanLens</span>
        </button>
        {/* Close button on mobile */}
        {onClose && (
          <button onClick={onClose} className="ml-auto text-text-subtle hover:text-text-base transition-colors md:hidden">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
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
            onClick={handleNavClick}
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
            {item.badge != null && item.badge > 0 && (
              <span className="ml-auto text-xs bg-warning text-background font-bold px-1.5 py-0.5 rounded-full">
                {item.badge}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Version + update notification */}
      <div className="px-4 py-4 border-t border-border flex flex-col gap-2">
        {update ? (
          <div className="bg-warning/10 border border-warning/30 rounded-lg px-3 py-2.5 flex flex-col gap-1.5">
            <div className="flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 text-warning flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
              </svg>
              <span className="text-xs font-semibold text-warning">Update available</span>
            </div>
            <p className="text-xs text-text-subtle">v{update.latestVersion} is out</p>
            <div className="flex items-center gap-2 mt-0.5">
              <a
                href={update.releaseUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-warning hover:text-warning/80 font-medium transition-colors"
              >
                View release →
              </a>
              <button
                onClick={() => dismissUpdate(update.latestVersion)}
                className="text-xs text-text-subtle hover:text-text-muted transition-colors ml-auto"
              >
                Dismiss
              </button>
            </div>
          </div>
        ) : null}
        <p className="text-xs text-text-subtle">
          LanLens{' '}
          <a
            href={`https://github.com/${GITHUB_REPO}/releases/tag/v${APP_VERSION}`}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-text-muted transition-colors"
          >
            v{APP_VERSION}
          </a>
        </p>
      </div>
    </aside>
  )
}
