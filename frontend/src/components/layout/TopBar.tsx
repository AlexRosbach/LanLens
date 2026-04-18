import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { scanApi } from '../../api/scan'
import { useAuthStore } from '../../store/authStore'
import { useDeviceStore } from '../../store/deviceStore'
import { useI18n } from '../../i18n'
import Button from '../ui/Button'

type Theme = 'dark' | 'light'

function getInitialTheme(): Theme {
  return 'dark'
}

function applyTheme(theme: Theme) {
  if (theme === 'light') {
    document.documentElement.classList.add('light')
  } else {
    document.documentElement.classList.remove('light')
  }
}

const languageOptions = {
  en: { label: 'English', flag: '🇬🇧' },
  de: { label: 'Deutsch', flag: '🇩🇪' },
  it: { label: 'Italiano', flag: '🇮🇹' },
} as const

export default function TopBar({ onMenuToggle }: { onMenuToggle?: () => void }) {
  const [scanning, setScanning] = useState(false)
  const [showUserMenu, setShowUserMenu] = useState(false)
  const [showLanguageMenu, setShowLanguageMenu] = useState(false)
  const [theme, setTheme] = useState<Theme>(getInitialTheme)
  const languageMenuRef = useRef<HTMLDivElement | null>(null)
  const { user, logout } = useAuthStore()
  const { fetchDevices, stats, devices } = useDeviceStore()
  const { lang, setLang, t } = useI18n()
  const navigate = useNavigate()

  const newCount = devices.filter((d) => d.is_new).length

  // Apply saved theme on mount
  useEffect(() => { applyTheme(theme) }, [theme])

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (!languageMenuRef.current?.contains(event.target as Node)) {
        setShowLanguageMenu(false)
      }
    }

    if (showLanguageMenu) {
      document.addEventListener('mousedown', handleClickOutside)
    }

    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showLanguageMenu])

  function toggleTheme() {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    applyTheme(next)
  }

  async function handleScan() {
    setScanning(true)
    try {
      await scanApi.start()
      toast.success(t('network_scan_started'))
      const poll = setInterval(async () => {
        const status = await scanApi.status()
        if (!status.is_running) {
          clearInterval(poll)
          setScanning(false)
          await fetchDevices()
          toast.success(
            t('scan_complete', { count: status.last_scan?.devices_found ?? 0 })
          )
        }
      }, 2000)
    } catch {
      toast.error(t('failed_start_scan'))
      setScanning(false)
    }
  }

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  return (
    <header className="h-14 bg-surface border-b border-border flex items-center justify-between px-4 sm:px-6 sticky top-0 z-10">
      {/* Left: hamburger (mobile) + stats */}
      <div className="flex items-center gap-3">
        {/* Mobile menu button */}
        <button
          onClick={onMenuToggle}
          className="md:hidden text-text-subtle hover:text-text-base p-1.5 rounded-lg hover:bg-surface2 transition-colors"
          aria-label="Open menu"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <h1 className="text-sm font-medium text-text-muted hidden sm:block">
          <span className="text-success font-mono">{stats.online}</span>
          <span className="text-text-subtle mx-1">/</span>
          <span className="font-mono">{stats.total}</span>
          <span className="ml-2">{t('devices_online')}</span>
        </h1>
        {newCount > 0 && (
          <span className="badge-new hidden sm:inline-flex">{newCount} {t('filter_new').toLowerCase()}</span>
        )}
      </div>

      <div className="flex items-center gap-2">
        <div className="relative" ref={languageMenuRef}>
          <button
            onClick={() => setShowLanguageMenu((open) => !open)}
            className="flex items-center gap-1.5 text-xs font-medium text-text-subtle hover:text-text-base px-2 py-1.5 rounded-lg hover:bg-surface2 transition-colors border border-border"
            title={t('switch_language')}
          >
            <span>{languageOptions[lang].flag}</span>
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {showLanguageMenu && (
            <div className="absolute right-0 top-10 bg-surface2 border border-border rounded-xl shadow-xl min-w-[140px] z-20 overflow-hidden animate-fade-in">
              {Object.entries(languageOptions).map(([code, option]) => (
                <button
                  key={code}
                  onClick={() => {
                    setLang(code as 'en' | 'de' | 'it')
                    setShowLanguageMenu(false)
                  }}
                  className={`w-full flex items-center gap-2 px-3 py-2 text-sm transition-colors ${lang === code ? 'bg-surface text-text-base' : 'text-text-muted hover:text-text-base hover:bg-surface'}`}
                >
                  <span>{option.flag}</span>
                  <span>{option.label}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Theme toggle */}
        <button
          onClick={toggleTheme}
          className="text-text-subtle hover:text-text-base p-2 rounded-lg hover:bg-surface2 transition-colors"
          title={theme === 'dark' ? t('switch_to_light_mode') : t('switch_to_dark_mode')}
        >
          {theme === 'dark' ? (
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
            </svg>
          ) : (
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
            </svg>
          )}
        </button>

        {/* Scan button */}
        <Button variant="primary" size="sm" loading={scanning} onClick={handleScan}>
          {scanning ? t('scanning') : (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <span className="hidden sm:inline">{t('scan_now')}</span>
            </>
          )}
        </Button>

        {/* User menu */}
        <div className="relative">
          <button
            onClick={() => setShowUserMenu(!showUserMenu)}
            className="flex items-center gap-2 text-sm text-text-muted hover:text-text-base px-2 py-1.5 rounded-lg hover:bg-surface2 transition-colors"
          >
            <div className="w-7 h-7 rounded-full bg-primary-dim border border-primary/30 flex items-center justify-center text-primary text-xs font-bold">
              {user?.username?.[0]?.toUpperCase() ?? 'A'}
            </div>
            <span className="hidden sm:block">{user?.username}</span>
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {showUserMenu && (
            <>
              <div className="fixed inset-0" onClick={() => setShowUserMenu(false)} />
              <div className="absolute right-0 top-10 bg-surface2 border border-border rounded-xl shadow-xl w-44 z-20 overflow-hidden animate-fade-in">
                <button
                  onClick={() => { navigate('/settings'); setShowUserMenu(false) }}
                  className="w-full text-left px-4 py-2.5 text-sm text-text-muted hover:text-text-base hover:bg-surface transition-colors"
                >
                  {t('settings')}
                </button>
                <div className="border-t border-border" />
                <button
                  onClick={handleLogout}
                  className="w-full text-left px-4 py-2.5 text-sm text-danger hover:bg-surface transition-colors"
                >
                  {t('sign_out')}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  )
}
