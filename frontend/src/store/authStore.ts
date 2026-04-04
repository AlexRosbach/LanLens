import { create } from 'zustand'
import { authApi, UserResponse } from '../api/auth'

interface AuthState {
  token: string | null
  user: UserResponse | null
  loadFromStorage: () => void
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  refreshUser: () => Promise<void>
  setForcePasswordChangeDone: () => void
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: null,
  user: null,

  loadFromStorage: () => {
    const token = localStorage.getItem('lanlens_token')
    const userStr = localStorage.getItem('lanlens_user')
    if (token && userStr) {
      try {
        set({ token, user: JSON.parse(userStr) })
      } catch {
        localStorage.removeItem('lanlens_token')
        localStorage.removeItem('lanlens_user')
      }
    }
  },

  login: async (username, password) => {
    const tokenData = await authApi.login({ username, password })
    localStorage.setItem('lanlens_token', tokenData.access_token)
    const user = await authApi.me()
    localStorage.setItem('lanlens_user', JSON.stringify(user))
    set({ token: tokenData.access_token, user })
  },

  logout: () => {
    localStorage.removeItem('lanlens_token')
    localStorage.removeItem('lanlens_user')
    set({ token: null, user: null })
  },

  refreshUser: async () => {
    const user = await authApi.me()
    localStorage.setItem('lanlens_user', JSON.stringify(user))
    set({ user })
  },

  setForcePasswordChangeDone: () => {
    set((state) => {
      if (!state.user) return {}
      const updated = { ...state.user, force_password_change: false }
      localStorage.setItem('lanlens_user', JSON.stringify(updated))
      return { user: updated }
    })
  },
}))
