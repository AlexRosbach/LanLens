import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { inventoryApi, type ApplicationInventory, type ApplicationProduct, type ApplicationFilters, type ApplicationDevice } from '../api/inventory'
import { useI18n } from '../i18n'
import { useUiSettingsStore } from '../store/uiSettingsStore'

const PAGE_SIZE = 25
const EMPTY_FILTERS: ApplicationFilters = { search: '', device: '', application: '', publisher: '', version: '', architecture: '', device_class: '', source: '' }
const FILTER_KEYS = ['device', 'application', 'publisher', 'version', 'architecture', 'device_class', 'source'] as const
const control = 'rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-base disabled:opacity-40'

export default function Applications() {
  const { t } = useI18n()
  const enabled = useUiSettingsStore(s => s.advancedViewEnabled && s.showApplicationsNav)
  const fetchSettings = useUiSettingsStore(s => s.fetchUiSettings)
  const [ready, setReady] = useState(false)
  const [filters, setFilters] = useState<ApplicationFilters>(EMPTY_FILTERS)
  const [applied, setApplied] = useState<ApplicationFilters>(EMPTY_FILTERS)
  const filterLabels = {
    device: t('applications_filter_device'),
    application: t('nav_applications'),
    publisher: t('applications_publisher'),
    version: t('applications_versions'),
    architecture: t('applications_architecture'),
    device_class: t('applications_filter_class'),
    source: t('applications_filter_source'),
  }
  const [page, setPage] = useState(0)
  const [refresh, setRefresh] = useState(0)
  const [data, setData] = useState<ApplicationInventory | null>(null)
  const [groupBy, setGroupBy] = useState<'application' | 'device'>('application')
  const [selected, setSelected] = useState<ApplicationProduct | null>(null)
  const [selectedDevice, setSelectedDevice] = useState<ApplicationDevice | null>(null)
  function clearSelection() {
    setSelected(null); setSelectedDevice(null); setDetail(null); setDetailPage(0)
  }
  const [detailPage, setDetailPage] = useState(0)
  const [detail, setDetail] = useState<ApplicationInventory | null>(null)
  const [loading, setLoading] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState(false)
  const [detailError, setDetailError] = useState(false)

  useEffect(() => {
    let active = true
    fetchSettings().catch(() => {}).finally(() => { if (active) setReady(true) })
    return () => { active = false }
  }, [fetchSettings])
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setApplied(filters)
      setPage(0)
      clearSelection()
    }, 300)
    return () => window.clearTimeout(timer)
  }, [filters])
  useEffect(() => {
    if (!ready || !enabled) return
    let active = true
    setLoading(true); setError(false)
    inventoryApi.applications({...applied, group_by: groupBy, offset: page * PAGE_SIZE, limit: PAGE_SIZE})
      .then(r => { if (active) setData(r) })
      .catch(() => { if (active) { setError(true); setData(null) } })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [ready, enabled, applied, page, refresh, groupBy])
  useEffect(() => {
    if (!ready || !enabled || (!selected && !selectedDevice)) return
    let active = true
    setDetail(null); setDetailLoading(true); setDetailError(false)
    inventoryApi.applications({...applied, application_id: selected?.id, selected_device_id: selectedDevice?.id, offset: detailPage * PAGE_SIZE, limit: PAGE_SIZE})
      .then(r => { if (active) setDetail(r) })
      .catch(() => { if (active) setDetailError(true) })
      .finally(() => { if (active) setDetailLoading(false) })
    return () => { active = false }
  }, [ready, enabled, selected, selectedDevice, detailPage, refresh, applied])

  if (!ready) return <p className="text-text-muted">{t('applications_loading')}</p>
  if (!enabled) return <p className="text-text-muted">{t('applications_disabled')} <Link className="text-primary" to="/settings">{t('nav_settings')}</Link></p>
  return <div className="space-y-5">
    <div><h1 className="text-xl font-bold text-text-base">{t('nav_applications')}</h1><p className="text-sm text-text-muted">{t('show_applications_nav_hint')}</p></div>
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      {[[t('applications_products'), data?.product_count], [t('applications_devices'), data?.device_count], [t('applications_installations'), data?.installation_count]].map(([label, count]) =>
        <div key={label} className="rounded-xl border border-border bg-surface p-4"><p className="text-xs text-text-muted">{label}</p><p className="text-2xl font-semibold text-text-base">{count ?? '—'}</p></div>)}
    </div>
    <section className="rounded-xl border border-border bg-surface p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-semibold text-text-base">{t('applications_filters')}</h2>
        <div className="ml-auto flex gap-2">
          <button className={control} disabled={!Object.values(filters).some(Boolean)} onClick={() => setFilters(EMPTY_FILTERS)}>{t('applications_reset_filters')}</button>
          <button className={control} onClick={() => setRefresh(v => v + 1)}>{t('applications_refresh')}</button>
        </div>
      </div>
      <input className={control + ' w-full'} aria-label={t('applications_search')} placeholder={t('applications_search')} maxLength={200} value={filters.search} onChange={e => setFilters(prev => ({...prev, search: e.target.value}))} />
      <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 xl:grid-cols-4">
        {FILTER_KEYS.map(key => <label key={key} className="flex flex-col gap-1 text-xs text-text-muted">
          {filterLabels[key]}
          <input className={control + ' w-full'} value={filters[key]} maxLength={200} onChange={e => setFilters(prev => ({...prev, [key]: e.target.value}))} />
        </label>)}
      </div>
    </section>
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm text-text-muted">{t('applications_group_by')}</span>
      {(['application', 'device'] as const).map(mode => <button key={mode} aria-pressed={groupBy === mode}
        className={control + (groupBy === mode ? ' border-primary text-primary' : '')}
        onClick={() => {setGroupBy(mode); setPage(0); setData(null); clearSelection()}}>
        {t(mode === 'application' ? 'nav_applications' : 'applications_group_devices')}
      </button>)}
    </div>
    {error && <p role="alert" className="text-danger">{t('applications_load_failed')}</p>}
    {loading && <p className="text-text-muted">{t('applications_loading')}</p>}
    {!loading && !error && data?.total === 0 && <p className="text-text-muted">{t('applications_empty')}</p>}
    {groupBy === 'device' && !!data?.devices.length && <div className="rounded-xl border border-border bg-surface overflow-x-auto">
      <table className="w-full text-left text-sm"><thead className="text-text-muted"><tr>
        {[t('col_device'), 'IP', t('applications_filter_class'), t('applications_products'), t('applications_installations')].map(h => <th className="p-3" key={h}>{h}</th>)}
      </tr></thead><tbody className="divide-y divide-border">{data.devices.map(d => <tr key={d.id}>
        <td className="p-3"><button className="text-primary font-medium text-left hover:underline" aria-expanded={selectedDevice?.id === d.id}
          onClick={() => {setSelectedDevice(selectedDevice?.id === d.id ? null : d); setSelected(null); setDetail(null); setDetailPage(0)}}>{selectedDevice?.id === d.id ? '▾ ' : '▸ '}{d.name}</button></td>
        <td className="p-3 text-text-muted">{d.ip_address || '—'}</td><td className="p-3 text-text-muted">{d.device_class || '—'}</td>
        <td className="p-3 text-text-base">{d.product_count}</td><td className="p-3 text-text-base">{d.installation_count}</td>
      </tr>)}</tbody></table></div>}
    {groupBy === 'application' && !!data?.products.length && <div className="rounded-xl border border-border bg-surface overflow-x-auto">
      <table className="w-full text-sm text-left"><thead className="text-text-muted"><tr>
        {[t('nav_applications'), t('applications_publisher'), t('applications_versions'), t('applications_installations')].map(h => <th className="p-3" key={h}>{h}</th>)}
      </tr></thead><tbody className="divide-y divide-border">{data.products.map(p => <tr key={p.id}>
        <td className="p-3"><button className="text-primary font-medium text-left hover:underline" aria-expanded={selected?.id === p.id} onClick={() => {setSelected(selected?.id === p.id ? null : p); setSelectedDevice(null); setDetail(null); setDetailPage(0)}}>{selected?.id === p.id ? '▾ ' : '▸ '}{p.name}</button></td>
        <td className="p-3 text-text-muted">{p.publisher || '—'}</td>
        <td className="p-3 text-text-muted">{p.versions.slice(0, 5).join(', ') || '—'}{p.versions.length > 5 && ' …'}</td>
        <td className="p-3 text-text-base">{p.installation_count} / {p.device_count} {t('col_device')}</td>
      </tr>)}</tbody></table></div>}
    {data && <div className="flex items-center gap-3 text-sm text-text-muted">
      <button className={control} disabled={loading || page === 0} onClick={() => {setPage(p => p-1); clearSelection()}}>{t('applications_previous')}</button>
      <span>{t('applications_page')} {page + 1} / {Math.max(1, Math.ceil(data.total / PAGE_SIZE))}</span>
      <button className={control} disabled={loading || (page+1)*PAGE_SIZE >= data.total} onClick={() => {setPage(p => p+1); clearSelection()}}>{t('applications_next')}</button>
    </div>}
    {selectedDevice && <section className="rounded-xl border border-border bg-surface p-4 space-y-3">
      <div className="flex items-center justify-between"><h2 className="font-semibold text-text-base"><Link className="text-primary hover:underline" to={'/devices/' + selectedDevice.id}>{selectedDevice.name}</Link> — {t('nav_applications')}</h2><button aria-label="Close" className={control} onClick={clearSelection}>×</button></div>
      {detailLoading && <p className="text-text-muted">{t('applications_loading')}</p>}
      {detailError && <p role="alert" className="text-danger">{t('applications_load_failed')}</p>}
      {detail && <><div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-text-muted"><tr>
        {[t('nav_applications'), t('applications_publisher'), t('applications_versions'), t('applications_installations')].map(h => <th key={h} className="p-2">{h}</th>)}
      </tr></thead><tbody className="divide-y divide-border">{detail.products.map(p => <tr key={p.id}>
        <td className="p-2 text-text-base">{p.name}</td><td className="p-2 text-text-muted">{p.publisher || '—'}</td><td className="p-2 text-text-muted">{p.versions.join(', ') || '—'}</td><td className="p-2 text-text-base">{p.installation_count}</td>
      </tr>)}</tbody></table></div>
      <div className="flex gap-3 items-center text-sm text-text-muted"><button className={control} disabled={detailPage===0} onClick={() => setDetailPage(p=>p-1)}>{t('applications_previous')}</button><span>{detailPage+1} / {Math.max(1, Math.ceil(detail.total/PAGE_SIZE))}</span><button className={control} disabled={(detailPage+1)*PAGE_SIZE>=detail.total} onClick={() => setDetailPage(p=>p+1)}>{t('applications_next')}</button></div></>}
    </section>}
    {selected && <section className="rounded-xl border border-border bg-surface p-4 space-y-3">
      <div className="flex items-center justify-between"><h2 className="font-semibold text-text-base">{selected.name} — {t('applications_installations')}</h2><button aria-label="Close" className={control} onClick={() => setSelected(null)}>×</button></div>
      {detailError && <p role="alert" className="text-danger">{t('applications_load_failed')}</p>}
      {detailLoading && <p className="text-text-muted">{t('applications_loading')}</p>}
      {detail && <><div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead className="text-text-muted"><tr>
        {[t('col_device'), 'IP', t('applications_versions'), t('applications_architecture'), t('applications_observed')].map(h => <th key={h} className="p-2">{h}</th>)}
      </tr></thead><tbody className="divide-y divide-border">{detail.installations.map((i, n) => <tr key={n}>
        <td className="p-2"><Link className="text-primary hover:underline" to={'/devices/' + i.device_id}>{i.device_name}</Link></td>
        <td className="p-2 text-text-muted">{i.ip_address || '—'}</td><td className="p-2 text-text-base">{i.version || '—'}</td><td className="p-2 text-text-muted">{i.architecture || '—'}</td>
        <td className="p-2 text-text-muted">{i.observed_at ? new Date(i.observed_at).toLocaleString() : '—'}</td>
      </tr>)}</tbody></table></div>
      <div className="flex gap-3 items-center text-sm text-text-muted"><button className={control} disabled={detailPage===0} onClick={() => setDetailPage(p=>p-1)}>{t('applications_previous')}</button><span>{detailPage+1} / {Math.max(1, Math.ceil(detail.total/PAGE_SIZE))}</span><button className={control} disabled={(detailPage+1)*PAGE_SIZE>=detail.total} onClick={() => setDetailPage(p=>p+1)}>{t('applications_next')}</button></div></>}
    </section>}
  </div>
}
