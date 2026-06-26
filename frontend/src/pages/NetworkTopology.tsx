import { PointerEvent, WheelEvent, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import Input from '../components/ui/Input'
import Spinner from '../components/ui/Spinner'
import { NetworkChangeEvent, TopologyEdge, TopologyNode, inventoryApi } from '../api/inventory'
import { SnmpEndpoint, snmpApi } from '../api/snmp'
import { useI18n } from '../i18n'
import { useUiSettingsStore } from '../store/uiSettingsStore'
import { formatRelativeTime } from '../utils/formatters'

type PositionedNode = TopologyNode & {
  x: number
  y: number
  kind: 'core' | 'infra' | 'switch' | 'endpoint'
  endpoint_count: number
  degree: number
}

type MapViewport = {
  x: number
  y: number
  scale: number
}

type NodePosition = {
  x: number
  y: number
}

const CANVAS_WIDTH = 1700
const CANVAS_HEIGHT = 1100
const MIN_ZOOM = 0.48
const MAX_ZOOM = 1.75
const ZOOM_STEP = 0.16
const DEFAULT_VIEWPORT: MapViewport = { x: -130, y: -80, scale: 1 }
const NODE_CARD_WIDTH = 188
const NODE_CARD_HEIGHT = 88
const NODE_MIN_GAP = 262
const ROW_GAP = 120

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function normalize(value?: string | null) {
  return (value || '').trim().toLowerCase()
}

function nodeKind(node: TopologyNode, sourceCount: number): PositionedNode['kind'] {
  const haystack = `${node.device_class} ${node.label}`.toLowerCase()
  if (sourceCount >= 3 || haystack.includes('core')) return 'core'
  if (/(switch|sw-|access)/.test(haystack)) return 'switch'
  if (/(router|gateway|firewall|wan|edge|ap)/.test(haystack)) return 'infra'
  return 'endpoint'
}

function relationLabel(edge: TopologyEdge) {
  if (edge.label) return edge.label
  return edge.relationship_type.replace(/_/g, ' ')
}

function relationTone(edge: TopologyEdge, target?: TopologyNode) {
  if (target && !target.is_online) return '#ef4444'
  if (edge.relationship_type === 'snmp_port') return '#22c55e'
  if (edge.relationship_type.includes('ospf') || edge.relationship_type.includes('lldp') || edge.relationship_type.includes('cdp')) return '#3b82f6'
  if (edge.relationship_type.includes('stp') || edge.relationship_type.includes('virtual')) return '#f59e0b'
  return '#64748b'
}

function endpointSummary(node: TopologyNode, endpoints: SnmpEndpoint[]) {
  return endpoints.filter((endpoint) => endpoint.device_id === node.id)
}

function buildPositions(nodes: TopologyNode[], edges: TopologyEdge[], endpoints: SnmpEndpoint[]) {
  const sourceCounts = new Map<number, number>()
  const degreeCounts = new Map<number, number>()
  edges.forEach((edge) => {
    sourceCounts.set(edge.source, (sourceCounts.get(edge.source) || 0) + 1)
    degreeCounts.set(edge.source, (degreeCounts.get(edge.source) || 0) + 1)
    degreeCounts.set(edge.target, (degreeCounts.get(edge.target) || 0) + 1)
  })

  const buckets: Record<PositionedNode['kind'], PositionedNode[]> = {
    core: [],
    infra: [],
    switch: [],
    endpoint: [],
  }

  nodes.forEach((node) => {
    const degree = degreeCounts.get(node.id) || 0
    const kind = nodeKind(node, sourceCounts.get(node.id) || 0)
    buckets[kind].push({
      ...node,
      x: 0,
      y: 0,
      kind,
      endpoint_count: endpointSummary(node, endpoints).length,
      degree,
    })
  })

  if (buckets.core.length === 0) {
    const likelyCore = [...buckets.switch, ...buckets.infra, ...buckets.endpoint]
      .sort((a, b) => b.degree - a.degree)[0]
    if (likelyCore) {
      Object.values(buckets).forEach((bucket) => {
        const index = bucket.findIndex((node) => node.id === likelyCore.id)
        if (index >= 0) bucket.splice(index, 1)
      })
      likelyCore.kind = 'core'
      buckets.core.push(likelyCore)
    }
  }

  const placeGrid = (row: PositionedNode[], startY: number, inset = 150) => {
    const sorted = [...row].sort((a, b) => b.degree - a.degree || a.label.localeCompare(b.label))
    const usableWidth = CANVAS_WIDTH - inset * 2
    const perLine = Math.max(1, Math.floor(usableWidth / NODE_MIN_GAP))
    const lineCount = Math.max(1, Math.ceil(sorted.length / perLine))

    sorted.forEach((node, index) => {
      const line = Math.floor(index / perLine)
      const lineStart = line * perLine
      const lineLength = Math.min(perLine, sorted.length - lineStart)
      const gap = usableWidth / Math.max(lineLength, 1)
      node.x = inset + gap * (index - lineStart) + gap / 2
      node.y = startY + line * ROW_GAP
    })
    return startY + (lineCount - 1) * ROW_GAP
  }

  const infraBottom = placeGrid(buckets.infra, 150, 360)
  const coreBottom = placeGrid(buckets.core, Math.max(325, infraBottom + 175), 500)
  const switchBottom = placeGrid(buckets.switch, Math.max(500, coreBottom + 175), 230)
  placeGrid(buckets.endpoint, Math.max(660, switchBottom + 160), 170)

  return [...buckets.infra, ...buckets.core, ...buckets.switch, ...buckets.endpoint]
}

function DeviceIcon({ kind }: { kind: PositionedNode['kind'] }) {
  const iconClass = "h-5 w-5"
  if (kind === 'core' || kind === 'switch') {
    return (
      <svg className={iconClass} fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M4 7h16v10H4V7zm4 13h8M8 4h8M8 12h.01M12 12h.01M16 12h.01" />
      </svg>
    )
  }
  if (kind === 'infra') {
    return (
      <svg className={iconClass} fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M12 3l8 4v5c0 5-3.4 7.7-8 9-4.6-1.3-8-4-8-9V7l8-4z" />
      </svg>
    )
  }
  return (
    <svg className={iconClass} fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M5 5h14v10H5V5zm3 14h8m-4-4v4" />
    </svg>
  )
}

export default function NetworkTopology() {
  const { t, lang } = useI18n()
  const navigate = useNavigate()
  const advancedViewEnabled = useUiSettingsStore((state) => state.advancedViewEnabled)
  const showNetworkTopologyNav = useUiSettingsStore((state) => state.showNetworkTopologyNav)
  const [topology, setTopology] = useState<{ nodes: TopologyNode[]; edges: TopologyEdge[] }>({ nodes: [], edges: [] })
  const [endpoints, setEndpoints] = useState<SnmpEndpoint[]>([])
  const [changes, setChanges] = useState<NetworkChangeEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [segment, setSegment] = useState('')
  const [deviceClass, setDeviceClass] = useState('')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [viewport, setViewport] = useState<MapViewport>(DEFAULT_VIEWPORT)
  const [nodePositions, setNodePositions] = useState<Record<number, NodePosition>>({})
  const svgRef = useRef<SVGSVGElement | null>(null)
  const dragRef = useRef<{
    pointerId: number
    startX: number
    startY: number
    originX: number
    originY: number
  } | null>(null)
  const nodeDragRef = useRef<{
    pointerId: number
    nodeId: number
    startX: number
    startY: number
    originX: number
    originY: number
    moved: boolean
  } | null>(null)
  const suppressNodeClickRef = useRef<number | null>(null)

  async function load() {
    setLoading(true)
    try {
      const [nextTopology, nextEndpoints, nextChanges] = await Promise.all([
        inventoryApi.topology(),
        snmpApi.listEndpoints().catch(() => [] as SnmpEndpoint[]),
        inventoryApi.changes({ since_hours: 24, limit: 8 }).catch(() => [] as NetworkChangeEvent[]),
      ])
      setTopology(nextTopology)
      setEndpoints(nextEndpoints)
      setChanges(nextChanges)
      setSelectedId((current) => current ?? nextTopology.nodes[0]?.id ?? null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const segments = useMemo(() => (
    [...new Set(topology.nodes.map((node) => node.segment_name).filter(Boolean) as string[])].sort()
  ), [topology.nodes])
  const classes = useMemo(() => (
    [...new Set(topology.nodes.map((node) => node.device_class || t('unknown')).filter(Boolean))].sort()
  ), [topology.nodes, t])

  const filteredNodes = useMemo(() => {
    const needle = normalize(search)
    return topology.nodes.filter((node) => {
      if (segment && node.segment_name !== segment) return false
      if (deviceClass && (node.device_class || t('unknown')) !== deviceClass) return false
      if (!needle) return true
      return normalize(`${node.label} ${node.ip_address} ${node.device_class} ${node.segment_name}`).includes(needle)
    })
  }, [deviceClass, search, segment, topology.nodes, t])

  const visibleIds = new Set(filteredNodes.map((node) => node.id))
  const visibleEdges = topology.edges.filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target))
  const positioned = buildPositions(filteredNodes, visibleEdges, endpoints).map((node) => {
    const customPosition = nodePositions[node.id]
    return customPosition ? { ...node, x: customPosition.x, y: customPosition.y } : node
  })
  const positionedById = new Map(positioned.map((node) => [node.id, node]))
  const selected = positionedById.get(selectedId ?? -1) ?? positioned[0] ?? null
  const selectedEndpoints = selected ? endpointSummary(selected, endpoints) : []
  const selectedEdges = selected ? topology.edges.filter((edge) => edge.source === selected.id || edge.target === selected.id) : []
  const selectedChanges = selected ? changes.filter((change) => change.device_id === selected.id) : []
  const snmpEdgeCount = topology.edges.filter((edge) => edge.relationship_type === 'snmp_port').length
  const passiveEdgeCount = topology.edges.filter((edge) => edge.relationship_type !== 'snmp_port' && edge.relationship_type !== 'host_guest').length
  const zoomPercent = Math.round(viewport.scale * 100)

  function zoomMap(nextScale: number, pivotX = CANVAS_WIDTH / 2, pivotY = CANVAS_HEIGHT / 2) {
    setViewport((current) => {
      const scale = clamp(nextScale, MIN_ZOOM, MAX_ZOOM)
      const ratio = scale / current.scale
      return {
        scale,
        x: pivotX - (pivotX - current.x) * ratio,
        y: pivotY - (pivotY - current.y) * ratio,
      }
    })
  }

  function resetMap() {
    setViewport(DEFAULT_VIEWPORT)
  }

  function resetLayout() {
    setNodePositions({})
    setViewport(DEFAULT_VIEWPORT)
  }

  function svgPoint(event: Pick<PointerEvent<SVGSVGElement>, 'clientX' | 'clientY'> | Pick<WheelEvent<SVGSVGElement>, 'clientX' | 'clientY'>) {
    const bounds = svgRef.current?.getBoundingClientRect()
    if (!bounds) return { x: CANVAS_WIDTH / 2, y: CANVAS_HEIGHT / 2 }
    return {
      x: ((event.clientX - bounds.left) / bounds.width) * CANVAS_WIDTH,
      y: ((event.clientY - bounds.top) / bounds.height) * CANVAS_HEIGHT,
    }
  }

  function mapPoint(event: Pick<PointerEvent, 'clientX' | 'clientY'>) {
    const point = svgPoint(event)
    return {
      x: (point.x - viewport.x) / viewport.scale,
      y: (point.y - viewport.y) / viewport.scale,
    }
  }

  function onWheel(event: WheelEvent<SVGSVGElement>) {
    event.preventDefault()
    const point = svgPoint(event)
    const direction = event.deltaY > 0 ? -1 : 1
    zoomMap(viewport.scale + direction * ZOOM_STEP, point.x, point.y)
  }

  function onPointerDown(event: PointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return
    event.currentTarget.setPointerCapture(event.pointerId)
    dragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: viewport.x,
      originY: viewport.y,
    }
  }

  function onPointerMove(event: PointerEvent<SVGSVGElement>) {
    const nodeDrag = nodeDragRef.current
    if (nodeDrag && nodeDrag.pointerId === event.pointerId) {
      const point = mapPoint(event)
      const dx = point.x - nodeDrag.startX
      const dy = point.y - nodeDrag.startY
      if (Math.abs(dx) > 2 || Math.abs(dy) > 2) {
        nodeDrag.moved = true
      }
      setNodePositions((current) => ({
        ...current,
        [nodeDrag.nodeId]: {
          x: clamp(nodeDrag.originX + dx, NODE_CARD_WIDTH / 2, CANVAS_WIDTH - NODE_CARD_WIDTH / 2),
          y: clamp(nodeDrag.originY + dy, NODE_CARD_HEIGHT / 2, CANVAS_HEIGHT - NODE_CARD_HEIGHT / 2),
        },
      }))
      return
    }

    const drag = dragRef.current
    const bounds = svgRef.current?.getBoundingClientRect()
    if (!drag || drag.pointerId !== event.pointerId || !bounds) return
    const dx = ((event.clientX - drag.startX) / bounds.width) * CANVAS_WIDTH
    const dy = ((event.clientY - drag.startY) / bounds.height) * CANVAS_HEIGHT
    setViewport((current) => ({ ...current, x: drag.originX + dx, y: drag.originY + dy }))
  }

  function onPointerUp(event: PointerEvent<SVGSVGElement>) {
    if (nodeDragRef.current?.pointerId === event.pointerId) {
      if (nodeDragRef.current.moved) {
        suppressNodeClickRef.current = nodeDragRef.current.nodeId
      }
      nodeDragRef.current = null
    }
    if (dragRef.current?.pointerId === event.pointerId) {
      dragRef.current = null
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId)
      }
    }
  }

  function startNodeDrag(event: PointerEvent<SVGGElement>, node: PositionedNode) {
    if (event.button !== 0) return
    event.stopPropagation()
    event.currentTarget.setPointerCapture(event.pointerId)
    const point = mapPoint(event)
    nodeDragRef.current = {
      pointerId: event.pointerId,
      nodeId: node.id,
      startX: point.x,
      startY: point.y,
      originX: node.x,
      originY: node.y,
      moved: false,
    }
  }

  function finishNodeDrag(event: PointerEvent<SVGGElement>) {
    if (nodeDragRef.current?.pointerId === event.pointerId) {
      if (nodeDragRef.current.moved) {
        suppressNodeClickRef.current = nodeDragRef.current.nodeId
      }
      nodeDragRef.current = null
    }
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  if (!advancedViewEnabled || !showNetworkTopologyNav) {
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-4">
        <div>
          <h1 className="text-xl font-bold text-text-base">{t('network_topology')}</h1>
          <p className="mt-1 text-sm text-text-subtle">{t('network_topology_disabled_hint')}</p>
        </div>
        <div className="rounded-lg border border-border bg-surface p-5">
          <Button onClick={() => navigate('/settings')}>{t('open_settings')}</Button>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5">
      <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <h1 className="text-xl font-bold text-text-base">{t('network_topology')}</h1>
          <p className="mt-1 text-sm text-text-subtle">
            {t('network_topology_summary', {
              nodes: topology.nodes.length,
              edges: topology.edges.length,
              snmp: snmpEdgeCount,
              passive: passiveEdgeCount,
            })}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={load}>{t('refresh')}</Button>
        </div>
      </div>

      <div className="grid gap-3 rounded-lg border border-border bg-surface p-3 lg:grid-cols-[minmax(220px,1.2fr)_180px_180px_auto]">
        <Input
          placeholder={t('topology_search_placeholder')}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select
          aria-label={t('segment_filter')}
          value={segment}
          onChange={(event) => setSegment(event.target.value)}
          className="h-10 rounded-lg border border-border bg-surface2 px-3 text-sm text-text-base outline-none focus:border-primary"
        >
          <option value="">{t('all_segments')}</option>
          {segments.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <select
          aria-label={t('device_class_filter')}
          value={deviceClass}
          onChange={(event) => setDeviceClass(event.target.value)}
          className="h-10 rounded-lg border border-border bg-surface2 px-3 text-sm text-text-base outline-none focus:border-primary"
        >
          <option value="">{t('all_device_classes')}</option>
          {classes.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
        <Button variant="ghost" size="sm" onClick={() => { setSearch(''); setSegment(''); setDeviceClass('') }}>{t('reset_filters')}</Button>
      </div>

      {loading ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : topology.nodes.length === 0 ? (
        <div className="rounded-lg border border-border bg-surface py-16 text-center text-sm text-text-subtle">
          {t('topology_empty')}
        </div>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="overflow-hidden rounded-lg border border-border bg-surface">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
              <div>
                <p className="text-sm font-semibold text-text-base">{t('topology_map')}</p>
                <p className="text-xs text-text-subtle">{t('topology_map_hint')}</p>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <Badge variant="success">{t('healthy_links')}</Badge>
                <Badge variant="primary">{t('passive_edges')}</Badge>
                <Badge variant="warning">{t('host_edges')}</Badge>
                <div className="ml-1 flex items-center overflow-hidden rounded-lg border border-border bg-surface2">
                  <button
                    type="button"
                    aria-label={t('zoom_out')}
                    onClick={() => zoomMap(viewport.scale - ZOOM_STEP)}
                    className="h-8 w-8 border-r border-border text-sm font-semibold text-text-base hover:bg-surface"
                  >
                    -
                  </button>
                  <span className="min-w-[52px] px-2 text-center text-[11px] font-medium text-text-muted">{zoomPercent}%</span>
                  <button
                    type="button"
                    aria-label={t('zoom_in')}
                    onClick={() => zoomMap(viewport.scale + ZOOM_STEP)}
                    className="h-8 w-8 border-l border-border text-sm font-semibold text-text-base hover:bg-surface"
                  >
                    +
                  </button>
                  <button
                    type="button"
                    aria-label={t('reset_map_view')}
                    onClick={resetMap}
                    className="h-8 border-l border-border px-2 text-[11px] font-medium text-text-muted hover:bg-surface hover:text-text-base"
                  >
                    {t('reset')}
                  </button>
                  <button
                    type="button"
                    aria-label={t('reset_topology_layout')}
                    onClick={resetLayout}
                    className="h-8 border-l border-border px-2 text-[11px] font-medium text-text-muted hover:bg-surface hover:text-text-base"
                  >
                    {t('reset_layout')}
                  </button>
                </div>
              </div>
            </div>
            <div className="overflow-hidden">
              <svg
                ref={svgRef}
                data-testid="topology-map"
                viewBox={`0 0 ${CANVAS_WIDTH} ${CANVAS_HEIGHT}`}
                className="h-[620px] w-full cursor-grab touch-none bg-surface2/40 active:cursor-grabbing"
                onWheel={onWheel}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={onPointerUp}
              >
                <defs>
                  <pattern id="topology-grid" width="32" height="32" patternUnits="userSpaceOnUse">
                    <path d="M 32 0 L 0 0 0 32" fill="none" stroke="currentColor" strokeOpacity="0.06" />
                  </pattern>
                </defs>
                <rect width={CANVAS_WIDTH} height={CANVAS_HEIGHT} fill="url(#topology-grid)" className="text-text-muted" />
                <g transform={`translate(${viewport.x} ${viewport.y}) scale(${viewport.scale})`}>
                  {visibleEdges.map((edge, index) => {
                    const source = positionedById.get(edge.source)
                    const target = positionedById.get(edge.target)
                    if (!source || !target) return null
                    const midX = (source.x + target.x) / 2
                    const midY = (source.y + target.y) / 2
                    const color = relationTone(edge, target)
                    return (
                      <g key={`${edge.source}-${edge.target}-${edge.relationship_type}-${index}`}>
                        <path
                          data-testid="topology-edge"
                          data-source-id={edge.source}
                          data-target-id={edge.target}
                          d={`M ${source.x} ${source.y} C ${source.x} ${midY}, ${target.x} ${midY}, ${target.x} ${target.y}`}
                          fill="none"
                          stroke={color}
                          strokeWidth={edge.relationship_type === 'snmp_port' ? 2.4 : 1.6}
                          strokeDasharray={edge.relationship_type === 'snmp_port' ? undefined : '7 5'}
                          opacity={0.84}
                        />
                        <foreignObject x={midX - 52} y={midY - 12} width="104" height="24">
                          <div className="truncate rounded-md border border-border bg-surface px-1.5 py-0.5 text-center text-[10px] font-medium text-text-muted shadow-sm">
                            {relationLabel(edge)}
                          </div>
                        </foreignObject>
                      </g>
                    )
                  })}
                  {positioned.map((node) => {
                    const selectedNode = selected?.id === node.id
                    return (
                      <g
                        key={node.id}
                        className="cursor-grab active:cursor-grabbing"
                        onClick={() => {
                          if (suppressNodeClickRef.current === node.id) {
                            suppressNodeClickRef.current = null
                            return
                          }
                          setSelectedId(node.id)
                        }}
                        onPointerDown={(event) => startNodeDrag(event, node)}
                        onPointerUp={finishNodeDrag}
                        onPointerCancel={finishNodeDrag}
                      >
                        <foreignObject
                          data-testid="topology-node"
                          data-node-id={node.id}
                          x={node.x - NODE_CARD_WIDTH / 2}
                          y={node.y - NODE_CARD_HEIGHT / 2}
                          width={NODE_CARD_WIDTH}
                          height={NODE_CARD_HEIGHT}
                        >
                          <div
                            className={`h-[86px] rounded-lg border bg-surface p-2 shadow-sm transition-colors ${selectedNode ? 'border-primary ring-1 ring-primary' : 'border-border hover:border-primary/60'}`}
                          >
                            <div className="flex items-start gap-2">
                              <div className={`rounded-md p-1.5 ${node.kind === 'core' ? 'bg-primary-dim text-primary' : node.kind === 'infra' ? 'bg-warning-dim text-warning' : 'bg-surface2 text-text-muted'}`}>
                                <DeviceIcon kind={node.kind} />
                              </div>
                              <div className="min-w-0 flex-1">
                                <p className="truncate text-xs font-semibold text-text-base">{node.label}</p>
                                <p className="truncate text-[10px] text-text-subtle">{node.ip_address || node.device_class || t('unknown')}</p>
                                <div className="mt-1 flex items-center gap-1">
                                  <span className={`h-1.5 w-1.5 rounded-full ${node.is_online ? 'bg-success' : 'bg-danger'}`} />
                                  <span className="truncate text-[10px] text-text-subtle">{node.segment_name || node.device_class || t('unknown')}</span>
                                </div>
                                {node.endpoint_count > 0 && (
                                  <p className="mt-1 truncate text-[10px] text-text-subtle">{node.endpoint_count} {t('learned_endpoints')}</p>
                                )}
                              </div>
                            </div>
                          </div>
                        </foreignObject>
                      </g>
                    )
                  })}
                </g>
              </svg>
            </div>
            <div className="grid gap-3 border-t border-border px-4 py-3 text-xs text-text-subtle md:grid-cols-4">
              <span>{t('topology_nodes')}: <strong className="text-text-base">{filteredNodes.length}</strong></span>
              <span>{t('topology_edges')}: <strong className="text-text-base">{visibleEdges.length}</strong></span>
              <span>SNMP: <strong className="text-text-base">{snmpEdgeCount}</strong></span>
              <span>{t('passive_edges')}: <strong className="text-text-base">{passiveEdgeCount}</strong></span>
            </div>
          </div>

          <aside className="flex flex-col gap-4">
            <div className="rounded-lg border border-border bg-surface">
              <div className="border-b border-border px-4 py-3">
                <p className="text-sm font-semibold text-text-base">{selected?.label || t('topology_no_selection')}</p>
                <p className="text-xs text-text-subtle">{selected?.ip_address || selected?.device_class || t('unknown')}</p>
              </div>
              {selected ? (
                <div className="space-y-4 p-4">
                  <div className="grid grid-cols-2 gap-3 text-xs">
                    <div>
                      <p className="text-text-subtle">{t('status')}</p>
                      <p className={selected.is_online ? 'font-medium text-success' : 'font-medium text-danger'}>
                        {selected.is_online ? t('online') : t('offline')}
                      </p>
                    </div>
                    <div>
                      <p className="text-text-subtle">{t('device_class')}</p>
                      <p className="font-medium text-text-base">{selected.device_class || t('unknown')}</p>
                    </div>
                    <div>
                      <p className="text-text-subtle">{t('segment')}</p>
                      <p className="font-medium text-text-base">{selected.segment_name || t('unknown')}</p>
                    </div>
                    <div>
                      <p className="text-text-subtle">{t('services')}</p>
                      <p className="font-medium text-text-base">{selected.service_count}</p>
                    </div>
                  </div>
                  <div className="rounded-lg border border-border bg-surface2 p-3 text-xs">
                    <p className="mb-2 font-semibold text-text-base">{t('snmp_context')}</p>
                    <div className="space-y-1 text-text-subtle">
                      <p>{t('idoit_export_snmp_switch')}: <span className="text-text-base">{selected.snmp_switch || '—'}</span></p>
                      <p>{t('idoit_export_snmp_port')}: <span className="text-text-base">{selected.snmp_interface || '—'}</span></p>
                      <p>{t('idoit_export_snmp_vlan')}: <span className="text-text-base">{selected.snmp_vlan || '—'}</span></p>
                    </div>
                  </div>
                  <div>
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-subtle">{t('neighbors')}</p>
                    <div className="divide-y divide-border rounded-lg border border-border">
                      {selectedEdges.slice(0, 6).map((edge, index) => {
                        const otherId = edge.source === selected.id ? edge.target : edge.source
                        const other = topology.nodes.find((node) => node.id === otherId)
                        return (
                          <button
                            key={`${edge.source}-${edge.target}-${index}`}
                            type="button"
                            onClick={() => other && setSelectedId(other.id)}
                            className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs hover:bg-surface2"
                          >
                            <span className="min-w-0">
                              <span className="block truncate font-medium text-text-base">{other?.label || t('unknown')}</span>
                              <span className="block truncate text-text-subtle">{relationLabel(edge)}</span>
                            </span>
                            <span className="text-text-subtle">{other?.ip_address || ''}</span>
                          </button>
                        )
                      })}
                      {selectedEdges.length === 0 && <p className="px-3 py-3 text-xs text-text-subtle">{t('topology_no_neighbors')}</p>}
                    </div>
                  </div>
                  <div>
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-subtle">{t('learned_endpoints')}</p>
                    <div className="space-y-2">
                      {selectedEndpoints.slice(0, 4).map((endpoint) => (
                        <div key={`${endpoint.switch_host}-${endpoint.mac_address}-${endpoint.vlan || ''}`} className="rounded-lg border border-border bg-surface2 px-3 py-2 text-xs">
                          <p className="truncate font-medium text-text-base">{endpoint.switch_name} · {endpoint.interface_name || `ifIndex ${endpoint.if_index ?? '?'}`}</p>
                          <p className="truncate text-text-subtle">{endpoint.mac_address}{endpoint.vlan ? ` · VLAN ${endpoint.vlan}` : ''}</p>
                        </div>
                      ))}
                      {selectedEndpoints.length === 0 && <p className="rounded-lg border border-border bg-surface2 px-3 py-3 text-xs text-text-subtle">{t('topology_no_endpoints')}</p>}
                    </div>
                  </div>
                  <Button variant="outline" size="sm" onClick={() => navigate(`/devices/${selected.id}`)}>{t('view_device')}</Button>
                </div>
              ) : null}
            </div>

            <div className="rounded-lg border border-border bg-surface">
              <div className="border-b border-border px-4 py-3">
                <p className="text-sm font-semibold text-text-base">{t('topology_recent_changes')}</p>
              </div>
              <div className="divide-y divide-border">
                {(selectedChanges.length ? selectedChanges : changes).slice(0, 5).map((change) => (
                  <button
                    key={change.id}
                    type="button"
                    onClick={() => navigate(`/devices/${change.device_id}`)}
                    className="block w-full px-4 py-3 text-left text-xs hover:bg-surface2"
                  >
                    <p className="truncate font-medium text-text-base">{change.device_label}</p>
                    <p className="truncate text-text-subtle">{change.message || change.event_type.replace(/_/g, ' ')}</p>
                    <p className="mt-1 text-text-subtle">{formatRelativeTime(change.created_at, lang)}</p>
                  </button>
                ))}
                {changes.length === 0 && <p className="px-4 py-4 text-xs text-text-subtle">{t('no_changes_recorded')}</p>}
              </div>
            </div>
          </aside>
        </div>
      )}
    </div>
  )
}
