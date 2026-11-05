// Runtime validation coverage for student API request behavior.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { accountApi, ApiError, apiRequest } from './api'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('apiRequest', () => {
  it('sends JSON requests with the student bearer token', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ saved: true }), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(apiRequest('/api/v1/students/me/profile', {
      method: 'PUT',
      body: JSON.stringify({ full_name: 'A. Student' }),
    }, 'access-token')).resolves.toEqual({ saved: true })

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/students/me/profile')
    expect(new Headers(options.headers).get('Content-Type')).toBe('application/json')
    expect(new Headers(options.headers).get('Authorization')).toBe('Bearer access-token')
  })

  it('surfaces structured API errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        error: { code: 'PROFILE_NOT_VERIFIED', message: 'University review is required.' },
      }), { status: 403 }),
    ))

    await expect(apiRequest('/api/v1/students/me/applications', {}, 'access-token'))
      .rejects.toMatchObject({
        name: 'Error',
        status: 403,
        code: 'PROFILE_NOT_VERIFIED',
        message: 'University review is required.',
      } satisfies Partial<ApiError>)
  })

  it('reports unreadable server responses explicitly', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response('not-json', { status: 200 }),
    ))

    await expect(apiRequest('/api/v1/public/catalogs')).rejects.toMatchObject({
      status: 200,
      code: 'INVALID_RESPONSE',
    })
  })

  it('reports network failures explicitly', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))

    await expect(apiRequest('/api/v1/public/catalogs')).rejects.toMatchObject({
      status: 0,
      code: 'NETWORK_ERROR',
    })
  })
})

describe('accountApi', () => {
  function stubFetch(body: unknown, status = 200) {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }))
    vi.stubGlobal('fetch', fetchMock)
    return fetchMock
  }

  function sent(fetchMock: ReturnType<typeof vi.fn>) {
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit]
    return { url, method: options.method, body: JSON.parse(String(options.body)), auth: new Headers(options.headers).get('Authorization') }
  }

  it('registers an employer through the public employer endpoint without a token', async () => {
    const fetchMock = stubFetch({ ok: true, data: { company_id: 7, message: 'Check your email.' } }, 201)

    await expect(accountApi.registerEmployer({ company_name: 'Acme' })).resolves.toEqual({ company_id: 7, message: 'Check your email.' })
    expect(sent(fetchMock)).toEqual({ url: '/api/employer/register', method: 'POST', body: { company_name: 'Acme' }, auth: null })
  })

  it('confirms an employer email at the employer verify-email endpoint', async () => {
    const fetchMock = stubFetch({ ok: true, data: { message: 'Email verified.' } })

    await accountApi.verifyEmployerEmail('abc')
    expect(sent(fetchMock)).toMatchObject({ url: '/api/employer/verify-email', body: { token: 'abc' } })
  })

  it('keeps per-field messages from a rejected employer form', async () => {
    stubFetch({ ok: false, category: 'invalid', message: 'Please correct the form.', fields: { rep_email: 'Required' } }, 422)

    await expect(accountApi.registerEmployer({})).rejects.toMatchObject({
      status: 422,
      message: 'Please correct the form.',
      fields: { rep_email: 'Required' },
    })
  })

  it.each([
    ['registerUniversity', () => accountApi.registerUniversity({ university_name: 'Gulu University' }), '/api/v1/auth/register-university', { university_name: 'Gulu University' }],
    ['resendVerification', () => accountApi.resendVerification('a@b.ug'), '/api/v1/auth/resend-verification', { email: 'a@b.ug' }],
    ['forgotPassword', () => accountApi.forgotPassword('a@b.ug'), '/api/v1/auth/forgot-password', { email: 'a@b.ug' }],
    ['resetPassword', () => accountApi.resetPassword('tok', 'a-new-password'), '/api/v1/auth/reset-password', { token: 'tok', password: 'a-new-password' }],
  ])('%s posts to the account endpoint', async (_name, call, url, body) => {
    const fetchMock = stubFetch({ message: 'ok' }, 202)

    await expect(call()).resolves.toEqual({ message: 'ok' })
    expect(sent(fetchMock)).toEqual({ url, method: 'POST', body, auth: null })
  })
})
