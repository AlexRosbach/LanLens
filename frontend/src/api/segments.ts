import apiClient from './client'

export interface Segment {
  id: number
  name: string
  color: string
  ip_start: string
  ip_end: string
  description: string | null
  created_at: string
}

export interface SegmentCreate {
  name: string
  color?: string
  ip_start: string
  ip_end: string
  description?: string
}

export type SegmentUpdate = Partial<SegmentCreate>

export const segmentsApi = {
  list: () => apiClient.get<Segment[]>('/segments').then((r) => r.data),

  create: (data: SegmentCreate) =>
    apiClient.post<Segment>('/segments', data).then((r) => r.data),

  update: (id: number, data: SegmentUpdate) =>
    apiClient.put<Segment>(`/segments/${id}`, data).then((r) => r.data),

  delete: (id: number) => apiClient.delete(`/segments/${id}`),
}
