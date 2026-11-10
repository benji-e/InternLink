import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { Menu } from 'lucide-react'
import {
  alertApi, ApiError, companyLogoUrl, cvApi, publicApi, savedApi, studentApi,
  type AuthUser, type ListingDetail, type ListingSummary, type SearchResult,
} from './api'
import { SuggestCompany } from './CompanyPages'
import { linkTo, navigate } from './router'
import './site.css'

export type SiteSession = { token: string; user: AuthUser } | null

const POPULAR = ['Software', 'Accounting', 'Data', 'Telecoms', 'Remote']

export function messageOf(error: unknown) {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}

export function initialsOf(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join('') || 'IL'
}

export function shortDate(value: string | null | undefined) {
  if (!value) return ''
  const date = new Date(value.length === 10 ? `${value}T00:00:00` : value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('en-UG', { day: 'numeric', month: 'short' }).format(date)
}

export function workplace(listing: Pick<ListingSummary, 'location' | 'is_remote'>) {
  return listing.is_remote ? `Remote${listing.location ? ` · ${listing.location}` : ''}` : listing.location
}

function plural(count: number, word: string) {
  return `${count} ${word}${count === 1 ? '' : 's'}`
}

/** A company's logo, or its initials when it has none (or the image fails to load). */
export function CompanyLogo({ companyId, name, hasLogo, large }: { companyId?: number | null; name: string; hasLogo?: boolean; large?: boolean }) {
  const [failed, setFailed] = useState(false)
  const className = `logo-box ${large ? 'is-lg' : ''}`
  if (!hasLogo || !companyId || failed) return <span className={className} aria-hidden="true">{initialsOf(name)}</span>
  return <img className={`${className} logo-img`} src={companyLogoUrl(companyId)} alt={`${name} logo`} loading="lazy" onError={() => setFailed(true)} />
}

export function Wordmark({ suffix, to = '/' }: { suffix?: string; to?: string }) {
  return <a className="wordmark" {...linkTo(to)}>intern<span>link</span>{suffix && <small>{suffix}</small>}</a>
}

export function SiteHeader({ session, active }: { session: SiteSession; active?: 'browse' | 'companies' | 'employers' | 'universities' | 'how' }) {
  const [open, setOpen] = useState(false)
  return (
    <header className="site-header">
      <div className="site-container site-header-inner">
        <button className="btn btn-sm site-menu-toggle" aria-label="Menu" aria-expanded={open} onClick={() => setOpen((value) => !value)}><Menu size={18} /></button>
        <Wordmark />
        <nav className={`site-nav ${open ? 'is-open' : ''}`} aria-label="Main">
          <a className={active === 'browse' ? 'is-active' : ''} {...linkTo('/internships')}>Browse internships</a>
          <a className={active === 'companies' ? 'is-active' : ''} {...linkTo('/companies')}>Companies</a>
          {!session && <>
            <a className={active === 'employers' ? 'is-active' : ''} {...linkTo('/#employers')} onClick={(event) => { event.preventDefault(); scrollToSection('employers') }}>For employers</a>
            <a className={active === 'universities' ? 'is-active' : ''} {...linkTo('/#universities')} onClick={(event) => { event.preventDefault(); scrollToSection('universities') }}>For universities</a>
            <a className={active === 'how' ? 'is-active' : ''} {...linkTo('/#how')} onClick={(event) => { event.preventDefault(); scrollToSection('how') }}>How it works</a>
          </>}
        </nav>
        <div className="site-header-actions">
          {session ? <>
            <a className="btn" {...linkTo('/dashboard')}>My dashboard</a>
            <span className="site-avatar" title={session.user.full_name}>{initialsOf(session.user.full_name)}</span>
          </> : <>
            <a className="btn hide-sm" {...linkTo('/signin')}>Sign in</a>
            <a className="btn btn-primary" {...linkTo('/signup')}>Create account</a>
          </>}
        </div>
      </div>
    </header>
  )
}

function scrollToSection(id: string) {
  if (window.location.pathname !== '/') {
    navigate('/')
    window.setTimeout(() => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' }), 60)
  } else {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
  }
}

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="site-container">
        <div><Wordmark /><div className="muted" style={{ fontSize: 14, marginTop: 4 }}>© 2026 InternLink Uganda</div></div>
        <div className="footer-cols">
          <div><h4>Students</h4><a {...linkTo('/internships')}>Browse internships</a><a {...linkTo('/companies')}>Companies</a><a {...linkTo('/signup')}>Create account</a></div>
          <div><h4>Organisations</h4><a {...linkTo('/signup?type=employer')}>Post an internship</a><a {...linkTo('/signup?type=university')}>Join as a university</a></div>
          <div><h4>Help</h4><a href="/#how" onClick={(event) => { event.preventDefault(); scrollToSection('how') }}>How it works</a><a href="mailto:hello@internlink.ug">Contact</a></div>
        </div>
      </div>
    </footer>
  )
}

export function SiteLayout({ session, active, grey, children }: { session: SiteSession; active?: 'browse' | 'companies'; grey?: boolean; children: ReactNode }) {
  return (
    <div className={`site ${grey ? 'is-grey' : ''}`}>
      <SiteHeader session={session} active={active} />
      <main className="site-main">{children}</main>
      <SiteFooter />
    </div>
  )
}

/** Save/unsave for students. Visitors are sent to sign in first; other roles see nothing. */
export function SaveButton({ session, listingId, saved, onChange }: { session: SiteSession; listingId: number; saved?: boolean; onChange?: (saved: boolean) => void }) {
  const [isSaved, setSaved] = useState(Boolean(saved))
  const [busy, setBusy] = useState(false)
  useEffect(() => setSaved(Boolean(saved)), [saved])
  if (session && session.user.role !== 'student') return null
  async function toggle() {
    if (!session) {
      navigate(`/signin?next=${encodeURIComponent(window.location.pathname + window.location.search)}`)
      return
    }
    setBusy(true)
    try {
      if (isSaved) await savedApi.unsave(session.token, listingId)
      else await savedApi.save(session.token, listingId)
      setSaved(!isSaved)
      onChange?.(!isSaved)
    } catch {
      // Leave the button as it was; the next page load shows the true state.
    } finally {
      setBusy(false)
    }
  }
  return <button type="button" className={`btn btn-sm ${isSaved ? 'is-saved' : ''}`} aria-pressed={isSaved} disabled={busy} onClick={() => void toggle()}>{isSaved ? 'Saved' : 'Save'}</button>
}

function ListingTile({ listing, session }: { listing: ListingSummary; session: SiteSession }) {
  return (
    <article className="listing-tile">
      <div className="company-line"><CompanyLogo companyId={listing.company_id} name={listing.company_name} hasLogo={listing.has_logo} /><span>{listing.company_name} · {listing.sector}</span></div>
      <a className="listing-title" {...linkTo(`/internships/${listing.listing_id}`)}>{listing.title}</a>
      <div className="listing-meta">{workplace(listing)} · {listing.duration_weeks} weeks · {plural(listing.slots_remaining, 'position')}</div>
      <div className="listing-foot"><span>Closes {shortDate(listing.application_deadline)}</span><SaveButton session={session} listingId={listing.listing_id} saved={listing.saved} /></div>
    </article>
  )
}

export function HomePage({ session }: { session: SiteSession }) {
  const [data, setData] = useState<{ latest: ListingSummary[]; universities: string[]; locations: string[] } | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [location, setLocation] = useState('')

  useEffect(() => {
    publicApi.home(session?.user.role === 'student' ? session.token : undefined).then(setData).catch((reason: unknown) => setError(messageOf(reason)))
  }, [session?.token])

  useEffect(() => {
    const hash = window.location.hash.slice(1)
    if (hash && data) document.getElementById(hash)?.scrollIntoView()
  }, [data])

  function search(event?: FormEvent, term = query) {
    event?.preventDefault()
    const params = new URLSearchParams()
    if (term === 'Remote') params.set('remote', 'true')
    else if (term.trim()) params.set('q', term.trim())
    if (location) params.set('location', location)
    navigate(`/internships${params.toString() ? `?${params}` : ''}`)
  }

  return (
    <SiteLayout session={session}>
      <section className="hero">
        <div className="site-container hero-grid">
          <div>
            <span className="eyebrow-s">Internships across Uganda</span>
            <h1>Find an internship that fits your course.</h1>
            <p>Search verified internships, apply with one profile, and track every application in one place.</p>
            <form className="search-bar" role="search" onSubmit={search}>
              <label className="sr-only" htmlFor="home-q">Role, skill or company</label>
              <input id="home-q" className="search-input" placeholder="Role, skill or company" value={query} onChange={(event) => setQuery(event.target.value)} />
              <label className="sr-only" htmlFor="home-loc">Location</label>
              <select id="home-loc" className="search-select" value={location} onChange={(event) => setLocation(event.target.value)}>
                <option value="">Any location</option>
                {data?.locations.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
              <button className="btn btn-primary">Search</button>
            </form>
            <div className="popular">Popular: {POPULAR.map((item) => <button key={item} type="button" onClick={() => search(undefined, item)}>{item}</button>)}</div>
          </div>
          <div className="placeholder-box hero-photo" role="img" aria-label="Students working with a mentor">Students working with a mentor</div>
        </div>
      </section>

      {!!data?.universities.length && <section className="band partner-band">
        <div className="site-container">
          <span className="eyebrow-s" style={{ margin: 0 }}>Partner universities</span>
          <div className="partner-list">{data.universities.slice(0, 5).map((name) => <span key={name}>{name}</span>)}</div>
        </div>
      </section>}

      <section className="section">
        <div className="site-container">
          <div className="section-head">
            <div><span className="eyebrow-s">Open now</span><h2>Latest internships</h2></div>
            <a {...linkTo('/internships')}>View all internships</a>
          </div>
          {error && <div className="notice is-error">{error}</div>}
          {!data && !error && <div className="empty">Loading internships…</div>}
          {data && data.latest.length === 0 && <div className="empty">No internships are open right now. Check back soon.</div>}
          {data && data.latest.length > 0 && <div className="listing-grid">{data.latest.map((item) => <ListingTile key={item.listing_id} listing={item} session={session} />)}</div>}
        </div>
      </section>

      <section className="section band">
        <div className="site-container">
          <span className="eyebrow-s">Three ways in</span>
          <h2 style={{ fontSize: 28, marginBottom: 18 }}>Who InternLink is for</h2>
          <div className="audience-grid">
            <article className="audience-card" id="students">
              <div className="placeholder-box">Students</div>
              <h3>Students</h3>
              <ul><li>Recommendations based on your course and skills</li><li>Apply with one profile</li><li>Track applications and message employers</li></ul>
              <a className="btn btn-primary" {...linkTo('/signup?type=student')}>Create a student account</a>
            </article>
            <article className="audience-card" id="employers">
              <div className="placeholder-box">Employers</div>
              <h3>Employers</h3>
              <ul><li>Post internships for free</li><li>See applicants ranked by fit</li><li>Shortlist, message and make offers</li></ul>
              <a className="btn" {...linkTo('/signup?type=employer')}>Register your company</a>
            </article>
            <article className="audience-card" id="universities">
              <div className="placeholder-box">Universities</div>
              <h3>Universities</h3>
              <ul><li>Verify your students</li><li>Approve placements</li><li>Export placement reports</li></ul>
              <a className="btn" {...linkTo('/signup?type=university')}>Bring your university on board</a>
            </article>
          </div>
        </div>
      </section>

      <section className="section" id="how">
        <div className="site-container">
          <span className="eyebrow-s">How it works</span>
          <h2 style={{ fontSize: 28, marginBottom: 18 }}>From sign-up to placement</h2>
          <div className="steps-grid">
            <div className="step-card"><b>1</b><h3>Create your account</h3><p>Sign up with your university email and confirm it.</p></div>
            <div className="step-card"><b>2</b><h3>Build your profile</h3><p>Add your skills and interests.</p></div>
            <div className="step-card"><b>3</b><h3>Apply</h3><p>See why each internship matches you, then apply in two clicks.</p></div>
            <div className="step-card"><b>4</b><h3>Get placed</h3><p>Your university approves the placement and tracks it with you.</p></div>
          </div>
        </div>
      </section>
    </SiteLayout>
  )
}

const DURATIONS: Record<string, { label: string; min?: string; max?: string }> = {
  short: { label: 'Up to 8 weeks', max: '8' },
  mid: { label: '9–16 weeks', min: '9', max: '16' },
  long: { label: '17+ weeks', min: '17' },
}

export function InternshipsPage({ session, search }: { session: SiteSession; search: string }) {
  const params = useMemo(() => new URLSearchParams(search), [search])
  const [query, setQuery] = useState(params.get('q') ?? '')
  const [location, setLocation] = useState(params.get('location') ?? '')
  const [locations, setLocations] = useState<string[]>([])
  const [result, setResult] = useState<SearchResult | null>(null)
  const [error, setError] = useState('')
  const isStudent = session?.user.role === 'student'
  const token = isStudent ? session?.token : undefined

  useEffect(() => { publicApi.home().then((data) => setLocations(data.locations)).catch(() => undefined) }, [])
  useEffect(() => { setQuery(params.get('q') ?? ''); setLocation(params.get('location') ?? '') }, [params])

  useEffect(() => {
    const api = new URLSearchParams()
    for (const key of ['q', 'location', 'sector', 'remote', 'closing_soon', 'my_programme', 'sort', 'page']) {
      const value = params.get(key)
      if (value) api.set(key, value)
    }
    const duration = DURATIONS[params.get('duration') ?? '']
    if (duration?.min) api.set('min_weeks', duration.min)
    if (duration?.max) api.set('max_weeks', duration.max)
    api.set('page_size', '10')
    let current = true
    setError('')
    publicApi.search(api, token)
      .then((data) => { if (current) setResult(data) })
      .catch((reason: unknown) => { if (current) setError(messageOf(reason)) })
    return () => { current = false }
  }, [params, token])

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    if (!('page' in changes)) next.delete('page')
    navigate(`/internships${next.toString() ? `?${next}` : ''}`, { replace: true })
  }

  const page = result?.page ?? 1
  const pages = result ? Math.max(1, Math.ceil(result.count / result.page_size)) : 1
  const [alertState, setAlertState] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [alertMessage, setAlertMessage] = useState('')
  useEffect(() => { setAlertState('idle'); setAlertMessage('') }, [params])

  /** Save the current filters as a job alert (students); visitors sign in first. */
  async function createAlert() {
    if (!session) {
      navigate(`/signin?next=${encodeURIComponent(`/internships?${params}`)}`)
      return
    }
    const filters: Record<string, string> = {}
    for (const key of ['q', 'location', 'sector', 'remote', 'duration', 'my_programme']) {
      const value = params.get(key)
      if (value) filters[key] = value
    }
    setAlertState('saving')
    try {
      const { alert, created } = await alertApi.create(session.token, filters)
      setAlertState('saved')
      setAlertMessage(created ? `Job alert saved: ${alert.label}. We'll email you when new internships match.` : `You already have this alert: ${alert.label}.`)
    } catch (reason) {
      setAlertState('idle')
      setAlertMessage(messageOf(reason))
    }
  }

  return (
    <SiteLayout session={session} active="browse" grey>
      <div className="site-container page-pad">
        <h1 className="page-title">Internships</h1>
        <form className="search-row" role="search" onSubmit={(event) => { event.preventDefault(); update({ q: query.trim() || null, location: location || null }) }}>
          <label className="sr-only" htmlFor="q">Role, skill or company</label>
          <input id="q" className="search-input" placeholder="Role, skill or company" value={query} onChange={(event) => setQuery(event.target.value)} />
          <label className="sr-only" htmlFor="loc">Location</label>
          <select id="loc" className="search-select" value={location} onChange={(event) => { setLocation(event.target.value); update({ location: event.target.value || null }) }}>
            <option value="">Any location</option>
            {locations.map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
          <button className="btn btn-primary">Search</button>
          {(!session || isStudent) && <button type="button" className="btn" disabled={alertState === 'saving'} onClick={() => void createAlert()}>
            {alertState === 'saved' ? 'Alert saved ✓' : 'Get alerts for this search'}
          </button>}
        </form>
        {alertMessage && <div className={`notice ${alertState === 'saved' ? 'is-ok' : 'is-error'}`} role="status" style={{ marginBottom: 14 }}>{alertMessage}</div>}
        <div className="browse-grid">
          <aside className="filters" aria-label="Filters">
            <div className="filters-head"><h2>Filters</h2><button className="btn-link" onClick={() => navigate('/internships', { replace: true })}>Clear all</button></div>
            <fieldset>
              <legend>Sector</legend>
              <label><input type="radio" name="sector" checked={!params.get('sector')} onChange={() => update({ sector: null })} /><span>All sectors</span></label>
              {result?.sectors.map((item) => (
                <label key={item.name}><input type="radio" name="sector" checked={params.get('sector') === item.name} onChange={() => update({ sector: item.name })} /><span>{item.name}</span><span className="count">{item.count}</span></label>
              ))}
            </fieldset>
            <fieldset>
              <legend>Work type</legend>
              <label><input type="checkbox" checked={params.get('remote') === 'false'} onChange={(event) => update({ remote: event.target.checked ? 'false' : null })} /><span>On site</span></label>
              <label><input type="checkbox" checked={params.get('remote') === 'true'} onChange={(event) => update({ remote: event.target.checked ? 'true' : null })} /><span>Remote</span></label>
            </fieldset>
            <fieldset>
              <legend>Duration</legend>
              <label><input type="radio" name="duration" checked={!params.get('duration')} onChange={() => update({ duration: null })} /><span>Any length</span></label>
              {Object.entries(DURATIONS).map(([key, item]) => (
                <label key={key}><input type="radio" name="duration" checked={params.get('duration') === key} onChange={() => update({ duration: key })} /><span>{item.label}</span></label>
              ))}
            </fieldset>
            <fieldset>
              <legend>Other</legend>
              <label><input type="checkbox" checked={params.get('closing_soon') === 'true'} onChange={(event) => update({ closing_soon: event.target.checked ? 'true' : null })} /><span>Closing this week</span></label>
              {isStudent && <label><input type="checkbox" checked={params.get('my_programme') === 'true'} onChange={(event) => update({ my_programme: event.target.checked ? 'true' : null })} /><span>Open to my programme</span></label>}
            </fieldset>
          </aside>
          <section aria-live="polite">
            <div className="results-head">
              <div><b>{result ? plural(result.count, 'internship') : '…'}</b> <span className="muted">match your filters</span></div>
              <label className="muted" style={{ fontSize: 14 }}>Sort by{' '}
                <select className="search-select" value={params.get('sort') ?? 'closing'} onChange={(event) => update({ sort: event.target.value === 'closing' ? null : event.target.value })}>
                  <option value="closing">Closing soonest</option>
                  <option value="newest">Newest</option>
                </select>
              </label>
            </div>
            {!session && <div className="signin-strip"><span>Sign in to see how well each internship matches your course and skills.</span><a className="btn btn-primary btn-sm" {...linkTo('/signin')}>Sign in</a></div>}
            {error && <div className="notice is-error">{error}</div>}
            {result && result.results.length === 0 && <>
              <div className="card empty">No internships match these filters. Try clearing some, or look through <a {...linkTo(`/companies${params.get('q') ? `?q=${encodeURIComponent(params.get('q') ?? '')}` : ''}`)}>companies</a>.</div>
              {params.get('q') && <SuggestCompany initialName={params.get('q') ?? ''} />}
            </>}
            {result?.results.map((item) => (
              <article key={item.listing_id} className="result-card">
                <CompanyLogo companyId={item.company_id} name={item.company_name} hasLogo={item.has_logo} />
                <div>
                  <div className="muted" style={{ fontSize: 13 }}>{item.company_name} · Verified employer</div>
                  <a className="listing-title" {...linkTo(`/internships/${item.listing_id}`)}>{item.title}</a>
                  <div className="listing-meta" style={{ margin: '4px 0 8px' }}>{workplace(item)} · {item.duration_weeks} weeks · {plural(item.slots_remaining, 'position')}</div>
                  <div className="chip-row">{item.required_skills.map((skill) => <span key={skill} className="chip">{skill}</span>)}</div>
                </div>
                <div className="result-side">
                  <span>Closes {shortDate(item.application_deadline)}</span>
                  {item.application_status ? <span className="status-pill is-blue">Applied</span> : <SaveButton session={session} listingId={item.listing_id} saved={item.saved} />}
                </div>
              </article>
            ))}
            {pages > 1 && <nav className="pager" aria-label="Pages">
              <button className="btn btn-sm" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}>Previous</button>
              {Array.from({ length: Math.min(pages, 7) }, (_, index) => index + 1).map((number) => (
                <button key={number} className={`btn btn-sm ${number === page ? 'is-current' : ''}`} aria-current={number === page ? 'page' : undefined} onClick={() => update({ page: String(number) })}>{number}</button>
              ))}
              <button className="btn btn-sm" disabled={page >= pages} onClick={() => update({ page: String(page + 1) })}>Next</button>
            </nav>}
          </section>
        </div>
      </div>
    </SiteLayout>
  )
}

const MATCH_PARTS = ['skills', 'programme', 'interests', 'location'] as const

export function InternshipDetailPage({ session, id, onApplied }: { session: SiteSession; id: number; onApplied?: () => void }) {
  const [listing, setListing] = useState<ListingDetail | null>(null)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [applyError, setApplyError] = useState('')
  const [verified, setVerified] = useState<boolean | null>(null)
  const isStudent = session?.user.role === 'student'
  const token = isStudent ? session?.token : undefined

  function load() {
    setError('')
    publicApi.detail(id, token)
      .then((data) => setListing(data.opportunity))
      .catch((reason: unknown) => setError(messageOf(reason)))
  }
  useEffect(load, [id, token])
  const [cvName, setCvName] = useState<string | null | undefined>(undefined)
  useEffect(() => {
    if (!token) return
    studentApi.profile(token).then((data) => setVerified(Boolean(data.profile.verified))).catch(() => undefined)
    cvApi.info(token).then((data) => setCvName(data.cv?.filename ?? null)).catch(() => setCvName(null))
  }, [token])

  async function apply(event: FormEvent) {
    event.preventDefault()
    if (!token) return
    setBusy(true)
    setApplyError('')
    try {
      await studentApi.apply(token, id, note)
      onApplied?.()
      load()
    } catch (reason) {
      setApplyError(reason instanceof ApiError && reason.status === 401 ? 'Your session has expired. Sign in again.' : messageOf(reason))
    } finally {
      setBusy(false)
    }
  }

  if (error) return <SiteLayout session={session} grey><div className="site-container page-pad"><div className="card"><h2>Internship not available</h2><p className="muted">{error}</p><a className="btn" {...linkTo('/internships')}>Browse internships</a></div></div></SiteLayout>
  if (!listing) return <SiteLayout session={session} grey><div className="site-container page-pad empty">Loading…</div></SiteLayout>

  const applied = listing.application
  const canApply = isStudent && !applied && verified !== false
  return (
    <SiteLayout session={session} active="browse" grey>
      <div className="site-container page-pad">
        <div className="crumbs"><a {...linkTo('/internships')}>Internships</a> / <a {...linkTo(`/internships?sector=${encodeURIComponent(listing.sector)}`)}>{listing.sector}</a> / {listing.title}</div>
        <div className="detail-grid">
          <div className="detail-main">
            <section className="card">
              <div className="company-line" style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <CompanyLogo companyId={listing.company_id} name={listing.company_name} hasLogo={listing.has_logo} large />
                <div><b>{listing.company_name}</b><div style={{ color: 'var(--s-green)', fontSize: 13, fontWeight: 600 }}>Verified employer</div></div>
              </div>
              <h1 className="detail-title">{listing.title}</h1>
              <div className="facts"><span>{workplace(listing)}</span><span>{listing.duration_weeks} weeks</span><span>{plural(listing.slots_remaining, 'position')} open</span><span>{listing.sector}</span></div>
            </section>

            {listing.match && <section className="card is-accent" aria-label="Why this matches you">
              <div className="match-head"><h2>Why this matches you</h2><span className="score" style={{ fontSize: 26 }}>{listing.match.score}% match</span></div>
              <div className="match-bars">
                {MATCH_PARTS.map((part) => {
                  const value = listing.match?.breakdown[part]
                  return <div key={part}><span>{part.toUpperCase()} ({listing.match?.weights[part]}%)</span><div className="bar" title={value == null ? 'Not used' : `${Math.round(value * 100)}%`}><i style={{ width: `${Math.round((value ?? 0) * 100)}%` }} /></div></div>
                })}
              </div>
              {listing.match.matched_skills.length > 0 && <div className="match-row"><b>You have</b><div className="chip-row">{listing.match.matched_skills.map((skill) => <span key={skill} className="chip chip-green">{skill}</span>)}</div></div>}
              {listing.match.missing_skills.length > 0 && <div className="match-row"><b>You could add</b><div className="chip-row">{listing.match.missing_skills.map((skill) => <span key={skill} className="chip chip-amber">{skill}</span>)}</div><a {...linkTo('/dashboard?page=profile')}>Add to my profile</a></div>}
            </section>}

            <section className="card">
              <h2>About the role</h2>
              <p className="prose">{listing.description}</p>
              {(listing.required_skills.length > 0 || listing.optional_skills.length > 0) && <>
                <h3 style={{ fontSize: 16, margin: '16px 0 8px' }}>Skills</h3>
                <div className="chip-row">
                  {listing.required_skills.map((skill) => <span key={skill} className="chip">{skill}</span>)}
                  {listing.optional_skills.map((skill) => <span key={skill} className="chip chip-outline">{skill} (nice to have)</span>)}
                </div>
              </>}
              <h3 style={{ fontSize: 16, margin: '16px 0 6px' }}>Who can apply</h3>
              <p className="muted" style={{ margin: 0 }}>{listing.accepted_programmes.length ? listing.accepted_programmes.join(', ') : 'Students from any programme'}</p>
            </section>

            {isStudent && <section className="card" id="apply">
              <span className="eyebrow-s">Apply</span>
              <h2>Your application</h2>
              {applied ? <div className="notice is-ok" style={{ marginTop: 10 }}>You applied on {shortDate(applied.submitted_at)}. Status: {applied.status.replaceAll('_', ' ')}. <a {...linkTo('/dashboard?page=applications')}>Track it</a></div>
                : <form className="stack" style={{ marginTop: 12 }} onSubmit={(event) => void apply(event)}>
                  <div className="field">CV
                    {cvName === undefined ? <small>Checking your CV…</small>
                      : cvName ? <div className="cv-file" style={{ marginTop: 0 }}><span className="logo-box">CV</span><span style={{ flex: 1 }}>{cvName} <small className="muted">(from your profile)</small></span><a className="btn btn-sm" {...linkTo('/dashboard?page=profile')}>Change</a></div>
                        : <div className="notice is-info">You haven't uploaded a CV. Employers often look for one. <a {...linkTo('/dashboard?page=profile')}>Upload your CV</a></div>}
                  </div>
                  <label className="field">Cover note <small>Optional</small><textarea maxLength={2000} placeholder="Why are you interested in this role?" value={note} onChange={(event) => setNote(event.target.value)} /></label>
                  {applyError && <div className="notice is-error" role="alert">{applyError}</div>}
                  {verified === false && <div className="notice">Your university needs to verify your profile before you can apply.</div>}
                  <div><button className="btn btn-primary" disabled={busy || !canApply}>{busy ? 'Submitting…' : 'Submit application'}</button></div>
                </form>}
            </section>}
          </div>

          <aside className="detail-side">
            <section className="card">
              <div className="side-label">Closes {shortDate(listing.application_deadline)} · {plural(listing.days_left, 'day')} left</div>
              {isStudent ? (applied ? <a className="btn btn-block" {...linkTo('/dashboard?page=applications')}>View my application</a>
                : <a className="btn btn-primary btn-block" href="#apply" onClick={(event) => { event.preventDefault(); document.getElementById('apply')?.scrollIntoView({ behavior: 'smooth' }) }}>Apply now</a>)
                : session ? <div className="notice is-info">Only student accounts can apply.</div>
                  : <a className="btn btn-primary btn-block" {...linkTo(`/signin?next=${encodeURIComponent(`/internships/${listing.listing_id}`)}`)}>Sign in to apply</a>}
              <div className="side-actions" style={session && !isStudent ? { gridTemplateColumns: '1fr' } : undefined}>
                <SaveButton session={session} listingId={listing.listing_id} saved={listing.saved} />
                <button className="btn btn-sm" onClick={() => { void navigator.clipboard?.writeText(window.location.href) }}>Share link</button>
              </div>
              {isStudent && verified === false && <div className="notice">Your university hasn't verified you yet. You can apply once they do.</div>}
            </section>
            <section className="card">
              <div className="side-label">About the company</div>
              <a style={{ fontSize: 17, fontWeight: 700 }} {...linkTo(`/companies/${listing.company_id}`)}>{listing.company_name}</a>
              <p className="muted" style={{ fontSize: 14 }}>{listing.company_description || `${listing.sector} · ${listing.company_location}`}</p>
              {listing.company_website && <p style={{ fontSize: 14, margin: '0 0 6px' }}><a href={listing.company_website} target="_blank" rel="noreferrer noopener">Company website</a></p>}
              <a style={{ fontSize: 14 }} {...linkTo(`/companies/${listing.company_id}`)}>{listing.company_open_listings > 1 ? `See all ${listing.company_open_listings} internships from this company` : 'View company profile'}</a>
            </section>
            {listing.similar.length > 0 && <section className="card">
              <div className="side-label">Similar internships</div>
              <div className="stack" style={{ gap: 8 }}>{listing.similar.map((item) => <a key={item.listing_id} {...linkTo(`/internships/${item.listing_id}`)}><b>{item.title}</b></a>)}</div>
            </section>}
          </aside>
        </div>
      </div>
    </SiteLayout>
  )
}
