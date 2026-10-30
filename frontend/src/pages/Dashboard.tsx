import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import { Device, devicesApi } from '../api/devices'
import { Segment, segmentsApi } from '../api/segments'
import RegisterDeviceModal from '../components/devices/RegisterDeviceModal'
import BulkEditDevicesModal from '../components/devices/BulkEditDevicesModal'
import DeviceTable from '../components/devices/DeviceTable'
import Spinner from '../components/ui/Spinner'
import Card from '../components/ui/Card'
import { useDeviceStore } from '../store/deviceStore'
import { useI18n } from '../i18n'
import { DEVICE_CLASSES } from '../components/devices/DeviceClassIcon'
import type { BulkPortScanStatus, DeviceUpdate } from '../api/devices'

function ipToInt(ip: string): number {
  const parts = ip.split('.').map(Number)
  return parts.length === 4 ? ((parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]) >>> 0 : 0
}

function ipInRange(ip: string, start: string, end: string): boolean {
  return ipToInt(ip) >= ipToInt(start) && ipToInt(ip) <= ipToInt(end)
}

type Filter = 'all' | 'online' | 'offline' | 'new' | 'archived'

export default function Dashboard() {
  const { devices, stats, loading, fetchDevices, updateDevice } = useDeviceStore()
  const { t } = useI18n()
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')
  const [classFilter, setClassFilter] = useState('')
  const [searchParams] = useSearchParams()
  const [segmentFilter, setSegmentFilter] = useState(() => searchParams.get('segment') ?? '')
  const [registerDevice, setRegisterDevice] = useState<Device | null>(null)
  const [segments, setSegments] = useState<Segment[]>([])
  const [selectedDeviceIds, setSelectedDeviceIds] = useState<Set<number>>(new Set())
  const [deletingSelected, setDeletingSelected] = useState(false)
  const [bulkEditOpen, setBulkEditOpen] = useState(false)
  const [bulkEditing, setBulkEditing] = useState(false)
  const [bulkScanStatus, setBulkScanStatus] = useState<BulkPortScanStatus | null>(null)
  const bulkScanStatusRef = useRef<BulkPortScanStatus | null>(null)
  const [startingBulkScan, setStartingBulkScan] = useState(false)

  const newDevicesCount = devices.filter((d) => d.is_new).length
  const deviceClassOptions = Array.from(new Set([...DEVICE_CLASSES, ...devices.map((d) => d.device_class).filter(Boolean)])).sort()

  useEffect(() => {
    fetchDevices({ archived_only: filter === 'archived' })
    segmentsApi.list().then(setSegments).catch(() => {})
  }, [fetchDevices, filter])

  useEffect(() => {
    let polling = false
    const poll = async () => {
      if (polling) return
      polling = true
      try {
        const status = await devicesApi.getBulkPortScanStatus()
        const previous = bulkScanStatusRef.current
        bulkScanStatusRef.current = status
        if (
          !previous
          || previous.job_id !== status.job_id
          || previous.status !== status.status
          || previous.total !== status.total
          || previous.completed !== status.completed
          || previous.succeeded !== status.succeeded
          || previous.failed !== status.failed
          || previous.skipped !== status.skipped
          || previous.cancel_requested !== status.cancel_requested
        ) {
          setBulkScanStatus(status)
        }
        if (
          previous &&
          ['running', 'cancelling'].includes(previous.status) &&
          ['completed', 'cancelled'].includes(status.status)
        ) {
          await fetchDevices({ archived_only: filter === 'archived' })
          toast.success(t(status.status === 'completed' ? 'bulk_scan_completed' : 'bulk_scan_cancelled', {
            succeeded: status.succeeded,
            total: status.total,
          }))
        }
      } catch {
        // Keep the last visible progress state; the next poll may recover.
      } finally {
        polling = false
      }
    }
    void poll()
    const timer = window.setInterval(poll, 3000)
    return () => window.clearInterval(timer)
  }, [fetchDevices, filter, t])

  const filterLabels: Record<Filter, string> = {
    all: t('filter_all'),
    online: t('filter_online'),
    offline: t('filter_offline'),
    new: t('filter_new'),
    archived: t('filter_archived'),
  }

  const filtered = devices.filter((d) => {
    if (filter === 'archived') return true
    if (filter === 'online' && !d.is_online) return false
    if (filter === 'offline' && d.is_online) return false
    if (filter === 'new' && !d.is_new) return false
    if (classFilter && d.device_class !== classFilter) return false
    if (segmentFilter) {
      const seg = segments.find((s) => String(s.id) === segmentFilter)
      if (seg) {
        const byId = d.segment_id === seg.id
        const byIp = d.ip_address != null && ipInRange(d.ip_address, seg.ip_start, seg.ip_end)
        if (!byId && !byIp) return false
      }
    }
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

  function toggleSelected(deviceId: number) {
    setSelectedDeviceIds((current) => {
      const next = new Set(current)
      if (next.has(deviceId)) next.delete(deviceId)
      else next.add(deviceId)
      return next
    })
  }

  function toggleAll(deviceIds: number[], selected: boolean) {
    setSelectedDeviceIds((current) => {
      const next = new Set(current)
      deviceIds.forEach((deviceId) => selected ? next.add(deviceId) : next.delete(deviceId))
      return next
    })
  }

  async function deleteSelected() {
    const deviceIds = Array.from(selectedDeviceIds)
    if (deviceIds.length === 0 || !window.confirm(t('bulk_delete_confirm', { count: String(deviceIds.length) }))) return
    setDeletingSelected(true)
    try {
      await devicesApi.bulkDelete(deviceIds, (batch) => {
        setSelectedDeviceIds((current) => {
          const next = new Set(current)
          batch.forEach((deviceId) => next.delete(deviceId))
          return next
        })
      })
      toast.success(t('bulk_delete_success', { count: String(deviceIds.length) }))
    } catch {
      toast.error(t('bulk_delete_failed'))
    } finally {
      try {
        await fetchDevices({ archived_only: filter === 'archived' })
      } finally {
        setDeletingSelected(false)
      }
    }
  }

  async function saveBulkEdit(fields: Pick<DeviceUpdate, 'device_class' | 'responsible' | 'location' | 'description'>) {
    const deviceIds = Array.from(selectedDeviceIds)
    if (deviceIds.length === 0) return
    setBulkEditing(true)
    try {
      const result = await devicesApi.bulkUpdate(deviceIds, fields)
      toast.success(t('bulk_edit_success', { count: result.updated }))
      setBulkEditOpen(false)
    } catch {
      toast.error(t('bulk_edit_failed'))
    } finally {
      try {
        await fetchDevices({ archived_only: filter === 'archived' })
      } finally {
        setBulkEditing(false)
      }
    }
  }

  async function startBulkScan() {
    setStartingBulkScan(true)
    try {
      const selected = Array.from(selectedDeviceIds)
      const status = await devicesApi.startBulkPortScan(selected.length ? selected : undefined)
      bulkScanStatusRef.current = status
      setBulkScanStatus(status)
      toast.success(t('bulk_scan_started', { count: status.total }))
    } catch {
      toast.error(t('bulk_scan_failed'))
    } finally {
      setStartingBulkScan(false)
    }
  }

  const summaryCards = [
    { labelKey: 'total' as const, value: stats.total, color: 'text-text-base' },
    { labelKey: 'online' as const, value: stats.online, color: 'text-success' },
    { labelKey: 'offline' as const, value: stats.offline, color: 'text-danger' },
    { labelKey: 'filter_new' as const, value: stats.unregistered, color: 'text-warning' },
    { labelKey: 'filter_archived' as const, value: stats.archived, color: 'text-text-subtle' },
  ]

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {summaryCards.map((card) => (
          <Card key={card.labelKey} className="flex flex-col gap-1">
            <span className="text-xs text-text-subtle">{t(card.labelKey)}</span>
            <span className={`text-3xl font-bold ${card.color}`}>{card.value}</span>
          </Card>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1 bg-surface border border-border rounded-lg p-1">
          {(['all', 'online', 'offline', 'new', 'archived'] as Filter[]).map((f) => (
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

        {newDevicesCount > 0 && (
          <span className="badge-new">{newDevicesCount} {t('filter_new').toLowerCase()}</span>
        )}

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

        <select
          value={classFilter}
          onChange={(e) => setClassFilter(e.target.value)}
          className="input-field w-auto"
        >
          <option value="">{t('all_classes')}</option>
          {deviceClassOptions.map((c) => <option key={c}>{c}</option>)}
        </select>

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

        <button
          type="button"
          onClick={startBulkScan}
          disabled={startingBulkScan || bulkScanStatus?.status === 'running' || bulkScanStatus?.status === 'cancelling'}
          className="px-3 py-2 rounded-lg text-sm font-medium border border-primary/40 text-primary hover:bg-primary-dim disabled:opacity-50"
        >
          {selectedDeviceIds.size > 0
            ? t('bulk_scan_selected', { count: selectedDeviceIds.size })
            : t('bulk_scan_all')}
        </button>

        {selectedDeviceIds.size > 0 && (
          <>
            <button
              type="button"
              onClick={() => setBulkEditOpen(true)}
              className="px-3 py-2 rounded-lg text-sm font-medium border border-border text-text-muted hover:border-primary hover:text-primary"
            >
              {t('bulk_edit_selected', { count: selectedDeviceIds.size })}
            </button>
            <button
              type="button"
              onClick={deleteSelected}
              disabled={deletingSelected}
              className="px-3 py-2 rounded-lg text-sm font-medium bg-danger text-white hover:opacity-90 disabled:opacity-50"
            >
              {t('delete_selected_devices', { count: String(selectedDeviceIds.size) })}
            </button>
          </>
        )}
      </div>

      {bulkScanStatus && ['running', 'cancelling'].includes(bulkScanStatus.status) && (
        <Card className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-3 text-sm">
            <span className="font-medium text-text-base">{t('bulk_scan_progress', { completed: bulkScanStatus.completed, total: bulkScanStatus.total })}</span>
            <button
              type="button"
              disabled={bulkScanStatus.status === 'cancelling'}
              onClick={async () => {
                try {
                  setBulkScanStatus(await devicesApi.cancelBulkPortScan())
                } catch {
                  toast.error(t('bulk_scan_cancel_failed'))
                }
              }}
              className="text-xs font-medium text-danger hover:underline disabled:opacity-50"
            >
              {bulkScanStatus.status === 'cancelling' ? t('bulk_scan_cancelling') : t('bulk_scan_cancel')}
            </button>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-surface2">
            <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${bulkScanStatus.total ? (bulkScanStatus.completed / bulkScanStatus.total) * 100 : 0}%` }} />
          </div>
          <p className="text-xs text-text-subtle">{t('bulk_scan_counts', { succeeded: bulkScanStatus.succeeded, failed: bulkScanStatus.failed, skipped: bulkScanStatus.skipped })}</p>
        </Card>
      )}

      {loading ? (
        <div className="flex justify-center py-16">
          <Spinner size="lg" />
        </div>
      ) : (
        <DeviceTable
          devices={filtered}
          onRegister={setRegisterDevice}
          onRefresh={() => fetchDevices({ archived_only: filter === 'archived' })}
          selectedIds={selectedDeviceIds}
          onToggleSelected={toggleSelected}
          onToggleAll={toggleAll}
        />
      )}

      <RegisterDeviceModal
        device={registerDevice}
        onClose={() => setRegisterDevice(null)}
        onSaved={(updated) => {
          updateDevice(updated.id, updated)
          fetchDevices()
          toast.success(`${updated.label} registered`)
        }}
      />
      <BulkEditDevicesModal
        open={bulkEditOpen}
        count={selectedDeviceIds.size}
        saving={bulkEditing}
        onClose={() => setBulkEditOpen(false)}
        onSave={saveBulkEdit}
      />
    </div>
  )
}
