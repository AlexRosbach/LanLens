import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { devicesApi, Device } from '../api/devices'
import { IgnoreRule, inventoryApi, MergePreview } from '../api/inventory'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Input from '../components/ui/Input'
import Spinner from '../components/ui/Spinner'
import { useI18n } from '../i18n'
import { formatDeviceLabel } from '../utils/formatters'

export default function InventoryTools() {
  const { t } = useI18n()
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
    load().catch(() => toast.error(t('inventory_tools_load_failed'))).finally(() => setLoading(false))
  }, [t])

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
      toast.success(t('ignore_rule_created'))
    } catch {
      toast.error(t('ignore_rule_create_failed'))
    }
  }

  async function previewMerge() {
    try {
      setMergePreview(await inventoryApi.previewMerge(Number(sourceId), Number(targetId), 'fill_empty'))
    } catch {
      toast.error(t('merge_preview_failed'))
    }
  }

  async function mergeDevices() {
    if (!mergePreview || !confirm(t('merge_confirm'))) return
    try {
      await inventoryApi.mergeDevices(Number(sourceId), Number(targetId), 'fill_empty')
      setMergePreview(null)
      setSourceId('')
      setTargetId('')
      await load()
      toast.success(t('devices_merged'))
    } catch {
      toast.error(t('device_merge_failed'))
    }
  }

  async function deleteRule(rule: IgnoreRule) {
    if (!confirm(t('ignore_rule_delete_confirm', { name: rule.name }))) return
    try {
      await inventoryApi.deleteIgnoreRule(rule.id)
      await load()
      toast.success(t('ignore_rule_deleted'))
    } catch {
      toast.error(t('ignore_rule_delete_failed'))
    }
  }

  if (loading) return <div className="flex justify-center py-16"><Spinner size="lg" /></div>

  return (
    <div className="max-w-5xl mx-auto space-y-5">
      <div>
        <h1 className="text-xl font-bold text-text-base">{t('inventory_tools_title')}</h1>
        <p className="text-sm text-text-subtle">{t('inventory_tools_description')}</p>
      </div>

      <Card>
        <h2 className="font-semibold text-text-base mb-3">{t('documentation_export')}</h2>
        <div className="flex flex-wrap gap-2">
          <a className="inline-flex items-center gap-2 font-medium rounded-lg transition-colors bg-primary hover:bg-primary-hover text-white px-4 py-2 text-sm" href={inventoryApi.reportUrl('markdown')}>Markdown</a>
          <a className="inline-flex items-center gap-2 font-medium rounded-lg transition-colors border border-border text-text-muted hover:border-primary hover:text-primary px-4 py-2 text-sm" href={inventoryApi.reportUrl('csv')}>CSV</a>
          <a className="inline-flex items-center gap-2 font-medium rounded-lg transition-colors border border-border text-text-muted hover:border-primary hover:text-primary px-4 py-2 text-sm" href={inventoryApi.reportUrl('json')}>JSON</a>
        </div>
      </Card>

      <Card>
        <h2 className="font-semibold text-text-base mb-3">{t('selective_backup')}</h2>
        <p className="text-sm text-text-subtle mb-3">{t('selective_backup_description')}</p>
        <a className="inline-flex items-center gap-2 font-medium rounded-lg transition-colors bg-primary hover:bg-primary-hover text-white px-4 py-2 text-sm" href={inventoryApi.selectiveBackupUrl()}>{t('download_selective_backup')}</a>
      </Card>

      <Card>
        <h2 className="font-semibold text-text-base mb-3">{t('ignore_rules')}</h2>
        <div className="grid sm:grid-cols-[160px_1fr_1fr_auto] gap-2 mb-4">
          <select className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-base" value={ruleType} onChange={(e) => setRuleType(e.target.value)}>
            <option value="hostname">{t('ignore_rule_type_hostname')}</option>
            <option value="mac">{t('ignore_rule_type_mac')}</option>
            <option value="ip">{t('ignore_rule_type_ip')}</option>
            <option value="segment">{t('ignore_rule_type_segment')}</option>
            <option value="device_class">{t('ignore_rule_type_device_class')}</option>
          </select>
          <Input value={ruleName} onChange={(e) => setRuleName(e.target.value)} placeholder={t('rule_name')} />
          <Input value={rulePattern} onChange={(e) => setRulePattern(e.target.value)} placeholder={t('pattern')} />
          <Button onClick={createRule}>{t('add')}</Button>
        </div>
        <div className="space-y-2">
          {rules.map((rule) => (
            <div key={rule.id} className="flex items-center justify-between gap-3 rounded-lg border border-border bg-surface2/40 px-3 py-2">
              <div>
                <p className="text-sm font-medium text-text-base">{rule.name}</p>
                <p className="text-xs text-text-subtle">{rule.rule_type}: {rule.pattern} · {rule.enabled ? t('enabled') : t('disabled')}</p>
              </div>
              <Button variant="ghost" size="sm" onClick={() => deleteRule(rule)}>{t('delete')}</Button>
            </div>
          ))}
          {rules.length === 0 && <p className="text-sm text-text-subtle">{t('no_ignore_rules')}</p>}
        </div>
      </Card>

      <Card>
        <h2 className="font-semibold text-text-base mb-3">{t('device_merge')}</h2>
        <div className="grid sm:grid-cols-2 gap-2 mb-3">
          <select className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-base" value={sourceId} onChange={(e) => setSourceId(e.target.value)}>
            <option value="">{t('source_device')}</option>
            {devices.map((d) => <option key={d.id} value={d.id}>#{d.id} {formatDeviceLabel(d, t('ip_only_host'))}</option>)}
          </select>
          <select className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text-base" value={targetId} onChange={(e) => setTargetId(e.target.value)}>
            <option value="">{t('target_device')}</option>
            {devices.map((d) => <option key={d.id} value={d.id}>#{d.id} {formatDeviceLabel(d, t('ip_only_host'))}</option>)}
          </select>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={previewMerge} disabled={!sourceId || !targetId || sourceId === targetId}>{t('preview_merge')}</Button>
          <Button variant="danger" onClick={mergeDevices} disabled={!mergePreview}>{t('merge_fill_empty')}</Button>
        </div>
        {mergePreview && (
          <div className="mt-4 rounded-lg border border-border bg-surface2/40 p-3 text-sm text-text-muted">
            <p className="font-medium text-text-base">{mergePreview.source_label} → {mergePreview.target_label}</p>
            <p className="text-xs text-text-subtle mt-1">{t('merge_moves')}: {Object.entries(mergePreview.move_counts).map(([k, v]) => `${k}: ${v}`).join(' · ')}</p>
            {Object.keys(mergePreview.conflicts).length > 0 && <p className="text-xs text-warning mt-2">{t('merge_conflicts_hint')}</p>}
          </div>
        )}
      </Card>
    </div>
  )
}
