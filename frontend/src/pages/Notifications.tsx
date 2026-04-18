import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { NotificationItem, notificationsApi } from '../api/notifications'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Spinner from '../components/ui/Spinner'
import { useNotificationStore } from '../store/notificationStore'
import { useI18n } from '../i18n'
import { formatRelativeTime } from '../utils/formatters'

export default function Notifications() {
  const { t, lang } = useI18n()
  const { fetchUnreadCount, markAllRead: storeMarkAllRead, decrementUnread } = useNotificationStore()
  const [items, setItems] = useState<NotificationItem[]>([])
  const [loading, setLoading] = useState(true)

  const eventLabels: Record<string, { label: string; variant: 'warning' | 'success' | 'danger' | 'muted' }> = {
    new_device: { label: t('event_new_device'), variant: 'warning' },
    device_online: { label: t('event_online'), variant: 'success' },
    device_offline: { label: t('event_offline'), variant: 'danger' },
  }

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    try { setItems(await notificationsApi.list()) }
    finally { setLoading(false) }
  }

  async function markAllRead() {
    await notificationsApi.markAllRead()
    setItems((prev) => prev.map((n) => ({ ...n, is_read: true })))
    storeMarkAllRead()
    toast.success(t('all_marked_read'))
  }

  async function deleteNotification(id: number, wasUnread: boolean) {
    await notificationsApi.delete(id)
    setItems((prev) => prev.filter((n) => n.id !== id))
    if (wasUnread) decrementUnread()
  }

  const unread = items.filter((n) => !n.is_read).length

  return (
    <div className="max-w-2xl mx-auto flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-text-base">
          {t('notifications')}
          {unread > 0 && (
            <span className="ml-2 text-sm font-normal text-warning">({unread} {t('unread')})</span>
          )}
        </h1>
        {unread > 0 && (
          <Button variant="ghost" size="sm" onClick={markAllRead}>{t('mark_all_read')}</Button>
        )}
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Spinner /></div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-text-subtle">
          <svg className="w-10 h-10 mb-3 opacity-40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.4}
              d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
          </svg>
          <p className="text-sm">{t('no_notifications')}</p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {items.map((item) => {
            const meta = eventLabels[item.event_type] ?? { label: item.event_type, variant: 'muted' as const }
            return (
              <div key={item.id}
                className={`flex items-start gap-3 p-4 rounded-xl border transition-colors
                  ${item.is_read ? 'bg-surface border-border' : 'bg-surface border-primary/30'}`}>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge variant={meta.variant}>{meta.label}</Badge>
                    {!item.is_read && <span className="w-2 h-2 rounded-full bg-primary flex-shrink-0" />}
                    {item.telegram_sent && (
                      <span className="text-xs text-text-subtle">Telegram ✓</span>
                    )}
                  </div>
                  <p className="text-sm text-text-muted leading-relaxed">{item.message}</p>
                  <p className="text-xs text-text-subtle mt-1">{formatRelativeTime(item.created_at, lang)}</p>
                </div>
                <button onClick={() => deleteNotification(item.id, !item.is_read)}
                  className="text-text-subtle hover:text-danger transition-colors p-1 flex-shrink-0">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
