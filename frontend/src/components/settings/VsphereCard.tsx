import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import apiClient from '../../api/client'
import { useI18n } from '../../i18n'

type Config = { auto_scan_enabled: boolean; scan_interval_minutes: number; last_scan_attempt_at: string | null; next_scan_at: string | null; device_field_mappings: Record<string,{target:string;overwrite:boolean}>; read_sysid: boolean; attribute_mappings: Record<string,string>; sysid_field_key: number | null; writeback_sysid: boolean; verify_tls: boolean; visible_fields: string[]; enabled: boolean; endpoint: string; username: string; has_password: boolean; last_discovery_at: string | null }
type Item = { id: number; external_id: string; name: string; device_id: number | null; match_status: string; metadata: Record<string, unknown> }
type Inventory = { total: number; items: Item[] }
type Result = { networks?: number; clusters?: number; datacenters?: number; hosts?: number; vms?: number; host_count?: number; counts?: Record<string, number>; warnings?: string[] }
const control = 'rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-base disabled:opacity-50'
const statuses = {
  existing: 'vsphere_existing', created: 'vsphere_created', unmatched: 'vsphere_unmatched',
  ambiguous: 'vsphere_ambiguous', ignored: 'vsphere_ignored', no_mac: 'vsphere_no_mac', stale: 'vsphere_stale',
} as const

const deviceTargets = ['label','purpose','description','location','responsible','asset_tag','notes','os_info'] as const

const fields = [
  ['host_id','vsphere_host'], ['cluster_id','vsphere_cluster'], ['datacenter_id','vsphere_datacenter'],
  ['power_state','vsphere_state'], ['macs','vsphere_macs'], ['ips','vsphere_ips'], ['guest_os','vsphere_guest_os'],
  ['instance_uuid','vsphere_instance_uuid'], ['bios_uuid','vsphere_bios_uuid'], ['cpu_count','vsphere_cpu'],
  ['memory_size_mib','vsphere_memory'], ['disks','vsphere_disks'],
] as const

export default function VsphereCard() {
  const { t } = useI18n()
  const [config, setConfig] = useState<Config | null>(null)
  const [password, setPassword] = useState('')
  const [customFields, setCustomFields] = useState<{key: number; name: string}[]>([])
  const [customFieldsError, setCustomFieldsError] = useState('')
  const [customFieldsLoading, setCustomFieldsLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<Result | null>(null)
  const [message, setMessage] = useState('')
  const [kind, setKind] = useState<'host'|'vm'|'cluster'|'datacenter'|'network'>('vm')
  const [discovering, setDiscovering] = useState(false)
  const [page, setPage] = useState(0)
  const [inventory, setInventory] = useState<Inventory | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [attributeRefresh, setAttributeRefresh] = useState(0)
  const [hostNames, setHostNames] = useState<Record<string, string>>({})
  const [topologyNames, setTopologyNames] = useState<Record<string, string>>({})
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
  const enabled = !!(config?.enabled && config.endpoint && config.username && config.has_password) && !dirty
  useEffect(() => {
    if (!enabled) {setInventory(null); return}
    let active = true
    apiClient.get<Inventory>('/vsphere/inventory', {params: {kind, offset: page*25, limit:25}})
      .then(r => {if (active) setInventory(r.data)}).catch(e => {if (active) failure(e)})
    apiClient.get<Inventory>('/vsphere/inventory', {params: {kind:'host', limit:100}})
      .then(r => {if (active) setHostNames(Object.fromEntries(r.data.items.map(i => [i.external_id,i.name])))})
      .catch(() => {})
    Promise.all((['cluster','datacenter'] as const).map(k => apiClient.get<Inventory>('/vsphere/inventory', {params:{kind:k,limit:100}})))
      .then(rs=>{if(active) setTopologyNames(Object.fromEntries(rs.flatMap(r=>r.data.items.map(i=>[i.external_id,i.name]))))}).catch(()=>{})
    return () => {active=false}
  }, [enabled, kind, page, refresh])
  useEffect(() => {
    if (!enabled || discovering) return
    let active = true
    setCustomFieldsError(''); setCustomFieldsLoading(true)
    apiClient.get<{key: number; name: string}[]>('/vsphere/custom-fields')
      .then(r => { if (active) setCustomFields(r.data) })
      .catch((e: unknown) => { if (active) {
        const detail = (e as {response?: {data?: {detail?: unknown}}})?.response?.data?.detail
        setCustomFieldsError(typeof detail === 'string' ? detail : t('vsphere_failed'))
      }})
      .finally(() => { if (active) setCustomFieldsLoading(false) })
    return () => { active = false }
  }, [enabled, refresh, discovering, attributeRefresh])
  function edit(patch: Partial<Config>) {
    if (config) setConfig({...config,...patch})
    if ('endpoint' in patch || 'username' in patch) {setCustomFields([]);setCustomFieldsError('')}
    setDirty(true); setResult(null); setMessage('')
  }
  async function save() {
    if (!config) return
    setBusy(true);setError('');setMessage('')
    try {
      const r = await apiClient.put<Config>('/vsphere/config', {
        enabled:config.enabled, auto_scan_enabled:config.auto_scan_enabled, scan_interval_minutes:config.scan_interval_minutes, endpoint:config.endpoint, username:config.username, verify_tls:config.verify_tls, writeback_sysid:config.writeback_sysid, sysid_field_key:config.sysid_field_key, read_sysid:config.read_sysid, attribute_mappings:config.attribute_mappings, device_field_mappings:config.device_field_mappings, visible_fields:config.visible_fields, ...(password ? {password} : {}),
      })
      setConfig(r.data);setPassword('');setDirty(false);setMessage(t('vsphere_saved'));setPage(0);setRefresh(v=>v+1)
    } catch (e) {failure(e)} finally {setBusy(false)}
  }
  useEffect(() => {
    if (!enabled) return
    let active = true
    const poll = async () => {
      try {
        const {data} = await apiClient.get<{status: string; result: Result | null; error: string | null}>('/vsphere/discover/status')
        if (!active) return
        if (discovering && data.status !== 'running') {
          const response = await apiClient.get<Config>('/vsphere/config')
          if (!active) return
          setConfig(response.data)
          if (data.result) {
            setResult(data.result)
            setPage(0); setRefresh(v=>v+1)
          }
          if (data.error) setError(data.error)
        }
        setDiscovering(data.status === 'running')
      } catch (e) { if (active) failure(e) }
    }
    void poll()
    const timer = window.setInterval(poll, 2000)
    return () => {active=false; window.clearInterval(timer)}
  }, [enabled, discovering])
  async function run(action: 'test'|'discover') {
    setBusy(true);setError('');setMessage('');setResult(null)
    try {
      if (action === 'discover') {
        await apiClient.post('/vsphere/discover/start')
        setDiscovering(true)
      } else {
        const r = await apiClient.post<Result>('/vsphere/test')
        setResult(r.data)
      }
    } catch(e){failure(e)} finally {setBusy(false)}
  }
  function renderField(key: string, value: unknown): string {
    if (value === null || value === undefined || value === '') return '—'
    if (typeof value === 'string') return key === 'host_id' ? hostNames[value] || value :
      (key === 'cluster_id' || key === 'datacenter_id') ? topologyNames[value] || value : value
    if (Array.isArray(value)) return value.map(v => typeof v === 'object' && v !== null ?
      [v.label || v.disk_id, v.uuid || '—', typeof v.capacity_bytes === 'number' ? v.capacity_bytes + ' B' : '', v.backing_file].filter(Boolean).join(' · ') : String(v)).join('\n') || '—'
    return String(value)
  }
  if (config && !config.enabled) return <p className="text-sm text-text-muted">{t('vsphere_enable_in_features')}</p>
  return <section className="rounded-xl border border-border bg-surface p-4 space-y-4">
    <h2 className="font-semibold text-text-base">{t('vsphere_title')}</h2><p className="text-sm text-text-muted">{t('vsphere_hint')}</p>
    {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    {config && <>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="text-sm text-text-muted flex flex-col gap-1">{t('vsphere_endpoint')}<input className={control} type="url" value={config.endpoint} maxLength={512} placeholder="https://vcenter.example.test" disabled={busy} onChange={e=>edit({endpoint:e.target.value,verify_tls:true,sysid_field_key:null,writeback_sysid:false,read_sysid:false,attribute_mappings:{},device_field_mappings:{}})}/></label>
        <label className="text-sm text-text-muted flex flex-col gap-1">{t('vsphere_user')}<input className={control} value={config.username} maxLength={255} autoComplete="off" disabled={busy} onChange={e=>edit({username:e.target.value,sysid_field_key:null,writeback_sysid:false,read_sysid:false,attribute_mappings:{},device_field_mappings:{}})}/></label>
        <label className="text-sm text-text-muted flex flex-col gap-1">{t('vsphere_password')}<input className={control} type="password" autoComplete="new-password" value={password} maxLength={4096} disabled={busy} onChange={e=>{setPassword(e.target.value);setDirty(true)}} placeholder={config.has_password?t('vsphere_password_saved'):''}/></label>
      </div>
      <label className="flex gap-2 items-center text-sm text-text-base"><input type="checkbox" checked={!config.verify_tls} disabled={busy} onChange={e=>edit({verify_tls:!e.target.checked})}/>{t('idoit_skip_tls')}</label>
      {!config.verify_tls && <p role="alert" className="text-sm text-warning">{t('idoit_skip_tls_warning')}</p>}
      <label className="flex gap-2 items-center text-sm text-text-base"><input type="checkbox" checked={config.writeback_sysid} disabled={busy||config.sysid_field_key===null} onChange={e=>edit({writeback_sysid:e.target.checked})}/>{t('vsphere_writeback_sysid')}</label>
      <p className="text-xs text-text-muted">{t('vsphere_writeback_hint')}</p>
      <label className="text-sm text-text-muted flex flex-col gap-1">{t('vsphere_sysid_field')}
        <select className={control} value={config.sysid_field_key ?? ''} disabled={busy} onChange={e=>edit({sysid_field_key:e.target.value===''?null:Number(e.target.value), ...(e.target.value===''?{writeback_sysid:false,read_sysid:false}:{})})}>
          <option value="">{t('vsphere_select_field')}</option>
          {config.sysid_field_key!==null && !customFields.some(f=>f.key===config.sysid_field_key) && <option value={config.sysid_field_key}>#{config.sysid_field_key}</option>}
          {customFields.map(f=><option key={f.key} value={f.key}>{f.name}</option>)}
        </select>
      </label>
      <label className="flex gap-2 items-center text-sm text-text-base"><input type="checkbox" checked={config.read_sysid} disabled={busy||config.sysid_field_key===null} onChange={e=>edit({read_sysid:e.target.checked})}/>{t('vsphere_read_sysid')}</label>
      <p className="text-xs text-text-muted">{t('vsphere_read_sysid_hint')}</p>
      <div className="space-y-2 border-t border-border pt-3">
        <h3 className="font-medium text-sm">{t('vsphere_attribute_mapping')}</h3>
        <p className="text-xs text-text-muted">{t('vsphere_attribute_mapping_hint')}</p>
        <p className="text-xs text-text-muted">{t('vsphere_attribute_refresh_hint')}</p>
        <button className={control} disabled={!enabled||busy||discovering||customFieldsLoading} onClick={()=>setAttributeRefresh(v=>v+1)}>{t('vsphere_load_attributes')}</button>
        {customFieldsLoading && enabled && <p className="text-sm text-text-muted">{t('applications_loading')}</p>}
        {enabled && !customFieldsLoading && !customFieldsError && customFields.length===0 && <p className="text-sm text-text-muted">{t('vsphere_no_attributes')}</p>}
        {customFieldsError && <p role="alert" className="text-sm text-warning">{customFieldsError}</p>}
        {customFields.map(field => <div key={field.key} className="flex flex-wrap gap-2 items-center border-b border-border pb-2">
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={String(field.key) in config.attribute_mappings} disabled={busy} onChange={e=>{
            const next = {...config.attribute_mappings}
            if(e.target.checked) next[String(field.key)] = field.name
            else delete next[String(field.key)]
            edit({attribute_mappings:next})
          }}/>{field.name}</label>
          {String(field.key) in config.attribute_mappings && <input className={control} aria-label={field.name} maxLength={100} value={config.attribute_mappings[String(field.key)]} onChange={e=>edit({attribute_mappings:{...config.attribute_mappings,[String(field.key)]:e.target.value}})} />}
          <label className="flex flex-col gap-1 text-xs text-text-muted">
            {t('vsphere_lanlens_target')}
            <select className={control} disabled={busy||discovering} value={config.read_sysid && config.sysid_field_key===field.key ? 'idoit_sysid' : config.device_field_mappings[String(field.key)]?.target ?? ''} onChange={e=>{
              const key=String(field.key), target=e.target.value
              const mappings={...config.device_field_mappings}
              delete mappings[key]
              if(target==='idoit_sysid') {
                edit({device_field_mappings:mappings, read_sysid:true, sysid_field_key:field.key})
              } else {
                if(target) mappings[key]={target,overwrite:false}
                edit({device_field_mappings:mappings, ...(config.read_sysid && config.sysid_field_key===field.key ? {read_sysid:false} : {})})
              }
            }}>
              <option value="">{t('vsphere_no_target')}</option>
              <option value="idoit_sysid" disabled={config.sysid_field_key!==null && config.sysid_field_key!==field.key && (config.writeback_sysid||config.read_sysid)}>i-doit SYSID</option>
              {deviceTargets.map(target=><option key={target} value={target} disabled={Object.entries(config.device_field_mappings).some(([key,rule])=>key!==String(field.key)&&rule.target===target)}>{t(target)}</option>)}
            </select>
          </label>
          {config.device_field_mappings[String(field.key)] && !(config.read_sysid && config.sysid_field_key===field.key) && <label className="flex items-center gap-2 text-xs text-text-muted"><input type="checkbox" disabled={busy||discovering} checked={config.device_field_mappings[String(field.key)].overwrite} onChange={e=>edit({device_field_mappings:{...config.device_field_mappings,[String(field.key)]:{...config.device_field_mappings[String(field.key)],overwrite:e.target.checked}}})}/>{t('vsphere_overwrite')}</label>}
        </div>)}
        <p className="text-xs text-text-muted">{t('vsphere_target_hint')}</p>
      </div>
      <div className="space-y-2">
        <h3 className="font-medium text-sm">{t('vsphere_fields')}</h3>
        <p className="text-xs text-text-muted">{t('vsphere_fields_hint')}</p>
        <div className="grid gap-2 md:grid-cols-3">{fields.map(([key,label])=><label key={key} className="flex gap-2 items-center text-sm">
          <input type="checkbox" checked={config.visible_fields.includes(key)} disabled={busy} onChange={e=>edit({visible_fields:e.target.checked ? [...config.visible_fields,key] : config.visible_fields.filter(v=>v!==key)})}/>{t(label)}
        </label>)}</div>
        <button className={control} disabled={busy} onClick={()=>edit({visible_fields:fields.map(([key])=>key)})}>{t('vsphere_reset_fields')}</button>
      </div>
      <div className="space-y-2 border-t border-border pt-3">
        <h3 className="font-medium text-sm">{t('vsphere_scan_schedule')}</h3>
        <label className="flex gap-2 items-center text-sm"><input type="checkbox" checked={config.auto_scan_enabled} disabled={busy||discovering} onChange={e=>edit({auto_scan_enabled:e.target.checked})}/>{t('vsphere_auto_scan')}</label>
        <label className="text-sm text-text-muted flex flex-col gap-1 max-w-xs">{t('vsphere_interval_minutes')}
          <input className={control} type="number" min={5} max={10080} step={1} value={config.scan_interval_minutes} disabled={busy||discovering||!config.auto_scan_enabled} onChange={e=>edit({scan_interval_minutes:Number(e.target.value)})}/>
        </label>
        <p className="text-xs text-text-muted">{t('vsphere_schedule_hint')}</p>
        {!dirty && config.auto_scan_enabled && config.next_scan_at && <p className="text-xs text-text-muted">{t('vsphere_next_scan')}: {new Date(config.next_scan_at).toLocaleString()}</p>}
        {config.last_scan_attempt_at && <p className="text-xs text-text-muted">{t('vsphere_last_attempt')}: {new Date(config.last_scan_attempt_at).toLocaleString()}</p>}
      </div>
      <div className="flex flex-wrap gap-2">
        <button className={control} disabled={busy||discovering||!Number.isInteger(config.scan_interval_minutes)||config.scan_interval_minutes<5||config.scan_interval_minutes>10080} onClick={save}>{t('save_changes')}</button>
        <button className={control} disabled={busy||discovering||!enabled} onClick={()=>run('test')}>{t('vsphere_test')}</button>
        <button className={control} disabled={busy||discovering||!enabled} onClick={()=>run('discover')}>{t('vsphere_discover')}</button>
      </div>
      {message && <p className="text-sm text-success">{message}</p>}
      {(busy || discovering) && <p className="text-sm text-text-muted">{t('applications_loading')}</p>}
      {result && <div className="text-sm text-text-muted space-y-1">
        <p>{t('vsphere_hosts')}: {result.hosts ?? result.host_count ?? '—'} · {t('vsphere_vms')}: {result.vms ?? '—'} · {t('vsphere_cluster')}: {result.clusters ?? '—'} · {t('vsphere_datacenter')}: {result.datacenters ?? '—'} · {t('vsphere_networks')}: {result.networks ?? '—'}</p>
        {Object.entries(result.counts??{}).map(([k,v])=><p key={k}>{k in statuses?t(statuses[k as keyof typeof statuses]):k}: {v}</p>)}
        {result.warnings?.map((w,i)=><p key={i} className="text-warning">{w}</p>)}
      </div>}
      {enabled && <>
        {result?.host_count !== undefined && !config.last_discovery_at && <p className="text-sm text-text-muted">{t('vsphere_run_discovery')}</p>}
        {config.last_discovery_at && <p className="text-xs text-text-muted">{t('vsphere_last_scan')}: {new Date(config.last_discovery_at).toLocaleString()}</p>}
        <div className="flex gap-2">{(['host','vm','cluster','datacenter','network'] as const).map(k=><button key={k} className={control+(kind===k?' border-primary text-primary':'')} aria-pressed={kind===k} onClick={()=>{setKind(k);setPage(0);setInventory(null)}}>{t(k==='host'?'vsphere_hosts':k==='vm'?'vsphere_vms':k==='cluster'?'vsphere_cluster':k==='network'?'vsphere_networks':'vsphere_datacenter')}</button>)}</div>
        {inventory?.total===0 && <p className="text-sm text-text-muted">{config.last_discovery_at ? t('vsphere_no_results') : t('vsphere_run_discovery')}</p>}
        {!!inventory?.items.length && <div className="overflow-x-auto"><table className="w-full text-sm text-left"><thead className="text-text-muted"><tr>
          <th className="p-2">{t('col_device')}</th>{fields.filter(([key])=>config.visible_fields.includes(key)).map(([key,label])=><th className="p-2" key={key}>{t(label)}</th>)}{kind==='vm' && Object.entries(config.attribute_mappings).map(([key,label])=><th className="p-2" key={'attr-'+key}>{label}</th>)}<th className="p-2">{t('vsphere_match')}</th>
        </tr></thead><tbody className="divide-y divide-border">{inventory.items.map(i=><tr key={i.id}>
          <td className="p-2">{i.device_id ? <Link className="text-primary hover:underline" to={'/devices/'+i.device_id}>{i.name}</Link>:i.name}</td>
          {fields.filter(([key])=>config.visible_fields.includes(key)).map(([key])=><td key={key} className="p-2 text-text-muted whitespace-pre-wrap break-words min-w-24">{renderField(key,i.metadata[key])}</td>)}
          {kind==='vm' && Object.keys(config.attribute_mappings).map(key=><td className="p-2 text-text-muted whitespace-pre-wrap break-words" key={'attr-'+key}>{renderField(key,(i.metadata.attributes as Record<string,unknown> | undefined)?.[key])}</td>)}
          <td className="p-2">{i.match_status in statuses?t(statuses[i.match_status as keyof typeof statuses]):i.match_status}</td>
        </tr>)}</tbody></table></div>}
        {inventory && <div className="flex gap-2 items-center text-sm"><button className={control} disabled={page===0} onClick={()=>setPage(v=>v-1)}>{t('vsphere_previous')}</button><span>{page+1} / {Math.max(1,Math.ceil(inventory.total/25))}</span><button className={control} disabled={(page+1)*25>=inventory.total} onClick={()=>setPage(v=>v+1)}>{t('vsphere_next')}</button></div>}
      </>}
    </>}
  </section>
}
