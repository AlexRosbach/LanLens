import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/layout/Layout'
import Dashboard from './pages/Dashboard'
import DeviceDetail from './pages/DeviceDetail'
import ForcePasswordChange from './pages/ForcePasswordChange'
import Login from './pages/Login'
import Notifications from './pages/Notifications'
import Settings from './pages/Settings'
import { useAuthStore } from './store/authStore'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { token, user } = useAuthStore()

  if (!token) return <Navigate to="/login" replace />
  if (user?.force_password_change) return <Navigate to="/change-password" replace />

  return <>{children}</>
}

function AuthRoute({ children }: { children: React.ReactNode }) {
  const { token, user } = useAuthStore()

  if (token && user?.force_password_change) return <Navigate to="/change-password" replace />
  if (token) return <Navigate to="/" replace />

  return <>{children}</>
}

function PasswordChangeRoute({ children }: { children: React.ReactNode }) {
  const { token } = useAuthStore()
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  const { loadFromStorage } = useAuthStore()

  useEffect(() => {
    loadFromStorage()
  }, [loadFromStorage])

  return (
    <BrowserRouter>
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
          <Route path="settings" element={<Settings />} />
          <Route path="notifications" element={<Notifications />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
