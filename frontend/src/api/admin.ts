import apiClient from './client'

export const adminApi = {
  exportSettings: () =>
    apiClient.get('/admin/export/settings', { responseType: 'blob' }),

  exportDatabase: () =>
    apiClient.get('/admin/export/database', { responseType: 'blob' }),

  getFilenameFromDisposition: (contentDisposition?: string | null, fallback = 'download.bin') => {
    if (!contentDisposition) return fallback
    const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i)
    if (utf8Match?.[1]) return decodeURIComponent(utf8Match[1])
    const plainMatch = contentDisposition.match(/filename="?([^";]+)"?/i)
    return plainMatch?.[1] ?? fallback
  },

  importSettings: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<{ message: string }>('/admin/import/settings', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
}
