import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { inventoryApi, TopologyResponse } from '../api/inventory'
import Card from '../components/ui/Card'
import Spinner from '../components/ui/Spinner'

export default function NetworkMap() {
  const [data, setData] = useState<TopologyResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    inventoryApi.topology().then(setData).finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="flex justify-center py-16"><Spinner size="lg" /></div>

  const bySegment = new Map<string, TopologyResponse['nodes']>()
  for (const node of data?.nodes ?? []) {
    const key = node.segment_name || 'Unassigned'
    bySegment.set(key, [...(bySegment.get(key) ?? []), node])
  }

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      <div>
        <h1 className="text-xl font-bold text-text-base">Network map</h1>
        <p className="text-sm text-text-subtle">Read-only topology grouped by segment. Host/guest relationships are listed below.</p>
      </div>

      <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
        {[...bySegment.entries()].map(([segment, nodes]) => (
          <Card key={segment}>
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold text-text-base">{segment}</h2>
              <span className="text-xs text-text-subtle">{nodes.length} devices</span>
            </div>
            <div className="space-y-2">
              {nodes.map((node) => (
                <Link key={node.id} to={`/devices/${node.id}`} className="block rounded-lg border border-border bg-surface2/50 px-3 py-2 hover:border-primary/50 transition-colors">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-text-base truncate">{node.label}</span>
                    <span className={`text-xs ${node.is_online ? 'text-success' : 'text-danger'}`}>{node.is_online ? 'online' : 'offline'}</span>
                  </div>
                  <p className="text-xs text-text-subtle truncate">{node.device_class} · {node.ip_address || 'no IP'} · {node.service_count} services</p>
                </Link>
              ))}
            </div>
          </Card>
        ))}
      </div>

      <Card>
        <h2 className="font-semibold text-text-base mb-3">Relationships</h2>
        {data?.edges.length ? (
          <div className="space-y-2">
            {data.edges.map((edge, index) => (
              <div key={`${edge.source}-${edge.target}-${index}`} className="text-sm text-text-muted border-b border-border/60 pb-2 last:border-0">
                Device #{edge.source} → Device #{edge.target} <span className="text-text-subtle">({edge.relationship_type})</span>
              </div>
            ))}
          </div>
        ) : <p className="text-sm text-text-subtle">No explicit relationships detected yet.</p>}
      </Card>
    </div>
  )
}
