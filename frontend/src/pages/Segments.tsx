import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { Device, devicesApi } from '../api/devices'
import { Segment, SegmentCreate, segmentsApi } from '../api/segments'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Input from '../components/ui/Input'
import Modal from '../components/ui/Modal'
import Spinner from '../components/ui/Spinner'
import { useI18n } from '../i18n'

const DEFAULT_COLORS = [
  '#6366f1', '#8b5cf6', '#ec4899', '#ef4444',
  '#f97316', '#eab308', '#22c55e', '#14b8a6',
  '#3b82f6', '#06b6d4',
]

function ipToInt(ip: string): number {
  const parts = ip.split('.').map(Number)
  return parts.length === 4 ? ((parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]) >>> 0 : 0
}

function ipInRange(ip: string, start: string, end: string): boolean {
  return ipToInt(ip) >= ipToInt(start) && ipToInt(ip) <= ipToInt(end)
}

function rangeSize(start: string, end: string): number {
  return Math.max(0, ipToInt(end) - ipToInt(start) + 1)
}

interface FormState {
  name: string
  color: string
  ip_start: string
  ip_end: string
  description: string
}

const EMPTY_FORM: FormState = {
  name: '',
  color: '#6366f1',
  ip_start: '',
  ip_end: '',
  description: '',
}

export default function Segments() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const [segments, setSegments] = useState<Segment[]>([])
  const [devices, setDevices] = useState<Device[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editSegment, setEditSegment] = useState<Segment | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    try {
      const [segs, devRes] = await Promise.all([
        segmentsApi.list(),
        devicesApi.list().catch(() => ({ items: [] as Device[] })),
      ])
      setSegments(segs)
      setDevices(devRes.items)
    } finally { setLoading(false) }
  }

  function openCreate() {
    setEditSegment(null)
    setForm(EMPTY_FORM)
    setModalOpen(true)
  }

  function openEdit(seg: Segment) {
    setEditSegment(seg)
    setForm({
      name: seg.name,
      color: seg.color,
      ip_start: seg.ip_start,
      ip_end: seg.ip_end,
      description: seg.description ?? '',
    })
    setModalOpen(true)
  }

  async function handleSave() {
    if (!form.name.trim()) { toast.error(t('please_enter_segment_name')); return }
    if (!form.ip_start.trim() || !form.ip_end.trim()) { toast.error(t('please_enter_ip_range')); return }

    setSaving(true)
    try {
      const data: SegmentCreate = {
        name: form.name.trim(),
        color: form.color,
        ip_start: form.ip_start.trim(),
        ip_end: form.ip_end.trim(),
        description: form.description.trim() || undefined,
      }
      if (editSegment) {
        const updated = await segmentsApi.update(editSegment.id, data)
        setSegments((prev) => prev.map((s) => (s.id === updated.id ? updated : s)))
        toast.success(t('segment_updated'))
      } else {
        const created = await segmentsApi.create(data)
        setSegments((prev) => [...prev, created])
        toast.success(t('segment_created'))
      }
      setModalOpen(false)
    } catch {
      toast.error(t('failed_to_save_segment'))
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(seg: Segment) {
    if (!confirm(t('segment_delete_confirm', { name: seg.name }))) return
    try {
      await segmentsApi.delete(seg.id)
      setSegments((prev) => prev.filter((s) => s.id !== seg.id))
      toast.success(t('segment_deleted'))
    } catch {
      toast.error(t('failed_to_delete_segment'))
    }
  }

  return (
    <div className="max-w-2xl mx-auto flex flex-col gap-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-text-base">{t('segments')}</h1>
        <Button size="sm" onClick={openCreate}>
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          {t('new_segment')}
        </Button>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Spinner /></div>
      ) : segments.length === 0 ? (
        <Card className="flex flex-col items-center py-12 text-text-subtle gap-3">
          <svg className="w-10 h-10 opacity-40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.4}
              d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
          </svg>
          <p className="text-sm">{t('no_segments')}</p>
          <Button size="sm" onClick={openCreate}>{t('new_segment')}</Button>
        </Card>
      ) : (
        <div className="flex flex-col gap-3">
          {segments.map((seg) => {
            const total = rangeSize(seg.ip_start, seg.ip_end)
            const used = devices.filter(
              (d) => d.ip_address != null && ipInRange(d.ip_address, seg.ip_start, seg.ip_end)
            ).length
            const free = total - used
            const pct = total > 0 ? Math.round((used / total) * 100) : 0
            return (
              <Card key={seg.id} className="flex flex-col gap-3">
                <div className="flex items-center gap-4">
                  {/* Color swatch */}
                  <div
                    className="w-3 h-10 rounded-full flex-shrink-0"
                    style={{ backgroundColor: seg.color }}
                  />
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-text-base">{seg.name}</p>
                    <p className="text-xs text-text-subtle font-mono">
                      {seg.ip_start} — {seg.ip_end}
                    </p>
                    {seg.description && (
                      <p className="text-xs text-text-muted mt-0.5">{seg.description}</p>
                    )}
                  </div>
                  <div className="flex gap-2 flex-shrink-0">
                    <Button variant="ghost" size="sm" onClick={() => navigate(`/?segment=${seg.id}`)}>
                      {t('devices_link')}
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => openEdit(seg)}>
                      {t('edit_segment')}
                    </Button>
                    <Button variant="danger" size="sm" onClick={() => handleDelete(seg)}>
                      {t('delete_segment')}
                    </Button>
                  </div>
                </div>
                {/* IP usage bar */}
                <div className="flex flex-col gap-1">
                  <div className="flex justify-between text-xs text-text-subtle">
                    <span>{t('segment_usage', { used, free, total })}</span>
                    <span>{pct}%</span>
                  </div>
                  <div className="h-1.5 bg-surface2 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{ width: `${pct}%`, backgroundColor: seg.color }}
                    />
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      )}

      {/* Create / Edit modal */}
      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editSegment ? t('edit_segment') : t('new_segment')}
      >
        <div className="flex flex-col gap-4">
          <Input
            label={t('segment_name')}
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            placeholder={t('segment_name_placeholder')}
            autoFocus
          />

          <div className="grid grid-cols-2 gap-3">
            <Input
              label={t('ip_start')}
              value={form.ip_start}
              onChange={(e) => setForm((f) => ({ ...f, ip_start: e.target.value }))}
              placeholder="192.168.1.1"
            />
            <Input
              label={t('ip_end')}
              value={form.ip_end}
              onChange={(e) => setForm((f) => ({ ...f, ip_end: e.target.value }))}
              placeholder="192.168.1.254"
            />
          </div>

          <div className="flex flex-col gap-2">
            <label className="text-sm font-medium text-text-muted">{t('segment_color')}</label>
            <div className="flex items-center gap-2 flex-wrap">
              {DEFAULT_COLORS.map((c) => (
                <button
                  key={c}
                  onClick={() => setForm((f) => ({ ...f, color: c }))}
                  className={`w-7 h-7 rounded-full transition-transform ${form.color === c ? 'scale-125 ring-2 ring-offset-2 ring-offset-surface ring-white/40' : 'hover:scale-110'}`}
                  style={{ backgroundColor: c }}
                />
              ))}
              <input
                type="color"
                value={form.color}
                onChange={(e) => setForm((f) => ({ ...f, color: e.target.value }))}
                className="w-8 h-7 rounded cursor-pointer border border-border bg-surface2"
                title={t('custom_color')}
              />
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-sm font-medium text-text-muted">{t('segment_description')}</label>
            <textarea
              rows={2}
              className="input-field resize-none"
              placeholder={t('segment_description_placeholder')}
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            />
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setModalOpen(false)}>{t('cancel')}</Button>
            <Button onClick={handleSave} loading={saving}>{t('save_segment')}</Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
