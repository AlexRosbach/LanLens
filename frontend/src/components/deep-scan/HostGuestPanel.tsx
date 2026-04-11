import { useNavigate } from 'react-router-dom'
import type { DeviceHostRelationship } from '../../api/deepScan'
import { useI18n } from '../../i18n'
import { formatDistanceToNow } from 'date-fns'

interface Props {
  deviceId: number
  relationships: DeviceHostRelationship[]
}

export default function HostGuestPanel({ deviceId, relationships }: Props) {
  const { t } = useI18n()
  const navigate = useNavigate()

  if (relationships.length === 0) {
    return (
      <p className="text-sm text-text-subtle py-4 text-center">
        {t('host_guest_no_relationships')}
      </p>
    )
  }

  const asHost = relationships.filter((r) => r.host_device_id === deviceId)
  const asGuest = relationships.filter((r) => r.child_device_id === deviceId)

  const RelationshipRow = ({ rel, linkedId }: { rel: DeviceHostRelationship; linkedId: number }) => (
    <div
      className="flex items-center justify-between py-3 border-b border-border last:border-0 cursor-pointer hover:bg-surface2 rounded-lg px-2 -mx-2 transition-colors"
      onClick={() => navigate(`/devices/${linkedId}`)}
    >
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-medium text-primary">
          {rel.vm_identifier || `Device #${linkedId}`}
        </span>
        {rel.match_source && (
          <span className="text-xs text-text-subtle">
            {t('host_guest_match_via')} {rel.match_source.toUpperCase()}
          </span>
        )}
      </div>
      <div className="text-right">
        <span className="text-xs text-text-subtle">
          {formatDistanceToNow(new Date(rel.last_confirmed_at), { addSuffix: true })}
        </span>
      </div>
    </div>
  )

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
