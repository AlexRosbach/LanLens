import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { devicesApi, Device } from '../api/devices'
import { IgnoreRule, inventoryApi, MergePreview } from '../api/inventory'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Input from '../components/ui/Input'
import Spinner from '../components/ui/Spinner'
import { formatDeviceLabel } from '../utils/formatters'

export default function InventoryTools() {
  const [rules, setRules] = useState<IgnoreRule[]>([])
  const [devices, setDevices] = useState<Device[]>([])
  const [loading, setLoading] = useState(true)
  const [ruleName, setRuleName] = useState('')
  const [rulePattern, setRulePattern] = useState('')
  const [ruleType, setRuleType] = useState('hostname')
  const [sourceId, setSourceId] = useState('')
  const [targetId, setTargetId] = useState('')
  const [mergePreview, setMergePreview] = useState<MergePreview | null>(null)

  async function load() {
    const [ruleRows, deviceRows] = await Promise.all([inventoryApi.ignoreRules(), devicesApi.list()])
    setRules(ruleRows)
    setDevices(deviceRows.items)
  }

  useEffect(() => {
    load().finally(() => setLoading(false))
  }, [])

  async function createRule() {
    if (!ruleName.trim() || !rulePattern.trim()) return
    try {
      await inventoryApi.createIgnoreRule({
        name: ruleName.trim(),
        rule_type: ruleType,
        pattern: rulePattern.trim(),
        enabled: true,
        mute_notifications: true,
        ignore_discovery: false,
        note: null,
      })
      setRuleName('')
      setRulePattern('')
      await load()
      toast.success('Ignore rule created')
    } catch {
      toast.error('Could not create ignore rule')
    }
  }

  async function previewMerge() {
    try {
      setMergePreview(await inventoryApi.previewMerge(Number(sourceId), Number(targetId), 'fill_empty'))
    } catch {
      toast.error('Could not preview merge')
    }
  }

  async function mergeDevices() {
    if (!mergePreview || !confirm('Merge these devices? This can not be undone automatically.')) return
    try {
      await inventoryApi.mergeDevices(Number(sourceId), Number(targetId), 'fill_empty')
      setMergePreview(null)
      setSourceId('')
      setTargetId('')
      await load()
      toast.success('Devices merged')
    } catch {
      toast.error('Device merge failed')
    }
  }

  if (loading) return <div className="flex justify-center py-16"><Spinner size="lg" /></div>

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      <div>
        <h1 className="text-xl font-bold text-text-base">Inventory tools</h1>
        <p className="text-sm text-text-subtle">Reports, selective backups, ignore rules, and duplicate handling.</p>
      </div>

      <Card>
        <h2 className="font-semibold text-text-base mb-3">Documentation export</h2>
        <div className="flex flex-wrap gap-2">
          <a href={inventoryApi.reportUrl('markdown')}><Button>Markdown</Button></a>
          <a href={inventoryApi.reportUrl('csv')}><Button variant="outline">CSV</Button></a>
          <a href={inventoryApi.reportUrl('json')}><Button variant="outline">JSON</Button></a>
        </div>
      </Card>

      <Card>
        <h2 className="font-semibold text-text-base mb-3">Selective backup</h2>
        <p className="text-sm text-text-subtle mb-3">Exports settings and documentation without secrets or credential values.</p>
        <a href={inventoryApi.selectiveBackupUrl()}><Button>Download selective backup</Button></a>
      </Card>

      <Card>
        <h2 className="font-semibold text-text-base mb-3">Ignore rules</h2>
        <div className="grid sm:grid-cols-[160px_1fr_1fr_auto] gap-2 mb-4">
          <select className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-base" value={ruleType} onChange={(e) => setRuleType(e.target.value)}>
            <option value="hostname">hostname</option>
            <option value="mac">mac</option>
            <option value="ip">ip</option>
            <option value="segment">segment</option>
            <option value="device_class">device class</option>
          </select>
          <Input value={ruleName} onChange={(e) => setRuleName(e.target.value)} placeholder="Rule name" />
          <Input value={rulePattern} onChange={(e) => setRulePattern(e.target.value)} placeholder="Pattern" />
          <Button onClick={createRule}>Add</Button>
        </div>
        <div className="space-y-2">
          {rules.map((rule) => (
            <div key={rule.id} className="flex items-center justify-between gap-3 rounded-lg border border-border bg-surface2/40 px-3 py-2">
              <div>
                <p className="text-sm font-medium text-text-base">{rule.name}</p>
                <p className="text-xs text-text-subtle">{rule.rule_type}: {rule.pattern} · {rule.enabled ? 'enabled' : 'disabled'}</p>
              </div>
              <Button variant="ghost" size="sm" onClick={async () => { await inventoryApi.deleteIgnoreRule(rule.id); await load() }}>Delete</Button>
            </div>
          ))}
          {rules.length === 0 && <p className="text-sm text-text-subtle">No ignore rules yet.</p>}
        </div>
      </Card>

      <Card>
        <h2 className="font-semibold text-text-base mb-3">Device merge</h2>
        <div className="grid sm:grid-cols-2 gap-2 mb-3">
          <select className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-base" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
            <option value="">Source device</option>
            {devices.map((d) => <option key={d.id} value={d.id}>#{d.id} {formatDeviceLabel(d, 'IP-only host')}</option>)}
          </select>
          <select className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-base" value={targetId} onChange={(e) => setTargetId(e.target.value)}>
            <option value="">Target device</option>
            {devices.map((d) => <option key={d.id} value={d.id}>#{d.id} {formatDeviceLabel(d, 'IP-only host')}</option>)}
          </select>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={previewMerge} disabled={!sourceId || !targetId || sourceId === targetId}>Preview merge</Button>
          <Button variant="danger" onClick={mergeDevices} disabled={!mergePreview}>Merge with fill-empty strategy</Button>
        </div>
        {mergePreview && (
          <div className="mt-4 rounded-lg border border-border bg-surface2/40 p-3 text-sm text-text-muted">
            <p className="font-medium text-text-base">{mergePreview.source_label} → {mergePreview.target_label}</p>
            <p className="text-xs text-text-subtle mt-1">Moves: {Object.entries(mergePreview.move_counts).map(([k, v]) => `${k}: ${v}`).join(' · ')}</p>
            {Object.keys(mergePreview.conflicts).length > 0 && <p className="text-xs text-warning mt-2">Conflicts exist. Fill-empty keeps existing target values.</p>}
          </div>
        )}
      </Card>
    </div>
  )
}
