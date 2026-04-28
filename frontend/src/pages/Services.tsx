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

export default function Services() {
  const { t } = useI18n()
  const [services, setServices] = useState<ServiceDirectoryItem[]>([])
  const [groups, setGroups] = useState<ServiceGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [newSeparatorName, setNewSeparatorName] = useState('')
  const [draggedServiceId, setDraggedServiceId] = useState<number | null>(null)

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
    for (const service of filtered) map.get(service.service_group_id ? String(service.service_group_id) : 'ungrouped')?.push(service)
    return map
  }, [filtered, groups])

  async function createSeparator() {
    const name = newSeparatorName.trim()
    if (!name) return
    try {
      await servicesApi.createGroup({ name })
      setNewSeparatorName('')
      await load()
      toast.success(t('service_separator_created'))
    } catch {
      toast.error(t('service_separator_create_failed'))
    }
  }

  async function moveService(service: ServiceDirectoryItem, groupId: string) {
    try {
      await servicesApi.update(service.device_id, service.id, { service_group_id: groupId ? Number(groupId) : null })
      await load()
    } catch {
      toast.error(t('failed_to_save_service'))
    }
  }

  async function dropServiceInto(sectionId: string) {
    if (draggedServiceId == null) return
    const service = services.find((item) => item.id === draggedServiceId)
    setDraggedServiceId(null)
    if (!service) return
    await moveService(service, sectionId === 'ungrouped' ? '' : sectionId)
  }

  if (loading) return <div className="flex justify-center py-16"><Spinner size="lg" /></div>

  const sections = [...groups.map((g) => ({ id: String(g.id), name: g.name, color: g.color })), { id: 'ungrouped', name: t('service_separator_ungrouped'), color: '#64748b' }]

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
          <Input label={t('new_service_separator')} value={newSeparatorName} onChange={(e) => setNewSeparatorName(e.target.value)} placeholder="Homelab, Monitoring, Media…" />
          <Button onClick={createSeparator}>{t('add_separator')}</Button>
        </div>
        <p className="text-xs text-text-subtle mt-3">{t('service_separator_help')}</p>
        <p className="text-xs text-text-subtle mt-1">{t('service_icon_license_note')}</p>
      </Card>

      {filtered.length === 0 ? (
        <Card><p className="text-sm text-text-subtle">{t('no_services_configured')}</p></Card>
      ) : sections.map((section) => {
        const items = grouped.get(section.id) ?? []
        if (items.length === 0 && section.id !== 'ungrouped') return null
        return (
          <div
            key={section.id}
            className="flex flex-col gap-3 rounded-xl border border-transparent hover:border-primary/20 transition-colors"
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => dropServiceInto(section.id)}
          >
            <div className="flex items-center gap-2 px-1">
              <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: section.color }} />
              <h2 className="text-sm font-semibold text-text-muted uppercase tracking-wider">{section.name}</h2>
            </div>
            {items.length === 0 ? <Card><p className="text-sm text-text-subtle">{t('no_services_configured')}</p></Card> : (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {items.map((service) => {
                  const href = service.url || (service.device_ip && service.port ? `${service.protocol}://${service.device_ip}:${service.port}` : null)
                  return (
                    <Card
                      key={service.id}
                      className={`flex flex-col gap-3 cursor-grab active:cursor-grabbing ${draggedServiceId === service.id ? 'opacity-60 ring-1 ring-primary' : ''}`}
                      draggable
                      onDragStart={() => setDraggedServiceId(service.id)}
                      onDragEnd={() => setDraggedServiceId(null)}
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
                      <select value={service.service_group_id ?? ''} onChange={(e) => moveService(service, e.target.value)} className="input-field text-xs">
                        <option value="">{t('service_separator_ungrouped')}</option>
                        {groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
                      </select>
                      <div className="flex items-center justify-between gap-2 pt-2 border-t border-border">
                        <Link to={`/devices/${service.device_id}`} className="text-xs text-text-subtle hover:text-primary">{service.device_ip ?? t('ip_address')} →</Link>
                        {href && <a href={href} target="_blank" rel="noopener noreferrer" className="text-sm font-medium text-primary hover:text-primary/80">{t('open_service')} →</a>}
                      </div>
                    </Card>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
