/**
 * VmHostSection — shown inside DeviceDetail when the device class is a VM type.
 * Displays the host device (if a relationship exists) and allows manual linking.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { deepScanApi, type DeviceHostRelationship } from '../../api/deepScan'
import { devicesApi, type Device } from '../../api/devices'
import { isHypervisorClass } from '../devices/DeviceClassIcon'
import { useI18n } from '../../i18n'

interface Props {
  deviceId: number
}

export default function VmHostSection({ deviceId }: Props) {
  const { t } = useI18n()
  const navigate = useNavigate()

  const [relationships, setRelationships] = useState<DeviceHostRelationship[]>([])
  const [hostDevices, setHostDevices] = useState<Device[]>([])
  const [hostData, setHostData] = useState<Record<number, Device>>({})
  const [selectedHostId, setSelectedHostId] = useState<string>('')
  const [saving, setSaving] = useState(false)
  const [removingId, setRemovingId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)

  const load = async () => {
    try {
      const [relsResp, allDevicesResp] = await Promise.all([
        deepScanApi.getRelationships(deviceId),
        devicesApi.list().catch(() => ({ items: [] as Device[], total: 0, online: 0, offline: 0, unregistered: 0 })),
      ])
      const rels = relsResp.data.filter((r) => r.child_device_id === deviceId)
      setRelationships(rels)

      const allDevices: Device[] = allDevicesResp.items ?? []

      // Separate hypervisor candidates from all devices
      const candidates = allDevices.filter(
        (d) => isHypervisorClass(d.device_class) && d.id !== deviceId
      )
      setHostDevices(candidates)

      // Load linked host device data
      const hostIds = new Set(rels.map((r) => r.host_device_id))
      const hostMap: Record<number, Device> = {}
      for (const d of allDevices) {
        if (hostIds.has(d.id)) hostMap[d.id] = d
      }
      setHostData(hostMap)
    } catch { /* silent */ } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [deviceId])

  const handleLink = async () => {
    if (!selectedHostId) return
    setSaving(true)
    try {
      await deepScanApi.createRelationship(deviceId, Number(selectedHostId))
      toast.success(t('vm_host_linked'))
      setSelectedHostId('')
      await load()
    } catch {
      toast.error(t('failed_to_link_host'))
    } finally {
      setSaving(false)
    }
  }

  const handleUnlink = async (rel: DeviceHostRelationship) => {
    if (!confirm(t('delete_confirm'))) return
    setRemovingId(rel.id)
    try {
      await deepScanApi.deleteRelationship(deviceId, rel.id)
      toast.success(t('vm_host_unlinked'))
      await load()
    } catch {
      toast.error(t('failed_to_unlink_host'))
    } finally {
      setRemovingId(null)
    }
  }

  if (loading) return null

  const hostRels = relationships.filter((r) => r.child_device_id === deviceId)

  // Filter out already-linked hosts from the dropdown
  const linkedHostIds = new Set(hostRels.map((r) => r.host_device_id))
  const availableHosts = hostDevices.filter((d) => !linkedHostIds.has(d.id))

  return (
    <div className="space-y-3">
      {/* Currently linked hosts */}
      {hostRels.length > 0 && (
        <div className="space-y-2">
          {hostRels.map((rel) => {
            const host = hostData[rel.host_device_id]
            const label = host
              ? host.label || host.hostname || host.mac_address
              : `Device #${rel.host_device_id}`
            return (
              <div
                key={rel.id}
                className="flex items-center gap-3 bg-surface2 rounded-lg px-3 py-2.5 border border-border"
              >
                <svg className="w-4 h-4 text-text-muted flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.6}
                    d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01" />
                </svg>
                <button
                  className="flex-1 text-sm font-medium text-primary hover:underline text-left"
                  onClick={() => navigate(`/devices/${rel.host_device_id}`)}
                >
                  {label}
                </button>
                {rel.match_source && (
                  <span className="text-xs text-text-subtle px-1.5 py-0.5 bg-surface rounded border border-border">
                    {rel.match_source}
                  </span>
                )}
                <button
                  onClick={() => handleUnlink(rel)}
                  disabled={removingId === rel.id}
                  className="flex-shrink-0 p-1 rounded text-text-subtle hover:text-danger hover:bg-danger-dim transition-colors disabled:opacity-50"
                  title={t('vm_host_unlink')}
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
                      d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            )
          })}
        </div>
      )}

      {/* Link a host */}
      {availableHosts.length > 0 && (
        <div className="flex gap-2 items-end">
          <div className="flex-1 flex flex-col gap-1">
            <label className="text-xs text-text-subtle">{t('vm_host_select')}</label>
            <select
              value={selectedHostId}
              onChange={(e) => setSelectedHostId(e.target.value)}
              className="input-field text-sm"
            >
              <option value="">{t('vm_host_select_placeholder')}</option>
              {availableHosts.map((d) => (
                <option key={d.id} value={String(d.id)}>
                  {d.label || d.hostname || d.mac_address} ({d.device_class})
                </option>
              ))}
            </select>
          </div>
          <button
            onClick={handleLink}
            disabled={!selectedHostId || saving}
            className="px-3 py-2 text-sm rounded-lg bg-primary text-white font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {saving ? '…' : t('vm_host_link')}
          </button>
        </div>
      )}

      {hostRels.length === 0 && availableHosts.length === 0 && (
        <p className="text-xs text-text-subtle">{t('vm_host_no_hosts_available')}</p>
      )}
    </div>
  )
}
