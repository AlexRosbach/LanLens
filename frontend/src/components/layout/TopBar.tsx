import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { scanApi } from '../../api/scan'
import { useAuthStore } from '../../store/authStore'
import { useDeviceStore } from '../../store/deviceStore'
import Button from '../ui/Button'

export default function TopBar() {
  const [scanning, setScanning] = useState(false)
  const [showUserMenu, setShowUserMenu] = useState(false)
  const { user, logout } = useAuthStore()
  const { fetchDevices, stats } = useDeviceStore()
  const navigate = useNavigate()

  async function handleScan() {
    setScanning(true)
    try {
      await scanApi.start()
      toast.success('Network scan started')
      // Poll for completion
      const poll = setInterval(async () => {
        const status = await scanApi.status()
        if (!status.is_running) {
          clearInterval(poll)
          setScanning(false)
          await fetchDevices()
          toast.success(`Scan complete — ${status.last_scan?.devices_found ?? 0} devices found`)
        }
      }, 2000)
    } catch {
      toast.error('Failed to start scan')
      setScanning(false)
    }
  }

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <header className="h-14 bg-surface border-b border-border flex items-center justify-between px-6 sticky top-0 z-10">
      <div className="flex items-center gap-4">
        <h1 className="text-sm font-medium text-text-muted">
          <span className="text-success font-mono">{stats.online}</span>
          <span className="text-text-subtle mx-1">/</span>
          <span className="font-mono">{stats.total}</span>
          <span className="ml-2">devices online</span>
        </h1>
        {stats.unregistered > 0 && (
          <span className="badge-new">{stats.unregistered} new</span>
        )}
      </div>

      <div className="flex items-center gap-3">
        <Button
          variant="primary"
          size="sm"
          loading={scanning}
          onClick={handleScan}
        >
          {scanning ? 'Scanning…' : (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              Scan Now
            </>
          )}
        </Button>

        {/* User menu */}
        <div className="relative">
          <button
            onClick={() => setShowUserMenu(!showUserMenu)}
            className="flex items-center gap-2 text-sm text-text-muted hover:text-text-base px-3 py-1.5 rounded-lg hover:bg-surface2 transition-colors"
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
                  Settings
                </button>
                <div className="border-t border-border" />
                <button
                  onClick={handleLogout}
                  className="w-full text-left px-4 py-2.5 text-sm text-danger hover:bg-surface transition-colors"
                >
                  Sign out
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  )
}
