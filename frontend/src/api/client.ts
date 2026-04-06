import axios from 'axios'
import { withBasePath } from '../utils/basePath'

const apiClient = axios.create({
  baseURL: '/api',
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

// Redirect to login on 401
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      window.location.href = withBasePath('/login')
    }
    return Promise.reject(error)
  },
)

export default apiClient
