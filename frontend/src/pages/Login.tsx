import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { useAuthStore } from '../store/authStore'
import Button from '../components/ui/Button'
import Input from '../components/ui/Input'
import { withBasePath } from '../utils/basePath'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const { login } = useAuthStore()
  const navigate = useNavigate()

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!username || !password) { toast.error('Please enter credentials'); return }
    setLoading(true)
    try {
      await login(username, password)
      navigate('/')
    } catch (err: any) {
      const msg = err?.response?.data?.detail ?? 'Login failed'
      toast.error(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      {/* Subtle background pattern */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] opacity-5">
          <svg viewBox="0 0 200 200" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="100" cy="100" r="95" stroke="#6366f1" strokeWidth="0.5"/>
            <circle cx="100" cy="100" r="70" stroke="#6366f1" strokeWidth="0.5"/>
            <circle cx="100" cy="100" r="45" stroke="#6366f1" strokeWidth="0.5"/>
            <circle cx="100" cy="100" r="20" stroke="#6366f1" strokeWidth="0.5"/>
            <line x1="100" y1="5" x2="100" y2="195" stroke="#6366f1" strokeWidth="0.3"/>
            <line x1="5" y1="100" x2="195" y2="100" stroke="#6366f1" strokeWidth="0.3"/>
          </svg>
        </div>
      </div>

      <div className="w-full max-w-sm relative">
        {/* Logo + title */}
        <div className="flex flex-col items-center mb-8">
          <img src={withBasePath('/logo.svg')} alt="LanLens" className="w-16 h-16 mb-4" />
          <h1 className="text-2xl font-bold text-text-base tracking-tight">LanLens</h1>
          <p className="text-sm text-text-muted mt-1">Network Monitoring Dashboard</p>
        </div>

        {/* Login form */}
        <div className="bg-surface border border-border rounded-2xl p-6 shadow-2xl">
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <Input
              label="Username"
              type="text"
              placeholder="admin"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
            />
            <Input
              label="Password"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
            <Button type="submit" loading={loading} className="w-full justify-center mt-1">
              Sign In
            </Button>
          </form>
        </div>

        <p className="text-center text-xs text-text-subtle mt-4">
          Default credentials: <span className="font-mono text-text-muted">admin / admin</span>
        </p>
      </div>
    </div>
  )
}
