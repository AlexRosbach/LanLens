import { create } from 'zustand'
import { notificationsApi } from '../api/notifications'

interface NotificationState {
  unreadCount: number
  fetchUnreadCount: () => Promise<void>
  markAllRead: () => void
  decrementUnread: (by?: number) => void
}

export const useNotificationStore = create<NotificationState>((set) => ({
  unreadCount: 0,

  fetchUnreadCount: async () => {
    try {
      const { count } = await notificationsApi.unreadCount()
      set({ unreadCount: count })
    } catch {
      // fail silently
    }
  },

  markAllRead: () => set({ unreadCount: 0 }),

  decrementUnread: (by = 1) =>
    set((s) => ({ unreadCount: Math.max(0, s.unreadCount - by) })),
}))
