import apiClient from './client'

export const adminApi = {
  exportSettings: () =>
    apiClient.get('/admin/export/settings', { responseType: 'blob' }),

  exportDatabase: () =>
    apiClient.get('/admin/export/database', { responseType: 'blob' }),

  importSettings: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<{ message: string }>('/admin/import/settings', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
}
