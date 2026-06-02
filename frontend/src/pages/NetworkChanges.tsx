import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Input from '../components/ui/Input'
import Spinner from '../components/ui/Spinner'
import { NetworkChangeEvent, inventoryApi } from '../api/inventory'
import { useI18n } from '../i18n'
import { formatDateTime, formatRelativeTime } from '../utils/formatters'

const EVENT_TYPES = [
  'device_discovered',
  'device_updated',
  'online_state_changed',
  'ip_changed',
  'hostname_changed',
  'device_archived',
  'device_unarchived',
  'maintenance_updated',
  'device_merged',
  'cmdb_id_generated',
]

function eventTone(eventType: string): 'success' | 'danger' | 'warning' | 'primary' | 'muted' {
  if (eventType === 'device_discovered' || eventType === 'device_unarchived') return 'success'
  if (eventType === 'device_archived') return 'danger'
  if (eventType === 'online_state_changed' || eventType === 'ip_changed') return 'warning'
  if (eventType === 'device_updated' || eventType === 'maintenance_updated') return 'primary'
  return 'muted'
}

function labelEvent(eventType: string) {
  return eventType.replace(/_/g, ' ')
}

function eventDetail(event: NetworkChangeEvent) {
  if (event.field_name) {
    return `${event.field_name}: ${event.old_value ?? '—'} -> ${event.new_value ?? '—'}`
  }
  return event.message || event.source
}

export default function NetworkChanges() {
  const { t, lang } = useI18n()
  const navigate = useNavigate()
  const [items, setItems] = useState<NetworkChangeEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [eventType, setEventType] = useState('')
  const [sinceHours, setSinceHours] = useState('168')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setDebouncedSearch(search.trim())
    }, 300)

    return () => window.clearTimeout(timeout)
  }, [search])

  const params = useMemo(() => ({
    event_type: eventType || undefined,
    since_hours: sinceHours ? Number(sinceHours) : undefined,
    search: debouncedSearch || undefined,
    limit: 200,
  }), [debouncedSearch, eventType, sinceHours])

  async function load() {
    setLoading(true)
    try {
      setItems(await inventoryApi.changes(params))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [params])

  const uniqueDevices = new Set(items.map((item) => item.device_id)).size

  return (
    <div className="max-w-6xl mx-auto flex flex-col gap-5">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h1 className="text-xl font-bold text-text-base">{t('network_changes')}</h1>
          <p className="mt-1 text-sm text-text-subtle">{t('network_changes_summary', { count: items.length, devices: uniqueDevices })}</p>
        </div>
        <Button variant="outline" size="sm" onClick={load}>{t('refresh')}</Button>
      </div>

      <div className="grid gap-3 rounded-lg border border-border bg-surface p-3 md:grid-cols-[1.4fr_1fr_1fr_auto]">
        <Input
          placeholder={t('search_changes')}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select
          value={eventType}
          onChange={(event) => setEventType(event.target.value)}
          className="h-10 rounded-lg border border-border bg-surface2 px-3 text-sm text-text-base outline-none focus:border-primary"
        >
          <option value="">{t('all_change_types')}</option>
          {EVENT_TYPES.map((type) => (
            <option key={type} value={type}>{labelEvent(type)}</option>
          ))}
        </select>
        <select
          value={sinceHours}
          onChange={(event) => setSinceHours(event.target.value)}
          className="h-10 rounded-lg border border-border bg-surface2 px-3 text-sm text-text-base outline-none focus:border-primary"
        >
          <option value="24">{t('last_24_hours')}</option>
          <option value="168">{t('last_7_days')}</option>
          <option value="720">{t('last_30_days')}</option>
          <option value="">{t('all_time')}</option>
        </select>
        <Button variant="ghost" size="sm" onClick={() => { setSearch(''); setEventType(''); setSinceHours('168') }}>{t('reset_filters')}</Button>
      </div>

      {loading ? (
        <div className="flex justify-center py-14"><Spinner /></div>
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-border bg-surface py-14 text-center text-sm text-text-subtle">
          {t('no_changes_recorded')}
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-border bg-surface">
          <div className="grid grid-cols-[minmax(180px,1fr)_minmax(150px,1fr)_minmax(220px,1.6fr)_140px] gap-3 border-b border-border px-4 py-2 text-xs uppercase text-text-subtle">
            <span>{t('col_device')}</span>
            <span>{t('change_type')}</span>
            <span>{t('details')}</span>
            <span>{t('time')}</span>
          </div>
          <div className="divide-y divide-border">
            {items.map((item) => (
              <button
                key={item.id}
                onClick={() => navigate(`/devices/${item.device_id}`)}
                className="grid w-full grid-cols-1 gap-2 px-4 py-3 text-left transition-colors hover:bg-surface2 md:grid-cols-[minmax(180px,1fr)_minmax(150px,1fr)_minmax(220px,1.6fr)_140px] md:items-center md:gap-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-text-base">{item.device_label}</p>
                  <p className="truncate text-xs text-text-subtle">{item.device_ip || item.device_mac || item.device_class || '—'}</p>
                </div>
                <div>
                  <Badge variant={eventTone(item.event_type)}>{labelEvent(item.event_type)}</Badge>
                  <p className="mt-1 text-xs text-text-subtle">{item.source}</p>
                </div>
                <p className="min-w-0 truncate text-sm text-text-muted">{eventDetail(item)}</p>
                <div className="text-xs text-text-subtle" title={formatDateTime(item.created_at)}>
                  {formatRelativeTime(item.created_at, lang)}
                </div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
