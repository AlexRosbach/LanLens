import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { deepScanApi, type DeviceHostRelationship } from '../../api/deepScan'
import { devicesApi, type Device } from '../../api/devices'
import { useI18n } from '../../i18n'
import { formatRelativeTime } from '../../utils/formatters'

interface Props {
  deviceId: number
  relationships: DeviceHostRelationship[]
  onRelationshipDeleted?: () => void
  onSuggestionApplied?: () => void
}

export default function HostGuestPanel({ deviceId, relationships, onRelationshipDeleted, onSuggestionApplied }: Props) {
  const { t, lang } = useI18n()
  const navigate = useNavigate()
  const [linkedDevices, setLinkedDevices] = useState<Record<number, Device>>({})
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [applyingId, setApplyingId] = useState<number | null>(null)

  // Load linked device data to show labels / detect missing labels for suggestions
  useEffect(() => {
    if (relationships.length === 0) return
    const ids = new Set<number>()
    relationships.forEach((r) => {
      if (r.host_device_id !== deviceId) ids.add(r.host_device_id)
      if (r.child_device_id !== deviceId) ids.add(r.child_device_id)
    })
    Promise.all(Array.from(ids).map((id) => devicesApi.get(id).catch(() => null))).then((results) => {
      const map: Record<number, Device> = {}
      results.forEach((d) => { if (d) map[d.id] = d })
      setLinkedDevices(map)
    })
  }, [relationships, deviceId])

  const handleDelete = async (rel: DeviceHostRelationship) => {
    if (!confirm(t('delete_confirm'))) return
    setDeletingId(rel.id)
    try {
      await deepScanApi.deleteRelationship(deviceId, rel.id)
      toast.success('Relationship removed')
      onRelationshipDeleted?.()
    } catch {
      toast.error('Failed to remove relationship')
    } finally {
      setDeletingId(null)
    }
  }

  const handleApplySuggestion = async (guestDeviceId: number, suggestedLabel: string) => {
    setApplyingId(guestDeviceId)
    try {
      await devicesApi.update(guestDeviceId, { label: suggestedLabel })
      toast.success(`Label set to "${suggestedLabel}"`)
      onSuggestionApplied?.()
    } catch {
      toast.error('Failed to apply label')
    } finally {
      setApplyingId(null)
    }
  }

  if (relationships.length === 0) {
    return (
      <p className="text-sm text-text-subtle py-4 text-center">
        {t('host_guest_no_relationships')}
      </p>
    )
  }

  const asHost = relationships.filter((r) => r.host_device_id === deviceId)
  const asGuest = relationships.filter((r) => r.child_device_id === deviceId)

  const RelationshipRow = ({ rel, linkedId }: { rel: DeviceHostRelationship; linkedId: number }) => {
    const linked = linkedDevices[linkedId]
    const linkedLabel = linked
      ? linked.label || linked.hostname || linked.mac_address
      : rel.vm_identifier || `Device #${linkedId}`

    // Suggestion: vm has a vm_identifier but linked device has no label
    const showSuggestion =
      rel.vm_identifier &&
      linked &&
      !linked.label &&
      rel.host_device_id === deviceId // only suggest for guests when we are the host

    return (
      <div className="py-3 border-b border-border last:border-0 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div
            className="flex-1 flex flex-col gap-0.5 cursor-pointer hover:text-primary transition-colors"
            onClick={() => navigate(`/devices/${linkedId}`)}
          >
            <span className="text-sm font-medium text-primary">{linkedLabel}</span>
            <div className="flex items-center gap-3 flex-wrap">
              {rel.match_source && (
                <span className="text-xs text-text-subtle">
                  {t('host_guest_match_via')} {rel.match_source.toUpperCase()}
                </span>
              )}
              <span className="text-xs text-text-subtle">
                {formatRelativeTime(rel.last_confirmed_at, lang)}
              </span>
              {rel.vm_identifier && rel.vm_identifier !== linkedLabel && (
                <span className="text-xs text-text-subtle font-mono">{rel.vm_identifier}</span>
              )}
            </div>
          </div>
          <button
            onClick={() => handleDelete(rel)}
            disabled={deletingId === rel.id}
            className="flex-shrink-0 p-1.5 rounded-lg text-text-subtle hover:text-danger hover:bg-danger-dim transition-colors disabled:opacity-50"
            title={t('delete_confirm')}
          >
            {deletingId === rel.id ? (
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            )}
          </button>
        </div>

        {/* Suggestion panel */}
        {showSuggestion && (
          <div className="flex items-center gap-2 bg-warning-dim border border-warning/30 rounded-lg px-3 py-2">
            <svg className="w-4 h-4 text-warning flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            <p className="text-xs text-warning flex-1">
              {t('host_guest_suggest_label')}{' '}
              <strong className="font-mono">"{rel.vm_identifier}"</strong>
            </p>
            <button
              onClick={() => handleApplySuggestion(linkedId, rel.vm_identifier!)}
              disabled={applyingId === linkedId}
              className="text-xs font-medium text-warning hover:text-warning/80 underline disabled:opacity-50"
            >
              {applyingId === linkedId ? '…' : t('host_guest_apply_label')}
            </button>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {asHost.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">
            {t('host_guest_this_hosts')}
          </p>
          <div>
            {asHost.map((r) => (
              <RelationshipRow key={r.id} rel={r} linkedId={r.child_device_id} />
            ))}
          </div>
        </div>
      )}

      {asGuest.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-text-muted uppercase tracking-wide mb-2">
            {t('host_guest_this_runs_on')}
          </p>
          <div>
            {asGuest.map((r) => (
              <RelationshipRow key={r.id} rel={r} linkedId={r.host_device_id} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
