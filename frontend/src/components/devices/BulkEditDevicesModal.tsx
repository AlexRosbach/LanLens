import { useEffect, useState } from 'react'
import type { DeviceUpdate } from '../../api/devices'
import { useI18n } from '../../i18n'
import Button from '../ui/Button'
import Input from '../ui/Input'
import Modal from '../ui/Modal'
import { DEVICE_CLASSES } from './DeviceClassIcon'

type BulkFields = Pick<DeviceUpdate, 'device_class' | 'responsible' | 'location' | 'description'>
type FieldKey = keyof BulkFields

interface Props {
  open: boolean
  count: number
  saving: boolean
  onClose: () => void
  onSave: (fields: BulkFields) => void
}

const emptyValues: Record<FieldKey, string> = {
  device_class: '',
  responsible: '',
  location: '',
  description: '',
}

export default function BulkEditDevicesModal({ open, count, saving, onClose, onSave }: Props) {
  const { t } = useI18n()
  const [enabled, setEnabled] = useState<Record<FieldKey, boolean>>({
    device_class: false,
    responsible: false,
    location: false,
    description: false,
  })
  const [values, setValues] = useState(emptyValues)

  useEffect(() => {
    if (!open) return
    setEnabled({ device_class: false, responsible: false, location: false, description: false })
    setValues(emptyValues)
  }, [open])

  const field = (key: FieldKey, label: string, content: React.ReactNode) => (
    <div className="rounded-lg border border-border bg-surface2/40 p-3">
      <label className="mb-2 flex items-center gap-2 text-sm font-medium text-text-muted">
        <input
          type="checkbox"
          checked={enabled[key]}
          onChange={(event) => setEnabled((current) => ({ ...current, [key]: event.target.checked }))}
          className="h-4 w-4 accent-primary"
        />
        {label}
      </label>
      <div className={enabled[key] ? '' : 'pointer-events-none opacity-45'}>{content}</div>
    </div>
  )

  const submit = () => {
    const fields: BulkFields = {}
    if (enabled.device_class) fields.device_class = values.device_class
    if (enabled.responsible) fields.responsible = values.responsible || null
    if (enabled.location) fields.location = values.location || null
    if (enabled.description) fields.description = values.description || null
    onSave(fields)
  }

  const hasSelection = Object.values(enabled).some(Boolean)

  return (
    <Modal open={open} onClose={onClose} title={t('bulk_edit_title', { count })}>
      <div className="flex flex-col gap-3">
        <p className="text-sm text-text-subtle">{t('bulk_edit_hint')}</p>
        {field('device_class', t('device_class'), (
          <>
            <Input
              list="bulk-device-classes"
              value={values.device_class}
              onChange={(event) => setValues((current) => ({ ...current, device_class: event.target.value }))}
              placeholder={t('custom_device_class_placeholder')}
            />
            <datalist id="bulk-device-classes">
              {DEVICE_CLASSES.map((value) => <option key={value} value={value} />)}
            </datalist>
          </>
        ))}
        {field('responsible', t('responsible'), (
          <Input value={values.responsible} onChange={(event) => setValues((current) => ({ ...current, responsible: event.target.value }))} placeholder={t('responsible_placeholder')} />
        ))}
        {field('location', t('location'), (
          <Input value={values.location} onChange={(event) => setValues((current) => ({ ...current, location: event.target.value }))} placeholder={t('location_placeholder')} />
        ))}
        {field('description', t('description'), (
          <textarea
            rows={3}
            className="input-field resize-none"
            value={values.description}
            onChange={(event) => setValues((current) => ({ ...current, description: event.target.value }))}
            placeholder={t('description_placeholder')}
          />
        ))}
        <p className="text-xs text-text-subtle">{t('bulk_edit_clear_hint')}</p>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>{t('cancel')}</Button>
          <Button loading={saving} disabled={!hasSelection || (enabled.device_class && !values.device_class.trim())} onClick={submit}>
            {t('apply_changes')}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
