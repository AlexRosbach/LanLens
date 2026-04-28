import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { servicesApi, type ServiceDirectoryItem, SERVICE_TYPE_LABELS } from '../api/services'
import Card from '../components/ui/Card'
import Spinner from '../components/ui/Spinner'
import ServiceIcon, { ServiceTypeTag } from '../components/devices/ServiceIcon'
import { useI18n } from '../i18n'

export default function Services() {
  const { t } = useI18n()
  const [services, setServices] = useState<ServiceDirectoryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')

  useEffect(() => {
    servicesApi.listAll().then(setServices).finally(() => setLoading(false))
  }, [])

  const filtered = services.filter((service) => {
    const term = search.toLowerCase()
    if (!term) return true
    return [service.name, service.description, service.device_label, service.device_ip, service.service_type]
      .some((value) => (value ?? '').toLowerCase().includes(term))
  })

  if (loading) return <div className="flex justify-center py-16"><Spinner size="lg" /></div>

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-text-base">{t('nav_services')}</h1>
          <p className="text-sm text-text-subtle">{t('services_directory_description')}</p>
        </div>
        <input
          className="input-field w-72 max-w-full"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('search_services_placeholder')}
        />
      </div>

      {filtered.length === 0 ? (
        <Card>
          <p className="text-sm text-text-subtle">{t('no_services_configured')}</p>
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((service) => {
            const href = service.url || (service.device_ip && service.port ? `${service.protocol}://${service.device_ip}:${service.port}` : null)
            return (
              <Card key={service.id} className="flex flex-col gap-3">
                <div className="flex items-start gap-3">
                  <ServiceIcon iconKey={service.icon_key} serviceType={service.service_type} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h2 className="font-semibold text-text-base truncate">{service.name}</h2>
                      <ServiceTypeTag type={service.service_type} />
                    </div>
                    <p className="text-xs text-text-subtle truncate">
                      {SERVICE_TYPE_LABELS[service.service_type] ?? service.service_type} · {service.device_label}
                    </p>
                  </div>
                </div>
                {service.description && <p className="text-sm text-text-muted line-clamp-2">{service.description}</p>}
                <div className="flex items-center justify-between gap-2 pt-2 border-t border-border">
                  <Link to={`/devices/${service.device_id}`} className="text-xs text-text-subtle hover:text-primary">
                    {service.device_ip ?? t('ip_address')} →
                  </Link>
                  {href && (
                    <a href={href} target="_blank" rel="noopener noreferrer" className="text-sm font-medium text-primary hover:text-primary/80">
                      {t('open_service')} →
                    </a>
                  )}
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
