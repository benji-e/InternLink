const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {
  status: number
  code: string
  /** Per-field messages, e.g. { rep_email: 'Required' }, when the server sends them. */
  fields: Record<string, string>

  constructor(status: number, code: string, message: string, fields: Record<string, string> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.fields = fields
  }
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
  token?: string,
): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (token) headers.set('Authorization', `Bearer ${token}`)

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', 'Could not reach InternLink. Check your connection and try again.')
  }

  const text = await response.text()
  let payload: Record<string, unknown> = {}
  if (text) {
    try {
      payload = JSON.parse(text) as Record<string, unknown>
    } catch {
      throw new ApiError(response.status, 'INVALID_RESPONSE', 'The server returned an unreadable response.')
    }
  }
  if (!response.ok) {
    const error = payload.error as { code?: string; message?: string } | undefined
    const detail = typeof payload.detail === 'string' ? payload.detail : undefined
    const fields = payload.fields && typeof payload.fields === 'object' ? payload.fields as Record<string, string> : {}
    throw new ApiError(
      response.status,
      error?.code ?? 'REQUEST_FAILED',
      error?.message ?? detail ?? (typeof payload.message === 'string' ? payload.message : undefined) ?? 'The request could not be completed.',
      fields,
    )
  }
  return payload as T
}

export type CatalogItem = { id: number; name: string }
export type University = CatalogItem & { location: string; email_domain?: string }
export type CatalogProgramme = CatalogItem & { programme_group: string }
export type CatalogDepartment = CatalogItem & { programmes: CatalogProgramme[] }
export type CoordinatorCatalog = { departments: CatalogDepartment[]; programme_groups: string[]; can_add_departments: boolean }
export type AuthUser = { user_id: number; full_name: string; email: string; role: 'student' | 'employer' | 'university' | 'admin' }

export async function employerRequest<T>(action: string, token: string, payload: Record<string, unknown> = {}) {
  const result = await apiRequest<{ ok: boolean; data: T }>(
    `/api/employer/${action}`,
    { method: 'POST', body: JSON.stringify(payload) },
    token,
  )
  return result.data
}

/** Employer registration and email confirmation need no sign-in. */
export async function employerPublicRequest<T>(action: 'register' | 'verify_email', payload: Record<string, unknown>) {
  const result = await apiRequest<{ ok: boolean; data: T }>(
    `/api/employer/${action === 'verify_email' ? 'verify-email' : action}`,
    { method: 'POST', body: JSON.stringify(payload) },
  )
  return result.data
}

const postJson = <T,>(path: string, body: Record<string, unknown>) =>
  apiRequest<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const accountApi = {
  registerEmployer: (input: Record<string, unknown>) =>
    employerPublicRequest<{ company_id: number; message: string }>('register', input),
  verifyEmployerEmail: (token: string) =>
    employerPublicRequest<{ message: string }>('verify_email', { token }),
  registerUniversity: (input: Record<string, unknown>) =>
    postJson<{ message: string }>('/api/v1/auth/register-university', input),
  resendVerification: (email: string) =>
    postJson<{ message: string }>('/api/v1/auth/resend-verification', { email }),
  forgotPassword: (email: string) =>
    postJson<{ message: string }>('/api/v1/auth/forgot-password', { email }),
  resetPassword: (token: string, password: string) =>
    postJson<{ message: string }>('/api/v1/auth/reset-password', { token, password }),
}

export const studentApi = {
  login: (email: string, password: string) =>
    apiRequest<{ access_token: string; user: AuthUser }>(
      '/api/v1/auth/login',
      { method: 'POST', body: JSON.stringify({ email, password }) },
    ),
  register: (input: Record<string, unknown>) =>
    apiRequest<{ message: string }>('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify(input),
    }),
  verifyEmail: (token: string) =>
    apiRequest<{ verified: boolean; role: string; awaiting_review: boolean }>('/api/v1/auth/verify-email', {
      method: 'POST',
      body: JSON.stringify({ token }),
    }),
  universities: () => apiRequest<{ universities: University[] }>('/api/v1/public/universities'),
  departments: (universityId: number) =>
    apiRequest<{ departments: CatalogItem[] }>(`/api/v1/public/universities/${universityId}/departments`),
  programmes: (departmentId: number) =>
    apiRequest<{ programmes: CatalogItem[] }>(`/api/v1/public/departments/${departmentId}/programmes`),
  catalogs: () => apiRequest<{ skills: CatalogItem[]; interests: CatalogItem[] }>('/api/v1/public/catalogs'),
  profile: (token: string) =>
    apiRequest<{ profile: Record<string, unknown> }>('/api/v1/students/me/profile', {}, token),
  saveProfile: (token: string, profile: Record<string, unknown>) =>
    apiRequest<{ profile: Record<string, unknown> }>(
      '/api/v1/students/me/profile',
      { method: 'PUT', body: JSON.stringify(profile) },
      token,
    ),
  opportunities: (token: string, query: URLSearchParams) =>
    apiRequest<{ results: Record<string, unknown>[]; count: number }>(
      `/api/v1/opportunities?${query.toString()}`,
      {},
      token,
    ),
  recommendations: (token: string) =>
    apiRequest<{ results: Record<string, unknown>[]; count: number }>(
      '/api/v1/students/me/recommendations?limit=10',
      {},
      token,
    ),
  applications: (token: string) =>
    apiRequest<{ applications: Record<string, unknown>[] }>(
      '/api/v1/students/me/applications',
      {},
      token,
    ),
  apply: (token: string, listingId: number, coverNote: string) =>
    apiRequest<{ application: Record<string, unknown> }>(
      '/api/v1/students/me/applications',
      { method: 'POST', body: JSON.stringify({ listing_id: listingId, cover_note: coverNote }) },
      token,
    ),
  withdraw: (token: string, applicationId: number) =>
    apiRequest<{ application: Record<string, unknown> }>(
      `/api/v1/students/me/applications/${applicationId}/withdraw`,
      { method: 'POST' },
      token,
    ),
  notifications: (token: string) =>
    apiRequest<{ notifications: Record<string, unknown>[] }>(
      '/api/v1/students/me/notifications',
      {},
      token,
    ),
  markNotificationRead: (token: string, notificationId: number) =>
    apiRequest<{ notification_id: number; is_read: boolean }>(
      `/api/v1/students/me/notifications/${notificationId}/read`,
      { method: 'POST' },
      token,
    ),
}

export const roleApi = {
  adminRegistrations: (token: string) =>
    apiRequest<{ registrations: Record<string, unknown>[] }>('/api/v1/admin/registrations', {}, token),
  adminUsers: (token: string) =>
    apiRequest<{ users: Record<string, unknown>[] }>('/api/v1/admin/users', {}, token),
  adminAudit: (token: string) =>
    apiRequest<{ events: Record<string, unknown>[] }>('/api/v1/admin/audit', {}, token),
  decideRegistration: (token: string, type: string, id: number, action: string, reason?: string) =>
    apiRequest<{ status: string }>(`/api/v1/admin/registrations/${type}/${id}`, {
      method: 'POST',
      body: JSON.stringify({ action, reason }),
    }, token),
  updateUser: (token: string, id: number, status: string) =>
    apiRequest<{ user_id: number; status: string }>(`/api/v1/admin/users/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    }, token),
  coordinatorDashboard: (token: string) =>
    apiRequest<{ stats: Record<string, number> }>('/api/v1/coordinator/dashboard', {}, token),
  coordinatorStudents: (token: string) =>
    apiRequest<{ students: Record<string, unknown>[] }>('/api/v1/coordinator/students', {}, token),
  coordinatorPlacements: (token: string) =>
    apiRequest<{ placements: Record<string, unknown>[] }>('/api/v1/coordinator/placements', {}, token),
  coordinatorCatalog: (token: string) =>
    apiRequest<CoordinatorCatalog>('/api/v1/coordinator/catalog', {}, token),
  addDepartment: (token: string, name: string) =>
    apiRequest<{ department: CatalogDepartment }>('/api/v1/coordinator/departments', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }, token),
  addProgramme: (token: string, departmentId: number, name: string, programmeGroup: string) =>
    apiRequest<{ programme: CatalogProgramme }>('/api/v1/coordinator/programmes', {
      method: 'POST',
      body: JSON.stringify({ department_id: departmentId, name, programme_group: programmeGroup }),
    }, token),
  verifyStudent: (token: string, id: number) =>
    apiRequest<{ student_id: number; verified: boolean }>(`/api/v1/coordinator/students/${id}`, { method: 'POST' }, token),
  decidePlacement: (token: string, id: number, action: string, reason?: string) =>
    apiRequest<{ placement_id: number; status: string }>(`/api/v1/coordinator/placements/${id}`, {
      method: 'POST',
      body: JSON.stringify({ action, reason }),
    }, token),
}

export type ListingSummary = {
  listing_id: number
  title: string
  company_name: string
  sector: string
  location: string
  is_remote: boolean
  duration_weeks: number
  slots_remaining: number
  application_deadline: string
  posted_at: string
  required_skills: string[]
  application_status?: string | null
}

export type MatchDetail = {
  score: number
  breakdown: Record<'skills' | 'programme' | 'interests' | 'location', number | null>
  weights: Record<'skills' | 'programme' | 'interests' | 'location', number>
  matched_skills: string[]
  missing_skills: string[]
}

export type ListingDetail = ListingSummary & {
  description: string
  slots: number
  accepted_programmes: string[]
  optional_skills: string[]
  days_left: number
  company_id: number
  company_description: string | null
  company_location: string
  company_website: string | null
  company_open_listings: number
  similar: { listing_id: number; title: string; company_name: string }[]
  match: MatchDetail | null
  application: { application_id: number; status: string; submitted_at: string } | null
}

export type SearchResult = {
  results: ListingSummary[]
  count: number
  page: number
  page_size: number
  sectors: { name: string; count: number }[]
}

export type ProgrammeOption = CatalogItem & { department_id: number; department: string }

export type MessageItem = { message_id: number; body: string; sent_at: string; is_read: boolean; mine: boolean; sender_name?: string }
export type MessageThread = {
  application: { application_id: number; status: string; title: string; company_name: string }
  employer_name: string | null
  messages: MessageItem[]
  can_reply: boolean
}

/** Pages that work without signing in. A student token adds match details. */
export const publicApi = {
  home: () =>
    apiRequest<{ latest: ListingSummary[]; universities: string[]; locations: string[] }>('/api/v1/public/home'),
  search: (query: URLSearchParams, token?: string) =>
    apiRequest<SearchResult>(`/api/v1/public/opportunities?${query.toString()}`, {}, token),
  detail: (id: number, token?: string) =>
    apiRequest<{ opportunity: ListingDetail }>(`/api/v1/public/opportunities/${id}`, {}, token),
  universityProgrammes: (universityId: number) =>
    apiRequest<{ programmes: ProgrammeOption[] }>(`/api/v1/public/universities/${universityId}/programmes`),
  requestUniversity: (input: { university_name: string; requester_email: string; coordinator_email?: string }) =>
    postJson<{ message: string }>('/api/v1/public/university-requests', input),
}

export const messageApi = {
  thread: (token: string, applicationId: number) =>
    apiRequest<MessageThread>(`/api/v1/students/me/applications/${applicationId}/messages`, {}, token),
  reply: (token: string, applicationId: number, body: string) =>
    apiRequest<{ message: MessageItem }>(
      `/api/v1/students/me/applications/${applicationId}/messages`,
      { method: 'POST', body: JSON.stringify({ body }) },
      token,
    ),
}
