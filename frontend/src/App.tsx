import { type ReactNode, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { getBasePath } from './utils/basePath'
import Layout from './components/layout/Layout'
import Dashboard from './pages/Dashboard'
import DeviceDetail from './pages/DeviceDetail'
import ForcePasswordChange from './pages/ForcePasswordChange'
import Login from './pages/Login'
import Notifications from './pages/Notifications'
import DeepScanSettings from './pages/DeepScanSettings'
import Segments from './pages/Segments'
import Settings from './pages/Settings'
import { useAuthStore } from './store/authStore'
import { useNotificationStore } from './store/notificationStore'
import { I18nProvider } from './i18n'

function AuthGate({ children }: { children: ReactNode }) {
  const { initialized } = useAuthStore()
  if (!initialized) {
    return <div className="min-h-screen bg-background flex items-center justify-center text-text-muted">Loading…</div>
  }
  return <>{children}</>
}

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { authenticated, user } = useAuthStore()

  if (!authenticated) return <Navigate to="/login" replace />
  if (user?.force_password_change) return <Navigate to="/change-password" replace />

  return <>{children}</>
}

function AuthRoute({ children }: { children: ReactNode }) {
  const { authenticated, user } = useAuthStore()

  if (authenticated && user?.force_password_change) return <Navigate to="/change-password" replace />
  if (authenticated) return <Navigate to="/" replace />

  return <>{children}</>
}

function PasswordChangeRoute({ children }: { children: ReactNode }) {
  const { authenticated } = useAuthStore()
  if (!authenticated) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  const { loadSession, authenticated } = useAuthStore()
  const { fetchUnreadCount } = useNotificationStore()

  useEffect(() => {
    loadSession()
  }, [loadSession])

  useEffect(() => {
    if (authenticated) {
      fetchUnreadCount()
      const interval = setInterval(fetchUnreadCount, 60_000)
      return () => clearInterval(interval)
    }
  }, [authenticated, fetchUnreadCount])

  return (
    <I18nProvider>
      <AuthGate>
        <BrowserRouter basename={getBasePath() || undefined}>
          <Routes>
            <Route
              path="/login"
              element={
                <AuthRoute>
                  <Login />
                </AuthRoute>
              }
            />
            <Route
              path="/change-password"
              element={
                <PasswordChangeRoute>
                  <ForcePasswordChange />
                </PasswordChangeRoute>
              }
            />
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <Layout />
                </ProtectedRoute>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path="devices/:id" element={<DeviceDetail />} />
              <Route path="segments" element={<Segments />} />
              <Route path="settings" element={<Settings />} />
              <Route path="deep-scan-settings" element={<DeepScanSettings />} />
              <Route path="notifications" element={<Notifications />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthGate>
    </I18nProvider>
  )
}
