import apiClient from './client'

export interface NotificationItem {
  id: number
  device_id: number | null
  device_path?: string | null
  device_url?: string | null
  event_type: string
  message: string
  is_read: boolean
  telegram_sent: boolean
  webhook_sent: boolean
  smtp_sent: boolean
  created_at: string
}

export const notificationsApi = {
  list: (unread_only?: boolean) =>
    apiClient.get<NotificationItem[]>('/notifications', { params: { unread_only } }).then((r) => r.data),

  unreadCount: () =>
    apiClient.get<{ count: number }>('/notifications/unread-count').then((r) => r.data),

  markAllRead: () => apiClient.put('/notifications/read-all').then((r) => r.data),

  deleteAll: () => apiClient.delete('/notifications').then((r) => r.data),

  delete: (id: number) => apiClient.delete(`/notifications/${id}`),
}
