import { create } from 'zustand'
import { authApi, UserResponse } from '../api/auth'

interface AuthState {
  user: UserResponse | null
  initialized: boolean
  authenticated: boolean
  loadSession: () => Promise<void>
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
  setForcePasswordChangeDone: () => void
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  initialized: false,
  authenticated: false,

  loadSession: async () => {
    try {
      const user = await authApi.me()
      set({ user, authenticated: true, initialized: true })
    } catch {
      set({ user: null, authenticated: false, initialized: true })
    }
  },

  login: async (username, password) => {
    await authApi.login({ username, password })
    const user = await authApi.me()
    set({ user, authenticated: true, initialized: true })
  },

  logout: async () => {
    try {
      await authApi.logout()
    } catch {
      // best effort
    }
    set({ user: null, authenticated: false, initialized: true })
  },

  refreshUser: async () => {
    const user = await authApi.me()
    set({ user, authenticated: true })
  },

  setForcePasswordChangeDone: () => {
    const state = get()
    if (!state.user) return
    set({ user: { ...state.user, force_password_change: false } })
  },
}))
