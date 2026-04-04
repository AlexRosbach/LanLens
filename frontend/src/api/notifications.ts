import apiClient from './client'

export interface NotificationItem {
  id: number
  device_id: number | null
  event_type: string
  message: string
  is_read: boolean
  telegram_sent: boolean
  created_at: string
}

export const notificationsApi = {
  list: (unread_only?: boolean) =>
    apiClient.get<NotificationItem[]>('/notifications', { params: { unread_only } }).then((r) => r.data),

  unreadCount: () =>
    apiClient.get<{ count: number }>('/notifications/unread-count').then((r) => r.data),

  markAllRead: () => apiClient.put('/notifications/read-all').then((r) => r.data),

  delete: (id: number) => apiClient.delete(`/notifications/${id}`),
}
