// Runtime validation coverage for student API request behavior.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiRequest } from './api'

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
