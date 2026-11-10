import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { companyApi, type CompanyPage as CompanyPageData, type CompanySummary } from './api'
import { CompanyLogo, messageOf, SaveButton, shortDate, SiteLayout, workplace, type SiteSession } from './PublicSite'
import { linkTo, navigate } from './router'
import './site.css'

/** "Suggest a company": students ask for a company that isn't on InternLink yet. */
export function SuggestCompany({ initialName = '', compact }: { initialName?: string; compact?: boolean }) {
  const [values, setValues] = useState({ company_name: initialName, website: '', requester_email: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState('')
  useEffect(() => setValues((current) => ({ ...current, company_name: initialName })), [initialName])
  const update = (name: keyof typeof values, value: string) => setValues((current) => ({ ...current, [name]: value }))

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      setDone((await companyApi.suggest({ ...values, website: values.website || undefined })).message)
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card" aria-label="Suggest a company" style={compact ? undefined : { marginTop: 18 }}>
      <h2>Can't find a company?</h2>
      <p className="muted" style={{ fontSize: 14, marginTop: 4 }}>Tell us who you'd like to intern with. We'll invite them to post internships on InternLink and email you when they join.</p>
      {done ? <div className="notice is-ok" role="status">{done}</div> : <form className="stack" onSubmit={(event) => void submit(event)}>
        <div className="field-pair">
          <label className="field">Company name<input value={values.company_name} onChange={(event) => update('company_name', event.target.value)} required maxLength={160} /></label>
          <label className="field">Website <small>Optional</small><input type="url" placeholder="https://" value={values.website} onChange={(event) => update('website', event.target.value)} /></label>
        </div>
        <label className="field">Your email<input type="email" value={values.requester_email} onChange={(event) => update('requester_email', event.target.value)} required /></label>
        {error && <div className="notice is-error" role="alert">{error}</div>}
        <div><button className="btn btn-primary" disabled={busy}>{busy ? 'Sending…' : 'Suggest this company'}</button></div>
      </form>}
    </section>
  )
}

export function CompaniesPage({ session, search }: { session: SiteSession; search: string }) {
  const params = useMemo(() => new URLSearchParams(search), [search])
  const [query, setQuery] = useState(params.get('q') ?? '')
  const [result, setResult] = useState<{ companies: CompanySummary[]; count: number; page: number; page_size: number; sectors: { name: string; count: number }[] } | null>(null)
  const [error, setError] = useState('')

  useEffect(() => { setQuery(params.get('q') ?? '') }, [params])
  useEffect(() => {
    let current = true
    setError('')
    companyApi.list(params)
      .then((data) => { if (current) setResult(data) })
      .catch((reason: unknown) => { if (current) setError(messageOf(reason)) })
    return () => { current = false }
  }, [params])

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    if (!('page' in changes)) next.delete('page')
    navigate(`/companies${next.toString() ? `?${next}` : ''}`, { replace: true })
  }

  const pages = result ? Math.max(1, Math.ceil(result.count / result.page_size)) : 1
  return (
    <SiteLayout session={session} active="companies" grey>
      <div className="site-container page-pad">
        <h1 className="page-title" style={{ marginBottom: 4 }}>Companies</h1>
        <p className="muted" style={{ margin: '0 0 18px' }}>Verified employers offering internships on InternLink.</p>
        <form className="search-row companies-search" role="search" onSubmit={(event) => { event.preventDefault(); update({ q: query.trim() || null }) }}>
          <label className="sr-only" htmlFor="company-q">Company name or sector</label>
          <input id="company-q" className="search-input" placeholder="Company name or sector" value={query} onChange={(event) => setQuery(event.target.value)} />
          <label className="sr-only" htmlFor="company-sector">Sector</label>
          <select id="company-sector" className="search-select" value={params.get('sector') ?? ''} onChange={(event) => update({ sector: event.target.value || null })}>
            <option value="">All sectors</option>
            {result?.sectors.map((item) => <option key={item.name} value={item.name}>{item.name} ({item.count})</option>)}
          </select>
          <button className="btn btn-primary">Search</button>
        </form>
        {error && <div className="notice is-error">{error}</div>}
        {!result && !error && <div className="card empty">Loading companies…</div>}
        {result && result.companies.length === 0 && <div className="card empty">No companies match{params.get('q') ? ` “${params.get('q')}”` : ''}.</div>}
        {result && result.companies.length > 0 && <div className="company-grid">
          {result.companies.map((company) => (
            <a key={company.company_id} className="company-card" {...linkTo(`/companies/${company.company_id}`)}>
              <CompanyLogo companyId={company.company_id} name={company.name} hasLogo={company.has_logo} large />
              <div style={{ minWidth: 0 }}>
                <b>{company.name}</b>
                <div className="muted" style={{ fontSize: 13 }}>{company.sector} · {company.location}</div>
                <div className={company.open_internships ? 'blue' : 'muted'} style={{ fontSize: 13, marginTop: 6 }}>
                  {company.open_internships ? `${company.open_internships} open internship${company.open_internships === 1 ? '' : 's'}` : 'No openings right now'}
                </div>
              </div>
            </a>
          ))}
        </div>}
        {pages > 1 && <nav className="pager" aria-label="Pages">
          <button className="btn btn-sm" disabled={(result?.page ?? 1) <= 1} onClick={() => update({ page: String((result?.page ?? 1) - 1) })}>Previous</button>
          <button className="btn btn-sm" disabled={(result?.page ?? 1) >= pages} onClick={() => update({ page: String((result?.page ?? 1) + 1) })}>Next</button>
        </nav>}
        <SuggestCompany initialName={result?.companies.length === 0 ? params.get('q') ?? '' : ''} />
      </div>
    </SiteLayout>
  )
}

export function CompanyPage({ session, id }: { session: SiteSession; id: number }) {
  const [company, setCompany] = useState<CompanyPageData | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    setCompany(null)
    companyApi.page(id).then((data) => setCompany(data.company)).catch((reason: unknown) => setError(messageOf(reason)))
  }, [id])

  if (error) return <SiteLayout session={session} grey><div className="site-container page-pad"><div className="card"><h2>Company not found</h2><p className="muted">{error}</p><a className="btn" {...linkTo('/companies')}>Browse companies</a></div></div></SiteLayout>
  if (!company) return <SiteLayout session={session} grey><div className="site-container page-pad empty">Loading…</div></SiteLayout>
  return (
    <SiteLayout session={session} active="companies" grey>
      <div className="site-container page-pad">
        <div className="crumbs"><a {...linkTo('/companies')}>Companies</a> / {company.name}</div>
        <section className="card applicant-head">
          <CompanyLogo companyId={company.company_id} name={company.name} hasLogo={company.has_logo} large />
          <div style={{ flex: 1 }}>
            <h1 style={{ fontSize: 30 }}>{company.name}</h1>
            <div style={{ color: 'var(--s-text)' }}>{company.sector} · {company.location}</div>
            <div style={{ color: 'var(--s-green)', fontSize: 14, fontWeight: 600 }}>Verified employer</div>
          </div>
          {company.website && <a className="btn" href={company.website} target="_blank" rel="noreferrer noopener">Website</a>}
        </section>
        <div className="detail-grid" style={{ marginTop: 16 }}>
          <div className="detail-main">
            <section className="card">
              <h2>About</h2>
              <p className="prose" style={{ marginBottom: 0 }}>{company.description?.trim() || <span className="muted">This company hasn't added a description yet.</span>}</p>
            </section>
            <section>
              <h2 style={{ fontSize: 22, margin: '6px 0 12px' }}>Open internships ({company.open_internships.length})</h2>
              {company.open_internships.length === 0 && <div className="card empty">No open internships right now. Check back soon, or set up a <a {...linkTo('/internships')}>job alert</a>.</div>}
              {company.open_internships.map((item) => (
                <article key={item.listing_id} className="result-card" style={{ gridTemplateColumns: '1fr auto' }}>
                  <div>
                    <a className="listing-title" {...linkTo(`/internships/${item.listing_id}`)}>{item.title}</a>
                    <div className="listing-meta" style={{ margin: '4px 0 8px' }}>{workplace(item)} · {item.duration_weeks} weeks · {item.slots_remaining} position{item.slots_remaining === 1 ? '' : 's'}</div>
                    <div className="chip-row">{item.required_skills.map((skill) => <span key={skill} className="chip">{skill}</span>)}</div>
                  </div>
                  <div className="result-side"><span>Closes {shortDate(item.application_deadline)}</span><SaveButton session={session} listingId={item.listing_id} /></div>
                </article>
              ))}
            </section>
          </div>
          <aside className="detail-side">
            <section className="card">
              <div className="side-label">On InternLink</div>
              <div className="fact-grid" style={{ margin: 0 }}>
                <div><span>OPEN NOW</span>{company.open_internships.length}</div>
                <div><span>PAST</span>{company.past_internships}</div>
                <div><span>INTERNS PLACED</span>{company.interns_placed}</div>
              </div>
            </section>
          </aside>
        </div>
      </div>
    </SiteLayout>
  )
}
