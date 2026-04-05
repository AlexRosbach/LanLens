import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { Device } from '../api/devices'
import { Segment, segmentsApi } from '../api/segments'
import RegisterDeviceModal from '../components/devices/RegisterDeviceModal'
import DeviceTable from '../components/devices/DeviceTable'
import Spinner from '../components/ui/Spinner'
import Card from '../components/ui/Card'
import { useDeviceStore } from '../store/deviceStore'
import { useI18n } from '../i18n'
import { DEVICE_CLASSES } from '../components/devices/DeviceClassIcon'

type Filter = 'all' | 'online' | 'offline' | 'new'

export default function Dashboard() {
  const { devices, stats, loading, fetchDevices, updateDevice } = useDeviceStore()
  const { t } = useI18n()
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')
  const [classFilter, setClassFilter] = useState('')
  const [segmentFilter, setSegmentFilter] = useState('')
  const [registerDevice, setRegisterDevice] = useState<Device | null>(null)
  const [segments, setSegments] = useState<Segment[]>([])

  useEffect(() => {
    fetchDevices()
    segmentsApi.list().then(setSegments).catch(() => {})
  }, [fetchDevices])

  const filterLabels: Record<Filter, string> = {
    all: t('filter_all'),
    online: t('filter_online'),
    offline: t('filter_offline'),
    new: t('filter_new'),
  }

  const filtered = devices.filter((d) => {
    if (filter === 'online' && !d.is_online) return false
    if (filter === 'offline' && d.is_online) return false
    if (filter === 'new' && d.is_registered) return false
    if (classFilter && d.device_class !== classFilter) return false
    if (segmentFilter && String(d.segment_id) !== segmentFilter) return false
    if (search) {
      const term = search.toLowerCase()
      return (
        d.mac_address.toLowerCase().includes(term) ||
        (d.ip_address ?? '').includes(term) ||
        (d.label ?? '').toLowerCase().includes(term) ||
        (d.hostname ?? '').toLowerCase().includes(term) ||
        (d.vendor ?? '').toLowerCase().includes(term)
      )
    }
    return true
  })

  const summaryCards = [
    { labelKey: 'total' as const, value: stats.total, color: 'text-text-base' },
    { labelKey: 'online' as const, value: stats.online, color: 'text-success' },
    { labelKey: 'offline' as const, value: stats.offline, color: 'text-danger' },
    { labelKey: 'unregistered' as const, value: stats.unregistered, color: 'text-warning' },
  ]

  return (
    <div className="flex flex-col gap-5">
      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {summaryCards.map((card) => (
          <Card key={card.labelKey} className="flex flex-col gap-1">
            <span className="text-xs text-text-subtle">{t(card.labelKey)}</span>
            <span className={`text-3xl font-bold ${card.color}`}>{card.value}</span>
          </Card>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        {/* Status filter tabs */}
        <div className="flex gap-1 bg-surface border border-border rounded-lg p-1">
          {(['all', 'online', 'offline', 'new'] as Filter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors
                ${filter === f ? 'bg-surface2 text-text-base' : 'text-text-subtle hover:text-text-muted'}`}
            >
              {filterLabels[f]}
            </button>
          ))}
        </div>

        {/* Search */}
        <div className="relative flex-1 min-w-40">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-text-subtle pointer-events-none"
            fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            placeholder={t('search_placeholder')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="input-field pl-9"
          />
        </div>

        {/* Class filter */}
        <select
          value={classFilter}
          onChange={(e) => setClassFilter(e.target.value)}
          className="input-field w-auto"
        >
          <option value="">{t('all_classes')}</option>
          {DEVICE_CLASSES.map((c) => <option key={c}>{c}</option>)}
        </select>

        {/* Segment filter */}
        {segments.length > 0 && (
          <select
            value={segmentFilter}
            onChange={(e) => setSegmentFilter(e.target.value)}
            className="input-field w-auto"
          >
            <option value="">{t('all_segments')}</option>
            {segments.map((s) => (
              <option key={s.id} value={String(s.id)}>{s.name}</option>
            ))}
          </select>
        )}
      </div>

      {/* Device table */}
      {loading ? (
        <div className="flex justify-center py-16">
          <Spinner size="lg" />
        </div>
      ) : (
        <DeviceTable
          devices={filtered}
          onRegister={setRegisterDevice}
          onRefresh={() => fetchDevices()}
        />
      )}

      {/* Register modal */}
      <RegisterDeviceModal
        device={registerDevice}
        onClose={() => setRegisterDevice(null)}
        onSaved={(updated) => {
          updateDevice(updated.id, updated)
          fetchDevices()  // refresh stats + segment data
          toast.success(`${updated.label} registered`)
        }}
      />
    </div>
  )
}
