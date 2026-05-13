import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import toast from 'react-hot-toast'
import { Device, DeviceIpHistoryEntry, devicesApi } from '../api/devices'
import { idoitApi } from '../api/idoit'
import type { ChangeEvent } from '../api/inventory'
import ConnectButtons from '../components/devices/ConnectButtons'
import DeviceClassIcon, { DEVICE_CLASSES, isVmClass } from '../components/devices/DeviceClassIcon'
import ServicesList from '../components/devices/ServicesList'
import DeepScanPanel from '../components/deep-scan/DeepScanPanel'
import VmHostSection from '../components/deep-scan/VmHostSection'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Input from '../components/ui/Input'
import Spinner from '../components/ui/Spinner'
import { useI18n } from '../i18n'
import { backendUtcToLocalDateTimeInput, formatDateTime, formatDeviceLabel, formatMac, formatRelativeTime, localDateTimeInputToUtcIso, parseDateStr } from '../utils/formatters'

interface EditState {
  label: string
  deviceClass: string
  purpose: string
  description: string
  location: string
  responsible: string
  passwordLocation: string
  osInfo: string
  assetTag: string
  notes: string
  cmdbId: string
}

function idoitStatusVariant(status?: string | null): 'success' | 'danger' | 'warning' | 'primary' | 'muted' {
  if (status === 'synced' || status === 'validated') return 'success'
  if (status === 'error' || status === 'mapping_error') return 'danger'
  if (status === 'preview_ready' || status === 'pending_changes' || status === 'validated_pending_sync') return 'warning'
  if (status === 'linked') return 'primary'
  return 'muted'
}

function toEditState(d: Device): EditState {
  return {
    label: d.label ?? '',
    deviceClass: d.device_class,
    purpose: d.purpose ?? '',
    description: d.description ?? '',
    location: d.location ?? '',
    responsible: d.responsible ?? '',
    passwordLocation: d.password_location ?? '',
    osInfo: d.os_info ?? '',
    assetTag: d.asset_tag ?? '',
    notes: d.notes ?? '',
    cmdbId: d.cmdb_id ?? '',
  }
}

function InfoRow({ label, value, mono = false }: { label: string; value?: string | null; mono?: boolean }) {
  if (!value) return null
  return (
    <div>
      <p className="text-text-subtle text-xs mb-0.5">{label}</p>
      <p className={`text-text-muted text-xs ${mono ? 'font-mono' : ''}`}>{value}</p>
    </div>
  )
}

export default function DeviceDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { t, lang } = useI18n()
  const [device, setDevice] = useState<Device | null>(null)
  const [ipHistory, setIpHistory] = useState<DeviceIpHistoryEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<EditState | null>(null)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [refreshStatusLoading, setRefreshStatusLoading] = useState(false)
  const [portScanInput, setPortScanInput] = useState('')
  const [portScanInputLoading, setPortScanInputLoading] = useState(false)
  const [portScanRunning, setPortScanRunning] = useState(false)
  const [portScanRequestedAt, setPortScanRequestedAt] = useState<number | null>(null)
  const [timeline, setTimeline] = useState<ChangeEvent[]>([])
  const [maintenanceDraft, setMaintenanceDraft] = useState({ until: '', note: '' })
  const [maintenanceSaving, setMaintenanceSaving] = useState(false)
  const [idoitSyncing, setIdoitSyncing] = useState(false)

  useEffect(() => {
    if (!id) return
    devicesApi.get(Number(id)).then(async (d) => {
      let currentDevice = d
      try {
        await devicesApi.markViewed(d.id)
        if (!d.is_registered) {
          currentDevice = await devicesApi.update(d.id, { is_registered: true })
        }
      } catch {
        // best effort
      }
      setDevice(currentDevice)
      setMaintenanceDraft({
        until: backendUtcToLocalDateTimeInput(currentDevice.maintenance_until),
        note: currentDevice.maintenance_note ?? '',
      })
      setIpHistory(currentDevice.ip_history ?? [])
      setForm(toEditState(currentDevice))
      devicesApi.getIpHistory(currentDevice.id).then(setIpHistory).catch(() => {})
      devicesApi.getTimeline(currentDevice.id).then(setTimeline).catch(() => {})
    }).finally(() => setLoading(false))
  }, [id])

  useEffect(() => {
    if (!portScanRunning || !device?.id) return

    const timer = window.setInterval(async () => {
      try {
        const refreshed = await devicesApi.get(device.id)
        setDevice(refreshed)

        if (!refreshed.latest_scan?.scanned_at || portScanRequestedAt == null) return
        const latestScanAt = new Date(refreshed.latest_scan.scanned_at).getTime()
        if (!Number.isNaN(latestScanAt) && latestScanAt > portScanRequestedAt) {
          setPortScanRunning(false)
          setPortScanRequestedAt(null)
        }
      } catch {
        // ignore transient polling errors while scan is running
      }
    }, 3000)

    return () => window.clearInterval(timer)
  }, [device?.id, portScanRequestedAt, portScanRunning])

  function field(key: keyof EditState) {
    return {
      value: form?.[key] ?? '',
      onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
        setForm((f) => f ? { ...f, [key]: e.target.value } : f),
    }
  }

  async function handleSave() {
    if (!device || !form) return
    setSaving(true)
    try {
      const updated = await devicesApi.update(device.id, {
        label: form.label.trim() || undefined,
        device_class: form.deviceClass.trim() || 'Unknown',
        purpose: form.purpose.trim() || undefined,
        description: form.description.trim() || undefined,
        location: form.location.trim() || undefined,
        responsible: form.responsible.trim() || undefined,
        password_location: form.passwordLocation.trim() || undefined,
        os_info: form.osInfo.trim() || undefined,
        asset_tag: form.assetTag.trim() || undefined,
        notes: form.notes.trim() || undefined,
        cmdb_id: form.cmdbId.trim() || undefined,
        is_registered: true,
      })
      setDevice(updated)
      setMaintenanceDraft({
        until: backendUtcToLocalDateTimeInput(updated.maintenance_until),
        note: updated.maintenance_note ?? '',
      })
      setForm(toEditState(updated))
      setEditing(false)
      toast.success(t('device_updated'))
    } catch {
      toast.error(t('save_failed'))
    } finally {
      setSaving(false)
    }
  }

  function handleCancelEdit() {
    if (device) setForm(toEditState(device))
    setEditing(false)
  }

  async function handleDelete() {
    if (!device || !confirm(t('device_delete_confirm'))) return
    setDeleting(true)
    try {
      await devicesApi.delete(device.id)
      toast.success(t('device_removed'))
      navigate('/')
    } catch {
      toast.error(t('device_delete_failed'))
      setDeleting(false)
    }
  }

  async function handleRefreshStatus() {
    if (!device) return
    setRefreshStatusLoading(true)
    try {
      const updated = await devicesApi.refreshStatus(device.id)
      setDevice(updated)
      setMaintenanceDraft({
        until: backendUtcToLocalDateTimeInput(updated.maintenance_until),
        note: updated.maintenance_note ?? '',
      })
      setForm(toEditState(updated))
      setIpHistory(updated.ip_history ?? ipHistory)
      devicesApi.getIpHistory(updated.id).then(setIpHistory).catch(() => {})
      devicesApi.getTimeline(updated.id).then(setTimeline).catch(() => {})
      toast.success(updated.is_online ? t('device_status_online') : t('device_status_offline'))
    } catch {
      toast.error(t('device_status_refresh_failed'))
    } finally {
      setRefreshStatusLoading(false)
    }
  }

  async function handleMaintenanceChange(changes: { ignored?: boolean; notifications_muted?: boolean; maintenance_until?: string | null; maintenance_note?: string | null }) {
    if (!device) return
    try {
      const updated = await devicesApi.updateMaintenance(device.id, changes)
      setDevice(updated)
      setMaintenanceDraft({
        until: backendUtcToLocalDateTimeInput(updated.maintenance_until),
        note: updated.maintenance_note ?? '',
      })
      devicesApi.getTimeline(updated.id).then(setTimeline).catch(() => {})
      toast.success(t('device_updated'))
    } catch {
      toast.error(t('save_failed'))
    }
  }

  async function saveMaintenanceDraft() {
    if (!device) return
    setMaintenanceSaving(true)
    try {
      const updated = await devicesApi.updateMaintenance(device.id, {
        maintenance_until: localDateTimeInputToUtcIso(maintenanceDraft.until),
        maintenance_note: maintenanceDraft.note.trim() || null,
      })
      setDevice(updated)
      setMaintenanceDraft({
        until: backendUtcToLocalDateTimeInput(updated.maintenance_until),
        note: updated.maintenance_note ?? '',
      })
      devicesApi.getTimeline(updated.id).then(setTimeline).catch(() => {})
      toast.success(t('device_updated'))
    } catch {
      toast.error(t('save_failed'))
    } finally {
      setMaintenanceSaving(false)
    }
  }

  async function handleIdoitSyncNow() {
    if (!device) return
    setIdoitSyncing(true)
    try {
      await idoitApi.syncDevice(device.id)
      const refreshed = await devicesApi.get(device.id)
      setDevice(refreshed)
      toast.success(t('idoit_sync_started'))
    } catch (error) {
      const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      const message = typeof detail === 'object' && detail && 'message' in detail
        ? String((detail as { message?: unknown }).message)
        : t('idoit_sync_failed')
      toast.error(message)
    } finally {
      setIdoitSyncing(false)
    }
  }

  if (loading) return <div className="flex justify-center py-16"><Spinner size="lg" /></div>
  if (!device || !form) return <p className="text-text-muted">{t('device_not_found')}</p>

  const hasDocumentation = device.purpose || device.description || device.location ||
    device.responsible || device.password_location || device.os_info || device.asset_tag || device.notes
  const maintenanceActive = device.maintenance_until && parseDateStr(device.maintenance_until).getTime() > Date.now()
  const maintenanceFlags = [
    device.ignored ? t('maintenance_ignored') : null,
    device.notifications_muted ? t('maintenance_notifications_muted') : null,
    maintenanceActive ? t('maintenance_until', { time: formatDateTime(device.maintenance_until!) }) : null,
  ].filter(Boolean).join(' · ')

  return (
    <div className="max-w-3xl mx-auto flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <button onClick={() => navigate('/')} className="text-text-subtle hover:text-text-base transition-colors flex-shrink-0">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <div className="w-10 h-10 rounded-xl bg-surface2 border border-border flex items-center justify-center flex-shrink-0">
            <DeviceClassIcon deviceClass={device.device_class} className="w-5 h-5" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-lg font-bold text-text-base">{formatDeviceLabel(device, t('ip_only_host'))}</h1>
              {device.is_dhcp && (
                <span className="text-xs bg-primary-dim text-primary border border-primary/20 px-1.5 py-0.5 rounded-full">
                  {t('badge_dhcp')}
                </span>
              )}
              {device.segment_name && (
                <span
                  className="text-xs px-1.5 py-0.5 rounded-full font-medium"
                  style={{
                    backgroundColor: (device.segment_color ?? '#6366f1') + '22',
                    color: device.segment_color ?? '#6366f1',
                    border: `1px solid ${(device.segment_color ?? '#6366f1')}44`,
                  }}
                >
                  {device.segment_name}
                </span>
              )}
            </div>
            <p className="text-sm text-text-muted">{device.device_class} · {device.vendor ?? t('vendor_unknown')}</p>
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          <Badge variant={device.is_online ? 'success' : 'danger'} dot>
            {device.is_online ? t('badge_online') : t('badge_offline')}
          </Badge>
          {!device.is_online && (
            <Button variant="ghost" size="sm" loading={refreshStatusLoading} onClick={handleRefreshStatus}>
              {t('refresh_status')}
            </Button>
          )}
        </div>
      </div>

      {(device.ignored || device.notifications_muted || maintenanceActive) && (
        <Card className="border-warning/40 bg-warning/10">
          <p className="text-sm font-medium text-warning">{t('maintenance_mute_active')}</p>
          <p className="text-xs text-text-muted mt-1">
            {maintenanceFlags}
          </p>
          {device.maintenance_note && <p className="text-xs text-text-subtle mt-1">{device.maintenance_note}</p>}
        </Card>
      )}

      {/* Connect */}
      <Card>
        <h2 className="text-sm font-semibold text-text-muted mb-3">{t('connection_info')}</h2>
        <ConnectButtons device={device} />
      </Card>

      {/* Identity & Documentation */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-text-muted">{t('documentation')}</h2>
          {!editing ? (
            <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>{t('edit')}</Button>
          ) : (
            <div className="flex gap-2">
              <Button variant="ghost" size="sm" onClick={handleCancelEdit}>{t('cancel')}</Button>
              <Button size="sm" onClick={handleSave} loading={saving}>{t('save')}</Button>
            </div>
          )}
        </div>

        {editing ? (
          <div className="flex flex-col gap-4">
            {/* Identity */}
            <div className="grid grid-cols-2 gap-3">
              <Input label={t('label')} placeholder={t('device_label_placeholder')} {...field('label')} />
              <Input label={t('asset_tag')} placeholder={t('asset_tag_placeholder')} {...field('assetTag')} />
              <div className="col-span-2 flex items-end gap-2">
                <div className="flex-1">
                  <label className="block text-sm font-medium text-text-muted mb-1">{t('cmdb_id')}</label>
                  <Input
                    value={form.cmdbId}
                    onChange={(e) => setForm((f) => f ? { ...f, cmdbId: e.target.value } : f)}
                    placeholder="DEV-0001"
                  />
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={async () => {
                    if (!device) return
                    try {
                      const updated = await devicesApi.generateCmdbId(device.id)
                      setDevice(updated)
                      setForm(toEditState(updated))
                      toast.success(t('cmdb_id_generated', { id: updated.cmdb_id ?? '' }))
                    } catch {
                      toast.error(t('failed_generate_cmdb_id'))
                    }
                  }}
                >
                  {t('generate')}
                </Button>
              </div>
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-sm font-medium text-text-muted">{t('device_class')}</label>
              <div className="grid grid-cols-3 gap-2">
                {DEVICE_CLASSES.map((cls) => (
                  <button key={cls}
                    onClick={() => setForm((f) => f ? { ...f, deviceClass: cls } : f)}
                    className={`flex items-center gap-2 p-2 rounded-lg border text-xs font-medium transition-colors
                      ${form.deviceClass === cls
                        ? 'border-primary bg-primary-dim text-primary'
                        : 'border-border bg-surface2 text-text-muted hover:border-primary/50'}`}>
                    <DeviceClassIcon deviceClass={cls} className="w-4 h-4" />
                    {cls}
                  </button>
                ))}
              </div>
              <Input
                label={t('custom_device_class')}
                placeholder={t('custom_device_class_placeholder')}
                value={DEVICE_CLASSES.includes(form.deviceClass) ? '' : form.deviceClass}
                onChange={(e) => setForm((f) => f ? { ...f, deviceClass: e.target.value } : f)}
              />
            </div>

            {/* Documentation fields */}
            <div className="border-t border-border pt-4 grid grid-cols-2 gap-3">
              <Input label={t('purpose')} placeholder={t('purpose_placeholder')} {...field('purpose')} />
              <Input label={t('location')} placeholder={t('location_placeholder')} {...field('location')} />
              <Input label={t('responsible')} placeholder={t('responsible_placeholder')} {...field('responsible')} />
              <Input label={t('os_info')} placeholder={t('os_info_placeholder')} {...field('osInfo')} />
              <div className="col-span-2">
                <Input label={t('password_location')} placeholder={t('password_location_placeholder')} {...field('passwordLocation')} />
              </div>
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-sm font-medium text-text-muted">{t('description')}</label>
              <textarea
                rows={2}
                className="input-field resize-none"
                placeholder={t('description_placeholder')}
                {...field('description')}
              />
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-sm font-medium text-text-muted">{t('notes')}</label>
              <textarea
                rows={2}
                className="input-field resize-none"
                placeholder={t('notes_placeholder')}
                {...field('notes')}
              />
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {/* Network identity */}
            <div className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm">
              <InfoRow label={t('ip_address')} value={device.ip_address} mono />
              <InfoRow label={t('mac_address')} value={formatMac(device.mac_address, t('ip_only_host'))} mono />
              <InfoRow label={t('hostname')} value={device.hostname} mono />
              <InfoRow label={t('vendor')} value={device.vendor} />
              <InfoRow label={t('asset_tag')} value={device.asset_tag} />
              <InfoRow label={t('os_info')} value={device.os_info} />
              {device.cmdb_id && (
                <div>
                  <p className="text-text-subtle text-xs mb-0.5">{t('cmdb_id')}</p>
                  <p className="text-text-muted text-xs font-mono font-semibold text-primary">{device.cmdb_id}</p>
                </div>
              )}
              <div>
                <p className="text-text-subtle text-xs mb-0.5">{t('first_seen')}</p>
                <p className="text-text-muted text-xs">{formatDateTime(device.first_seen)}</p>
              </div>
              <div>
                <p className="text-text-subtle text-xs mb-0.5">{t('last_seen')}</p>
                <p className="text-text-muted text-xs">{formatRelativeTime(device.last_seen, lang)}</p>
              </div>
            </div>

            {device.idoit_enabled && (
              <div className="border-t border-border pt-4">
                <div className="flex items-center justify-between gap-3 mb-3">
                  <h2 className="text-sm font-semibold text-text-muted">{t('idoit_sync')}</h2>
                  <div className="flex items-center gap-2">
                    <Badge variant={idoitStatusVariant(device.idoit_sync_status)} dot>{device.idoit_sync_status || 'never_synced'}</Badge>
                    <Button size="sm" variant="outline" onClick={handleIdoitSyncNow} loading={idoitSyncing}>{t('idoit_sync_now')}</Button>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-x-8 gap-y-3 text-sm">
                  <InfoRow label={t('idoit_object_id')} value={device.idoit_object_id} mono />
                  <InfoRow label={t('idoit_sysid')} value={device.idoit_sysid} mono />
                  <div>
                    <p className="text-text-subtle text-xs mb-0.5">{t('idoit_object')}</p>
                    {device.idoit_object_url ? (
                      <a className="text-xs text-primary hover:underline" href={device.idoit_object_url} target="_blank" rel="noreferrer">{t('open_in_idoit')}</a>
                    ) : (
                      <p className="text-text-muted text-xs">—</p>
                    )}
                  </div>
                  <InfoRow label={t('idoit_last_sync')} value={device.idoit_last_sync_at ? formatDateTime(device.idoit_last_sync_at) : null} />
                  <InfoRow label={t('idoit_last_validation')} value={device.idoit_last_validation_at ? formatDateTime(device.idoit_last_validation_at) : null} />
                  {device.idoit_last_error && (
                    <div className="col-span-2">
                      <p className="text-text-subtle text-xs mb-0.5">{t('idoit_last_error')}</p>
                      <p className="text-danger text-xs whitespace-pre-wrap">{device.idoit_last_error}</p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Documentation fields */}
            {hasDocumentation && (
              <div className="border-t border-border pt-4 grid grid-cols-2 gap-x-8 gap-y-3 text-sm">
                <InfoRow label={t('purpose')} value={device.purpose} />
                <InfoRow label={t('location')} value={device.location} />
                <InfoRow label={t('responsible')} value={device.responsible} />
                <InfoRow label={t('password_location')} value={device.password_location} />
                {device.description && (
                  <div className="col-span-2">
                    <p className="text-text-subtle text-xs mb-0.5">{t('description')}</p>
                    <p className="text-text-muted text-xs whitespace-pre-wrap">{device.description}</p>
                  </div>
                )}
                {device.notes && (
                  <div className="col-span-2">
                    <p className="text-text-subtle text-xs mb-0.5">{t('notes')}</p>
                    <p className="text-text-muted text-xs whitespace-pre-wrap">{device.notes}</p>
                  </div>
                )}
              </div>
            )}

            {!hasDocumentation && (
              <p className="text-xs text-text-subtle border-t border-border pt-3">
                {t('no_device_documentation', { edit: t('edit') })}
              </p>
            )}
          </div>
        )}
      </Card>

      {/* IP History */}
      <Card>
        <h2 className="text-sm font-semibold text-text-muted mb-3">{t('ip_history')}</h2>
        {ipHistory.length === 0 ? (
          <p className="text-sm text-text-subtle">{t('ip_history_empty')}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-text-subtle uppercase tracking-wider">
                  <th className="py-2 pr-3 text-left font-medium">{t('ip_address')}</th>
                  <th className="py-2 pr-3 text-left font-medium">{t('first_seen')}</th>
                  <th className="py-2 pr-3 text-left font-medium">{t('last_seen')}</th>
                  <th className="py-2 text-left font-medium">{t('seen_count')}</th>
                </tr>
              </thead>
              <tbody>
                {ipHistory.map((entry) => (
                  <tr key={entry.id} className="border-b border-border last:border-0">
                    <td className="py-2 pr-3 font-mono text-text-muted">{entry.ip_address}</td>
                    <td className="py-2 pr-3 text-text-subtle">{formatDateTime(entry.first_seen)}</td>
                    <td className="py-2 pr-3 text-text-subtle">{formatRelativeTime(entry.last_seen, lang)}</td>
                    <td className="py-2 text-text-subtle">{entry.seen_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Services */}
      <Card>
        <h2 className="text-sm font-semibold text-text-muted mb-3">{t('services')}</h2>
        <ServicesList
          deviceId={device.id}
          services={device.services}
          onChange={(services) => setDevice({ ...device, services })}
        />
      </Card>

      {/* Host assignment (only for VM device classes) */}
      {isVmClass(device.device_class) && (
        <Card>
          <h2 className="text-sm font-semibold text-text-muted mb-3">{t('vm_host_section_title')}</h2>
          <VmHostSection deviceId={device.id} />
        </Card>
      )}

      {/* Deep Scan */}
      <Card>
        <h2 className="text-sm font-semibold text-text-muted mb-3">{t('deep_scan')}</h2>
        <DeepScanPanel deviceId={device.id} />
      </Card>

      {/* Open Ports */}
      <Card>
        <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
          <h2 className="text-sm font-semibold text-text-muted">
            {t('open_ports')}
            {device.latest_scan && (
              <span className="ml-2 text-xs font-normal text-text-subtle">
                ({t('last_scanned')} {formatRelativeTime(device.latest_scan.scanned_at, lang)})
              </span>
            )}
          </h2>
          <div className="flex flex-col gap-1 items-start">
            <div className="flex items-center gap-2 flex-wrap">
              <Input
                value={portScanInput}
                onChange={(e) => setPortScanInput(e.target.value)}
                placeholder={t('port_scan_input_placeholder')}
                className="w-52"
              />
              <Button
              size="sm"
              loading={portScanInputLoading}
              disabled={portScanRunning}
              onClick={async () => {
                if (!device) return
                const value = portScanInput.trim()
                const isDefaultScan = value.length === 0
                const isSinglePort = /^\d+$/.test(value)
                const isPortRange = /^top:\d+$/.test(value) || /^\d+(-\d+)?(,\d+(-\d+)?)*$/.test(value)

                if (!isDefaultScan && !isSinglePort && !isPortRange) {
                  toast.error(t('port_range_invalid'))
                  return
                }

                setPortScanInputLoading(true)
                try {
                  if (isDefaultScan) {
                    await devicesApi.scanPorts(device.id)
                    toast.success(t('port_scan_started'))
                  } else if (isSinglePort) {
                    const port = Number(value)
                    if (!Number.isInteger(port) || port < 1 || port > 65535) {
                      toast.error(t('single_port_invalid'))
                      return
                    }
                    await devicesApi.scanSinglePort(device.id, port)
                    toast.success(t('single_port_scan_started', { port }))
                  } else {
                    await devicesApi.scanPortRange(device.id, value)
                    toast.success(t('port_range_scan_started', { range: value }))
                  }
                  setPortScanRequestedAt(Date.now())
                  setPortScanRunning(true)
                  setPortScanInput('')
                } catch {
                  toast.error(
                    isDefaultScan
                      ? t('port_scan_failed')
                      : isSinglePort
                        ? t('single_port_scan_failed')
                        : t('port_range_scan_failed')
                  )
                } finally {
                  setPortScanInputLoading(false)
                }
              }}
              >
                {portScanRunning ? t('port_scan_running') : t('scan_ports')}
              </Button>
            </div>
            <p className="text-xs text-text-subtle">{t('port_scan_input_help')}</p>
          </div>
        </div>
        {device.latest_scan ? (
          device.latest_scan.open_ports.length === 0 ? (
            <p className="text-sm text-text-subtle">{t('no_open_ports_found')}</p>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {device.latest_scan.open_ports.map((p) => (
                <div key={`${p.port}-${p.protocol}`}
                  className="flex items-center gap-2 bg-surface2 rounded-lg px-3 py-2 text-xs">
                  <span className="font-mono font-medium text-primary">{p.port}</span>
                  <span className="text-text-subtle">{p.protocol}</span>
                  <span className="text-text-muted ml-auto">{p.service}</span>
                </div>
              ))}
            </div>
          )
        ) : (
          <p className="text-sm text-text-subtle">{t('port_scan_not_scanned_yet')}</p>
        )}
      </Card>

      <Card>
        <h2 className="text-sm font-semibold text-text-muted mb-3">{t('maintenance_noise_control')}</h2>
        <p className="text-xs text-text-subtle mb-3">{t('maintenance_noise_help')}</p>
        <div className="grid sm:grid-cols-2 gap-3 text-sm">
          <label className="flex items-center gap-2 text-text-muted">
            <input type="checkbox" checked={!!device.notifications_muted} onChange={(e) => handleMaintenanceChange({ notifications_muted: e.target.checked })} />
            {t('maintenance_mute_notifications')}
          </label>
          <label className="flex items-center gap-2 text-text-muted">
            <input type="checkbox" checked={!!device.ignored} onChange={(e) => handleMaintenanceChange({ ignored: e.target.checked })} />
            {t('maintenance_ignore_device')}
          </label>
        </div>
        <div className="mt-3 grid sm:grid-cols-2 gap-3">
          <label className="block">
            <span className="block text-xs text-text-subtle mb-1">{t('maintenance_until_label')}</span>
            <Input
              type="datetime-local"
              value={maintenanceDraft.until}
              onChange={(e) => setMaintenanceDraft((draft) => ({ ...draft, until: e.target.value }))}
            />
          </label>
          <Input
            value={maintenanceDraft.note}
            onChange={(e) => setMaintenanceDraft((draft) => ({ ...draft, note: e.target.value }))}
            placeholder={t('maintenance_note')}
          />
        </div>
        <div className="mt-3 flex justify-end gap-2">
          <Button size="sm" variant="outline" onClick={() => setMaintenanceDraft({ until: '', note: '' })}>{t('maintenance_clear')}</Button>
          <Button size="sm" onClick={saveMaintenanceDraft} loading={maintenanceSaving}>{t('save')}</Button>
        </div>
      </Card>

      <Card>
        <h2 className="text-sm font-semibold text-text-muted mb-3">{t('change_timeline')}</h2>
        {timeline.length === 0 ? (
          <p className="text-sm text-text-subtle">{t('no_changes_recorded')}</p>
        ) : (
          <div className="space-y-2">
            {timeline.slice(0, 12).map((event) => (
              <div key={event.id} className="border border-border rounded-lg p-3 bg-surface2/40">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-medium text-text-base">{event.event_type.replace(/_/g, ' ')}</p>
                  <span className="text-xs text-text-subtle">{formatRelativeTime(event.created_at, lang)}</span>
                </div>
                <p className="text-xs text-text-subtle mt-1">
                  {event.field_name ? `${event.field_name}: ${event.old_value ?? '—'} → ${event.new_value ?? '—'}` : event.message ?? event.source}
                </p>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Danger zone */}
      <Card>
        <h2 className="text-sm font-semibold text-danger mb-2">{t('danger_zone')}</h2>
        <p className="text-xs text-text-subtle mb-3">
          {t('delete_device_warning')}
        </p>
        <Button variant="danger" size="sm" loading={deleting} onClick={handleDelete}>
          {t('delete_device')}
        </Button>
      </Card>
    </div>
  )
}
