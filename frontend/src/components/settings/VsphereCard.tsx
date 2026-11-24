import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import apiClient from '../../api/client'
import { useI18n } from '../../i18n'

type Config = { verify_tls: boolean; visible_fields: string[]; enabled: boolean; endpoint: string; username: string; has_password: boolean; last_discovery_at: string | null }
type Item = { id: number; external_id: string; name: string; device_id: number | null; match_status: string; metadata: { host_id?: string; power_state?: string; macs?: string[]; ips?: string[]; guest_os?: string } }
type Inventory = { total: number; items: Item[] }
type Result = { hosts?: number; vms?: number; host_count?: number; counts?: Record<string, number>; warnings?: string[] }
const control = 'rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-base disabled:opacity-50'
const statuses = {
  existing: 'vsphere_existing', created: 'vsphere_created', unmatched: 'vsphere_unmatched',
  ambiguous: 'vsphere_ambiguous', ignored: 'vsphere_ignored', no_mac: 'vsphere_no_mac', stale: 'vsphere_stale',
} as const

export default function VsphereCard({featureOnly = false}: {featureOnly?: boolean}) {
  const { t } = useI18n()
  const [config, setConfig] = useState<Config | null>(null)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<Result | null>(null)
  const [message, setMessage] = useState('')
  const [kind, setKind] = useState<'host'|'vm'>('vm')
  const [page, setPage] = useState(0)
  const [inventory, setInventory] = useState<Inventory | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [hostNames, setHostNames] = useState<Record<string, string>>({})
  const failure = (e: unknown) => {
    const detail = (e as {response?: {data?: {detail?: unknown}}})?.response?.data?.detail
    setError(typeof detail === 'string' ? detail : t('vsphere_failed'))
  }
  useEffect(() => {
    let active = true
    apiClient.get<Config>('/vsphere/config').then(r => {if (active) setConfig(r.data)})
      .catch(e => {if (active) failure(e)})
    return () => {active = false}
  }, [])
  const enabled = !!config?.enabled && !dirty
  useEffect(() => {
    if (!enabled || featureOnly) {setInventory(null); return}
    let active = true
    apiClient.get<Inventory>('/vsphere/inventory', {params: {kind, offset: page*25, limit:25}})
      .then(r => {if (active) setInventory(r.data)}).catch(e => {if (active) failure(e)})
    apiClient.get<Inventory>('/vsphere/inventory', {params: {kind:'host', limit:100}})
      .then(r => {if (active) setHostNames(Object.fromEntries(r.data.items.map(i => [i.external_id,i.name])))})
      .catch(() => {})
    return () => {active=false}
  }, [enabled, featureOnly, kind, page, refresh])
  function edit(patch: Partial<Config>) {
    if (config) setConfig({...config,...patch})
    setDirty(true); setResult(null); setMessage('')
  }
  async function save() {
    if (!config) return
    setBusy(true);setError('');setMessage('')
    try {
      const r = await apiClient.put<Config>('/vsphere/config', {
        enabled:config.enabled, endpoint:config.endpoint, username:config.username, verify_tls:config.verify_tls, visible_fields:config.visible_fields, ...(password ? {password} : {}),
      })
      setConfig(r.data);setPassword('');setDirty(false);setMessage(t('vsphere_saved'));setPage(0);setRefresh(v=>v+1)
    } catch (e) {failure(e)} finally {setBusy(false)}
  }
  async function run(action: 'test'|'discover') {
    setBusy(true);setError('');setMessage('');setResult(null)
    try {
      const r = await apiClient.post<Result>('/vsphere/'+action)
      setResult(r.data)
      if(action==='discover') {
        setConfig((await apiClient.get<Config>('/vsphere/config')).data)
        setPage(0);setRefresh(v=>v+1)
      }
    } catch(e){failure(e)} finally {setBusy(false)}
  }
  async function toggleFeature(value: boolean) {
    setBusy(true);setError('')
    try {setConfig((await apiClient.put<Config>('/vsphere/enabled',{enabled:value})).data)}
    catch(e){failure(e)} finally {setBusy(false)}
  }
  if (featureOnly) return <section className="rounded-xl border border-border bg-surface p-4 space-y-2">
    <h3 className="font-semibold text-text-base">{t('vsphere_title')}</h3>
    <p className="text-sm text-text-muted">{t('vsphere_hint')}</p>
    {config && <label className="flex gap-2 items-center text-sm text-text-base"><input type="checkbox" checked={config.enabled} disabled={busy} onChange={e=>toggleFeature(e.target.checked)}/>{t('vsphere_enable')}</label>}
    {error && <p role="alert" className="text-sm text-danger">{error}</p>}
  </section>
  return <section className="rounded-xl border border-border bg-surface p-4 space-y-4">
    <h2 className="font-semibold text-text-base">{t('vsphere_title')}</h2><p className="text-sm text-text-muted">{t('vsphere_hint')}</p>
    {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    {config && <>
      <label className="flex gap-2 items-center text-sm text-text-base"><input type="checkbox" checked={config.enabled} disabled={busy} onChange={e=>edit({enabled:e.target.checked})}/>{t('vsphere_enable')}</label>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="text-sm text-text-muted flex flex-col gap-1">{t('vsphere_endpoint')}<input className={control} type="url" value={config.endpoint} maxLength={512} placeholder="https://vcenter.example.test" disabled={busy} onChange={e=>edit({endpoint:e.target.value,verify_tls:true})}/></label>
        <label className="text-sm text-text-muted flex flex-col gap-1">{t('vsphere_user')}<input className={control} value={config.username} maxLength={255} autoComplete="off" disabled={busy} onChange={e=>edit({username:e.target.value})}/></label>
        <label className="text-sm text-text-muted flex flex-col gap-1">{t('vsphere_password')}<input className={control} type="password" autoComplete="new-password" value={password} maxLength={4096} disabled={busy} onChange={e=>{setPassword(e.target.value);setDirty(true)}} placeholder={config.has_password?t('vsphere_password_saved'):''}/></label>
      </div>
      <label className="flex gap-2 items-center text-sm text-text-base"><input type="checkbox" checked={!config.verify_tls} disabled={busy} onChange={e=>edit({verify_tls:!e.target.checked})}/>{t('idoit_skip_tls')}</label>
      {!config.verify_tls && <p role="alert" className="text-sm text-warning">{t('idoit_skip_tls_warning')}</p>}
      <div className="flex flex-wrap gap-2">
        <button className={control} disabled={busy} onClick={save}>{t('save_changes')}</button>
        <button className={control} disabled={busy||!enabled} onClick={()=>run('test')}>{t('vsphere_test')}</button>
        <button className={control} disabled={busy||!enabled} onClick={()=>run('discover')}>{t('vsphere_discover')}</button>
      </div>
      {message && <p className="text-sm text-success">{message}</p>}
      {busy && <p className="text-sm text-text-muted">{t('applications_loading')}</p>}
      {result && <div className="text-sm text-text-muted space-y-1">
        <p>{t('vsphere_hosts')}: {result.hosts ?? result.host_count ?? '—'} · {t('vsphere_vms')}: {result.vms ?? '—'}</p>
        {Object.entries(result.counts??{}).map(([k,v])=><p key={k}>{k in statuses?t(statuses[k as keyof typeof statuses]):k}: {v}</p>)}
        {result.warnings?.map((w,i)=><p key={i} className="text-warning">{w}</p>)}
      </div>}
      {enabled && <>
        {config.last_discovery_at && <p className="text-xs text-text-muted">{t('vsphere_last_scan')}: {new Date(config.last_discovery_at).toLocaleString()}</p>}
        <div className="flex gap-2">{(['host','vm'] as const).map(k=><button key={k} className={control+(kind===k?' border-primary text-primary':'')} aria-pressed={kind===k} onClick={()=>{setKind(k);setPage(0);setInventory(null)}}>{t(k==='host'?'vsphere_hosts':'vsphere_vms')}</button>)}</div>
        {inventory?.total===0 && <p className="text-sm text-text-muted">{t('vsphere_no_results')}</p>}
        {!!inventory?.items.length && <div className="overflow-x-auto"><table className="w-full text-sm text-left"><thead className="text-text-muted"><tr>
          <th className="p-2">{t('col_device')}</th><th className="p-2">{t('vsphere_host')}</th><th className="p-2">MAC / IP</th><th className="p-2">{t('vsphere_state')}</th><th className="p-2">{t('vsphere_match')}</th>
        </tr></thead><tbody className="divide-y divide-border">{inventory.items.map(i=><tr key={i.id}>
          <td className="p-2">{i.device_id ? <Link className="text-primary hover:underline" to={'/devices/'+i.device_id}>{i.name}</Link>:i.name}<div className="text-xs text-text-subtle">{i.metadata.guest_os}</div></td>
          <td className="p-2 text-text-muted">{i.metadata.host_id ? hostNames[i.metadata.host_id]||i.metadata.host_id : '—'}</td>
          <td className="p-2 text-text-muted">{i.metadata.macs?.join(', ')||'—'}<div>{i.metadata.ips?.join(', ')}</div></td><td className="p-2 text-text-muted">{i.metadata.power_state||'—'}</td>
          <td className="p-2">{i.match_status in statuses?t(statuses[i.match_status as keyof typeof statuses]):i.match_status}</td>
        </tr>)}</tbody></table></div>}
        {inventory && <div className="flex gap-2 items-center text-sm"><button className={control} disabled={page===0} onClick={()=>setPage(v=>v-1)}>{t('vsphere_previous')}</button><span>{page+1} / {Math.max(1,Math.ceil(inventory.total/25))}</span><button className={control} disabled={(page+1)*25>=inventory.total} onClick={()=>setPage(v=>v+1)}>{t('vsphere_next')}</button></div>}
      </>}
    </>}
  </section>
}
