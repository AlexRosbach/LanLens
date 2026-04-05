import { useState } from 'react'
import toast from 'react-hot-toast'
import { Service, servicesApi } from '../../api/services'
import Button from '../ui/Button'
import ServiceIcon, { ServiceTypeTag } from './ServiceIcon'
import AddServiceModal from './AddServiceModal'

interface Props {
  deviceId: number
  services: Service[]
  onChange: (services: Service[]) => void
}

export default function ServicesList({ deviceId, services, onChange }: Props) {
  const [showAdd, setShowAdd] = useState(false)
  const [editService, setEditService] = useState<Service | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  function handleSaved(saved: Service) {
    const existing = services.find((s) => s.id === saved.id)
    if (existing) {
      onChange(services.map((s) => (s.id === saved.id ? saved : s)))
    } else {
      onChange([...services, saved])
    }
  }

  async function handleDelete(service: Service) {
    if (!confirm(`Remove service "${service.name}"?`)) return
    setDeletingId(service.id)
    try {
      await servicesApi.delete(deviceId, service.id)
      onChange(services.filter((s) => s.id !== service.id))
      toast.success('Service removed')
    } catch {
      toast.error('Failed to remove service')
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <>
      <div className="flex flex-col gap-2">
        {services.length === 0 && (
          <p className="text-sm text-text-subtle py-2">
            No services documented yet. Add one to start building your network documentation.
          </p>
        )}

        {services.map((svc) => (
          <ServiceCard
            key={svc.id}
            service={svc}
            onEdit={() => setEditService(svc)}
            onDelete={() => handleDelete(svc)}
            deleting={deletingId === svc.id}
          />
        ))}

        <div className="pt-1">
          <Button variant="ghost" size="sm" onClick={() => setShowAdd(true)}>
            <svg className="w-4 h-4 mr-1.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Add Service
          </Button>
        </div>
      </div>

      {showAdd && (
        <AddServiceModal
          deviceId={deviceId}
          onClose={() => setShowAdd(false)}
          onSaved={handleSaved}
        />
      )}
      {editService && (
        <AddServiceModal
          deviceId={deviceId}
          editService={editService}
          onClose={() => setEditService(null)}
          onSaved={handleSaved}
        />
      )}
    </>
  )
}

function ServiceCard({
  service,
  onEdit,
  onDelete,
  deleting,
}: {
  service: Service
  onEdit: () => void
  onDelete: () => void
  deleting: boolean
}) {
  const [expanded, setExpanded] = useState(false)

  const hasDetails =
    service.description ||
    service.version ||
    service.username_hint ||
    service.password_location ||
    service.notes

  return (
    <div className="border border-border rounded-xl bg-surface2/40 overflow-hidden">
      {/* Header row */}
      <div className="flex items-center gap-3 px-3 py-2.5">
        <ServiceIcon iconKey={service.icon_key} serviceType={service.service_type} className="w-8 h-8 flex-shrink-0" />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-text-base">{service.name}</span>
            <ServiceTypeTag type={service.service_type} />
            {service.version && (
              <span className="text-xs text-text-subtle">v{service.version}</span>
            )}
          </div>
          {service.description && (
            <p className="text-xs text-text-subtle truncate mt-0.5">{service.description}</p>
          )}
        </div>

        <div className="flex items-center gap-1.5 flex-shrink-0">
          {service.url && (
            <a
              href={service.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 transition-colors px-2 py-1 rounded-lg hover:bg-primary-dim"
              title={service.url}
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
              </svg>
              Open
            </a>
          )}
          {service.port && !service.url && (
            <span className="text-xs text-text-subtle font-mono px-2 py-1">:{service.port}</span>
          )}

          {hasDetails && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="p-1.5 rounded-lg text-text-subtle hover:text-text-muted hover:bg-surface2 transition-colors"
              title={expanded ? 'Collapse' : 'Expand'}
            >
              <svg className={`w-4 h-4 transition-transform ${expanded ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
          )}

          <button
            onClick={onEdit}
            className="p-1.5 rounded-lg text-text-subtle hover:text-text-muted hover:bg-surface2 transition-colors"
            title="Edit"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
            </svg>
          </button>

          <button
            onClick={onDelete}
            disabled={deleting}
            className="p-1.5 rounded-lg text-text-subtle hover:text-danger hover:bg-danger/10 transition-colors disabled:opacity-50"
            title="Remove"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
        </div>
      </div>

      {/* Expanded details */}
      {expanded && hasDetails && (
        <div className="border-t border-border px-3 py-3 grid grid-cols-2 gap-x-6 gap-y-2.5 text-xs bg-surface/50">
          {service.url && (
            <div className="col-span-2">
              <p className="text-text-subtle mb-0.5">URL</p>
              <p className="text-text-muted font-mono break-all">{service.url}</p>
            </div>
          )}
          {service.port && (
            <div>
              <p className="text-text-subtle mb-0.5">Port</p>
              <p className="text-text-muted font-mono">{service.port} / {service.protocol}</p>
            </div>
          )}
          {service.version && (
            <div>
              <p className="text-text-subtle mb-0.5">Version</p>
              <p className="text-text-muted">{service.version}</p>
            </div>
          )}
          {service.username_hint && (
            <div>
              <p className="text-text-subtle mb-0.5">Username / Login</p>
              <p className="text-text-muted font-mono">{service.username_hint}</p>
            </div>
          )}
          {service.password_location && (
            <div>
              <p className="text-text-subtle mb-0.5">Password Location</p>
              <p className="text-text-muted">{service.password_location}</p>
            </div>
          )}
          {service.notes && (
            <div className="col-span-2">
              <p className="text-text-subtle mb-0.5">Notes</p>
              <p className="text-text-muted whitespace-pre-wrap">{service.notes}</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
