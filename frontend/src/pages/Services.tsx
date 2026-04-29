import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import toast from 'react-hot-toast'
import { servicesApi, type ServiceDirectoryItem, type ServiceGroup, SERVICE_TYPE_LABELS } from '../api/services'
import Card from '../components/ui/Card'
import Input from '../components/ui/Input'
import Button from '../components/ui/Button'
import Spinner from '../components/ui/Spinner'
import ServiceIcon, { ServiceTypeTag } from '../components/devices/ServiceIcon'
import { useI18n } from '../i18n'

type Section = {
  id: string
  name: string
  color: string
  group?: ServiceGroup
}

export default function Services() {
  const { t } = useI18n()
  const [services, setServices] = useState<ServiceDirectoryItem[]>([])
  const [groups, setGroups] = useState<ServiceGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [newSegmentName, setNewSegmentName] = useState('')
  const [draggedServiceId, setDraggedServiceId] = useState<number | null>(null)
  const [dragOverSection, setDragOverSection] = useState<string | null>(null)
  const [editingGroupId, setEditingGroupId] = useState<number | null>(null)
  const [editingName, setEditingName] = useState('')

  async function load() {
    const [serviceItems, groupItems] = await Promise.all([servicesApi.listAll(), servicesApi.listGroups()])
    setServices(serviceItems)
    setGroups(groupItems)
  }

  useEffect(() => {
    load().finally(() => setLoading(false))
  }, [])

  const filtered = services.filter((service) => {
    const term = search.toLowerCase()
    if (!term) return true
    return [service.name, service.description, service.device_label, service.device_ip, service.service_type, service.service_group_name]
      .some((value) => (value ?? '').toLowerCase().includes(term))
  })

  const grouped = useMemo(() => {
    const map = new Map<string, ServiceDirectoryItem[]>()
    for (const group of groups) map.set(String(group.id), [])
    map.set('ungrouped', [])
    for (const service of filtered) {
      const key = service.service_group_id ? String(service.service_group_id) : 'ungrouped'
      if (!map.has(key)) map.set(key, [])
      map.get(key)?.push(service)
    }
    return map
  }, [filtered, groups])

  const sections: Section[] = [
    ...groups.map((group) => ({ id: String(group.id), name: group.name, color: group.color, group })),
    { id: 'ungrouped', name: t('service_segment_ungrouped'), color: '#64748b' },
  ]

  async function createSegment() {
    const name = newSegmentName.trim()
    if (!name) return
    try {
      await servicesApi.createGroup({ name, sort_order: groups.length })
      setNewSegmentName('')
      await load()
      toast.success(t('service_segment_created'))
    } catch {
      toast.error(t('service_segment_create_failed'))
    }
  }

  function startEditing(group: ServiceGroup) {
    setEditingGroupId(group.id)
    setEditingName(group.name)
  }

  async function saveSegment(groupId: number) {
    const name = editingName.trim()
    if (!name) return
    try {
      await servicesApi.updateGroup(groupId, { name })
      setEditingGroupId(null)
      setEditingName('')
      await load()
      toast.success(t('service_segment_saved'))
    } catch {
      toast.error(t('service_segment_save_failed'))
    }
  }

  async function deleteSegment(groupId: number) {
    if (!window.confirm(t('service_segment_delete_confirm'))) return
    try {
      await servicesApi.deleteGroup(groupId)
      await load()
      toast.success(t('service_segment_deleted'))
    } catch {
      toast.error(t('service_segment_delete_failed'))
    }
  }

  async function moveServiceToSection(sectionId: string) {
    if (draggedServiceId == null) return
    const service = services.find((item) => item.id === draggedServiceId)
    setDraggedServiceId(null)
    setDragOverSection(null)
    if (!service) return

    await moveServiceToGroup(service, sectionId === 'ungrouped' ? null : Number(sectionId))
  }

  async function moveServiceToGroup(service: ServiceDirectoryItem, nextGroupId: number | null) {
    if (service.service_group_id === nextGroupId) return

    const previousServices = services
    setServices((current) => current.map((item) => (
      item.id === service.id
        ? {
            ...item,
            service_group_id: nextGroupId,
            service_group_name: nextGroupId == null ? null : groups.find((group) => group.id === nextGroupId)?.name ?? item.service_group_name,
            service_group_color: nextGroupId == null ? null : groups.find((group) => group.id === nextGroupId)?.color ?? item.service_group_color,
          }
        : item
    )))

    try {
      await servicesApi.update(service.device_id, service.id, { service_group_id: nextGroupId })
      await load()
    } catch {
      setServices(previousServices)
      toast.error(t('failed_to_save_service'))
    }
  }

  if (loading) return <div className="flex justify-center py-16"><Spinner size="lg" /></div>

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-text-base">{t('nav_services')}</h1>
          <p className="text-sm text-text-subtle">{t('services_directory_description')}</p>
        </div>
        <input className="input-field w-72 max-w-full" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t('search_services_placeholder')} />
      </div>

      <Card>
        <div className="flex items-end gap-3 flex-wrap">
          <Input label={t('new_service_segment')} value={newSegmentName} onChange={(e) => setNewSegmentName(e.target.value)} placeholder="Homelab, Monitoring, Media…" />
          <Button onClick={createSegment}>{t('add_segment')}</Button>
        </div>
        <p className="text-xs text-text-subtle mt-3">{t('service_segment_help')}</p>
        <p className="text-xs text-text-subtle mt-1">{t('service_icon_license_note')}</p>
      </Card>

      {filtered.length === 0 ? (
        <Card><p className="text-sm text-text-subtle">{t('no_services_configured')}</p></Card>
      ) : (
        <div className="flex flex-col gap-5">
          {sections.map((section) => {
            const items = grouped.get(section.id) ?? []
            const isDropTarget = dragOverSection === section.id
            return (
              <section
                key={section.id}
                className={`rounded-2xl border p-3 transition-colors ${isDropTarget ? 'border-primary bg-primary/5' : 'border-border/60 bg-surface/30'}`}
                onDragOver={(e) => { e.preventDefault(); setDragOverSection(section.id) }}
                onDragLeave={() => setDragOverSection((current) => current === section.id ? null : current)}
                onDrop={() => moveServiceToSection(section.id)}
              >
                <div className="flex items-center justify-between gap-3 mb-3">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: section.color }} />
                    {editingGroupId === section.group?.id ? (
                      <input className="input-field h-9 max-w-xs" value={editingName} onChange={(e) => setEditingName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && section.group && saveSegment(section.group.id)} autoFocus />
                    ) : (
                      <h2 className="text-sm font-semibold text-text-muted uppercase tracking-wider truncate">{section.name}</h2>
                    )}
                    <span className="text-xs text-text-subtle">{items.length}</span>
                  </div>
                  {section.group && (
                    <div className="flex items-center gap-2 shrink-0">
                      {editingGroupId === section.group.id ? (
                        <>
                          <button className="text-xs text-primary hover:text-primary/80" onClick={() => saveSegment(section.group!.id)}>{t('save')}</button>
                          <button className="text-xs text-text-subtle hover:text-text-base" onClick={() => setEditingGroupId(null)}>{t('cancel')}</button>
                        </>
                      ) : (
                        <>
                          <button className="text-xs text-text-subtle hover:text-primary" onClick={() => startEditing(section.group!)}>{t('edit')}</button>
                          <button className="text-xs text-danger hover:text-danger/80" onClick={() => deleteSegment(section.group!.id)}>{t('delete')}</button>
                        </>
                      )}
                    </div>
                  )}
                </div>

                {items.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-border px-4 py-6 text-sm text-text-subtle text-center">
                    {t('drop_services_here')}
                  </div>
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    {items.map((service) => {
                      const href = service.url || (service.device_ip && service.port ? `${service.protocol}://${service.device_ip}:${service.port}` : null)
                      return (
                        <Card
                          key={service.id}
                          className={`flex flex-col gap-3 cursor-grab active:cursor-grabbing select-none ${draggedServiceId === service.id ? 'opacity-60 ring-1 ring-primary' : ''}`}
                          draggable
                          onDragStart={(e) => {
                            e.dataTransfer.effectAllowed = 'move'
                            setDraggedServiceId(service.id)
                          }}
                          onDragEnd={() => { setDraggedServiceId(null); setDragOverSection(null) }}
                        >
                          <div className="flex items-start gap-3">
                            <ServiceIcon iconKey={service.icon_key} iconUrl={service.icon_url} serviceType={service.service_type} />
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2 flex-wrap">
                                <h2 className="font-semibold text-text-base truncate">{service.name}</h2>
                                <ServiceTypeTag type={service.service_type} />
                              </div>
                              <p className="text-xs text-text-subtle truncate">{SERVICE_TYPE_LABELS[service.service_type] ?? service.service_type} · {service.device_label}</p>
                            </div>
                          </div>
                          {service.description && <p className="text-sm text-text-muted line-clamp-2">{service.description}</p>}
                          <div className="flex items-center gap-2 pt-2 border-t border-border">
                            <label className="text-xs text-text-subtle" htmlFor={`service-group-${service.id}`}>
                              {t('segments')}
                            </label>
                            <select
                              id={`service-group-${service.id}`}
                              className="input-field h-8 text-xs flex-1 min-w-0"
                              value={service.service_group_id ?? 'ungrouped'}
                              onChange={(e) => moveServiceToGroup(service, e.target.value === 'ungrouped' ? null : Number(e.target.value))}
                              onClick={(e) => e.stopPropagation()}
                              onDragStart={(e) => e.preventDefault()}
                            >
                              <option value="ungrouped">{t('service_segment_ungrouped')}</option>
                              {groups.map((group) => (
                                <option key={group.id} value={group.id}>{group.name}</option>
                              ))}
                            </select>
                          </div>
                          <div className="flex items-center justify-between gap-2 pt-2 border-t border-border">
                            <Link to={`/devices/${service.device_id}`} className="text-xs text-text-subtle hover:text-primary">{service.device_ip ?? t('ip_address')} →</Link>
                            {href && <a href={href} target="_blank" rel="noopener noreferrer" className="text-sm font-medium text-primary hover:text-primary/80">{t('open_service')} →</a>}
                          </div>
                        </Card>
                      )
                    })}
                  </div>
                )}
              </section>
            )
          })}
        </div>
      )}
    </div>
  )
}
