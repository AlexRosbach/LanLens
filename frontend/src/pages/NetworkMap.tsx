import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { inventoryApi, TopologyEdge, TopologyNode } from '../api/inventory'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Spinner from '../components/ui/Spinner'
import { useI18n } from '../i18n'

export default function NetworkMap() {
  const { t } = useI18n()
  const [nodes, setNodes] = useState<TopologyNode[]>([])
  const [edges, setEdges] = useState<TopologyEdge[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  async function loadTopology() {
    setLoading(true)
    setError(false)
    try {
      const topology = await inventoryApi.topology()
      setNodes(topology.nodes)
      setEdges(topology.edges)
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadTopology()
  }, [])

  const groupedNodes = useMemo(() => {
    const groups = new Map<string, TopologyNode[]>()
    nodes.forEach((node) => {
      const key = node.segment_name || t('network_map_unassigned')
      groups.set(key, [...(groups.get(key) || []), node])
    })
    return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [nodes, t])

  const snmpEdges = edges.filter((edge) => edge.relationship_type === 'snmp_port')
  const otherEdges = edges.filter((edge) => edge.relationship_type !== 'snmp_port')
  const nodeById = new Map(nodes.map((node) => [node.id, node]))

  if (loading) return <div className="flex justify-center py-16"><Spinner size="lg" /></div>

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-text-base">{t('network_map_title')}</h1>
          <p className="mt-1 text-sm text-text-subtle">{t('network_map_description')}</p>
        </div>
        <Button variant="outline" onClick={loadTopology}>{t('refresh')}</Button>
      </div>

      {error && (
        <Card>
          <p className="text-sm text-danger">Topology data could not be loaded.</p>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        {groupedNodes.map(([segment, devices]) => (
          <Card key={segment}>
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="text-sm font-semibold text-text-muted">{segment}</h2>
              <span className="text-xs text-text-subtle">{t('network_map_device_count', { count: devices.length })}</span>
            </div>
            <div className="space-y-2">
              {devices.map((device) => (
                <Link
                  key={device.id}
                  to={`/devices/${device.id}`}
                  className="block rounded-lg border border-border bg-surface2/35 p-3 transition-colors hover:border-primary/60"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-text-base">{device.label}</p>
                      <p className="text-xs text-text-subtle">{device.ip_address || t('network_map_no_ip')} · {device.device_class}</p>
                    </div>
                    <Badge variant={device.is_online ? 'success' : 'danger'} dot>
                      {device.is_online ? t('online') : t('offline')}
                    </Badge>
                  </div>
                  <div className="mt-2 grid gap-1 text-xs text-text-subtle">
                    <span>{t('network_map_service_count', { count: device.service_count })}</span>
                    {device.snmp_switch && (
                      <span>SNMP: {device.snmp_switch}{device.snmp_interface ? ` / ${device.snmp_interface}` : ''}{device.snmp_vlan ? ` / VLAN ${device.snmp_vlan}` : ''}</span>
                    )}
                  </div>
                </Link>
              ))}
            </div>
          </Card>
        ))}
      </div>

      <Card>
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-text-muted">SNMP switch ports</h2>
          <span className="text-xs text-text-subtle">{snmpEdges.length} mappings</span>
        </div>
        {snmpEdges.length === 0 ? (
          <p className="text-sm text-text-subtle">No SNMP switch-port mappings yet. Add and poll a switch in Settings to populate this view.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-left uppercase tracking-wider text-text-subtle">
                  <th className="py-2 pr-3 font-medium">Switch</th>
                  <th className="py-2 pr-3 font-medium">Device</th>
                  <th className="py-2 pr-3 font-medium">Port</th>
                  <th className="py-2 font-medium">VLAN</th>
                </tr>
              </thead>
              <tbody>
                {snmpEdges.map((edge) => {
                  const source = nodeById.get(edge.source)
                  const target = nodeById.get(edge.target)
                  const metadata = edge.metadata || {}
                  return (
                    <tr key={`${edge.source}-${edge.target}-${edge.label || ''}`} className="border-b border-border last:border-0">
                      <td className="py-2 pr-3 text-text-muted">{source?.label || t('network_map_device_ref', { id: edge.source })}</td>
                      <td className="py-2 pr-3 text-text-muted">{target?.label || t('network_map_device_ref', { id: edge.target })}</td>
                      <td className="py-2 pr-3 text-text-subtle">{edge.label || String(metadata.if_index || '') || '-'}</td>
                      <td className="py-2 text-text-subtle">{String(metadata.vlan || '-')}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <h2 className="mb-3 text-sm font-semibold text-text-muted">{t('network_map_relationships')}</h2>
        {otherEdges.length === 0 ? (
          <p className="text-sm text-text-subtle">{t('network_map_no_relationships')}</p>
        ) : (
          <div className="space-y-2 text-sm text-text-muted">
            {otherEdges.map((edge) => (
              <div key={`${edge.source}-${edge.target}-${edge.relationship_type}`} className="rounded-lg border border-border bg-surface2/35 p-3">
                {nodeById.get(edge.source)?.label || t('network_map_device_ref', { id: edge.source })}
                <span className="px-2 text-text-subtle">-&gt;</span>
                {nodeById.get(edge.target)?.label || t('network_map_device_ref', { id: edge.target })}
                <span className="ml-2 text-xs text-text-subtle">{edge.label || edge.relationship_type}</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
