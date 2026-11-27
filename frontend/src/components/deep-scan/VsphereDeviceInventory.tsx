import type { VsphereDeviceObservation } from '../../api/devices'
import { useI18n } from '../../i18n'

const labels = {host_id:'vsphere_host',cluster_id:'vsphere_cluster',datacenter_id:'vsphere_datacenter',power_state:'vsphere_state',macs:'vsphere_macs',ips:'vsphere_ips',guest_os:'vsphere_guest_os',instance_uuid:'vsphere_instance_uuid',bios_uuid:'vsphere_bios_uuid',cpu_count:'vsphere_cpu',memory_size_mib:'finding_memory',disks:'vsphere_disks'} as const

export default function VsphereDeviceInventory({observations}:{observations: VsphereDeviceObservation[]}) {
  const {t} = useI18n()
  return <div className="space-y-3 mb-3">{observations.map(row=><div key={row.external_id} className="rounded-lg border border-border p-3 space-y-2">
    <div className="flex flex-wrap items-center justify-between gap-2"><strong className="text-sm">VMware / vSphere · {row.name}</strong><span className="text-xs text-text-muted">{new Date(row.observed_at).toLocaleString()} · {row.match_status==='stale'?t('vsphere_stale'):t('vsphere_existing')}</span></div>
    <dl className="grid gap-2 sm:grid-cols-2">{Object.entries(row.fields).map(([key,value])=><div key={key} className="min-w-0">
      <dt className="text-xs text-text-muted">{key in labels?t(labels[key as keyof typeof labels]):key}</dt>
      <dd className="text-sm break-words">{key==='memory_size_mib' && typeof value==='number'? (value/1024).toFixed(2)+' GiB':Array.isArray(value) && key==='disks'?<div className="space-y-1">{value.map((disk,i)=><div key={i} className="text-xs border-b border-border py-1">{String(disk.label||disk.disk_id)} · {typeof disk.capacity_bytes==='number'?(disk.capacity_bytes/1073741824).toFixed(2)+' GiB':'—'}{disk.uuid && <div className="font-mono break-all">{disk.uuid}</div>}{disk.datastore && <div>{disk.datastore}</div>}</div>)}</div>:Array.isArray(value)?value.join(', '):String(value)}</dd>
    </div>)}</dl>
    {row.custom_fields.length>0 && <><h4 className="text-xs font-semibold text-text-muted">{t('vsphere_attribute_mapping')}</h4><dl className="grid gap-2 sm:grid-cols-2">{row.custom_fields.map(field=><div key={field.key}><dt className="text-xs text-text-muted">{field.label}</dt><dd className="text-sm break-all">{field.value}</dd></div>)}</dl></>}
  </div>)}</div>
}
