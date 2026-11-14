import { useEffect, useMemo, useState, type DragEvent, type FormEvent, type ReactNode } from 'react'
import {
  adminApi, companyRequestApi, coordinatorTeamApi, employerDownload, employerLogoApi, employerRequest, MAX_LOGO_BYTES, roleApi, studentApi,
  type CatalogItem, type CompanyRequest, type CoordinatorRow, type RegistrationDetail, type UniversityRequest, type VerifiedUniversity,
} from './api'
import { initialsOf, messageOf, shortDate, Wordmark } from './PublicSite'
import './site.css'

type Row = Record<string, unknown>

/* ------------------------------------------------------------------ shell */

export type OrgNavItem<P extends string> = { page: P; label: string; count?: number }

export function OrgShell<P extends string>({ suffix, nav, page, onPage, name, onSignOut, action, children }: {
  suffix: string; nav: OrgNavItem<P>[]; page: P; onPage: (page: P) => void; name: string; onSignOut: () => void
  action?: ReactNode; children: ReactNode
}) {
  const [menu, setMenu] = useState(false)
  return (
    <div className="site is-grey">
      <header className="site-header">
        <div className="site-container site-header-inner" style={{ maxWidth: 'none' }}>
          <Wordmark suffix={suffix} to="/dashboard" />
          <div className="site-header-actions" style={{ position: 'relative' }}>
            {action && <span className="hide-sm">{action}</span>}
            <button className="btn btn-sm" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu((value) => !value)}>{name} ▾</button>
            {menu && <div role="menu" className="card" style={{ position: 'absolute', right: 0, top: 44, padding: 12, minWidth: 200, zIndex: 40 }}>
              <button role="menuitem" className="btn btn-sm btn-block" onClick={() => { setMenu(false); onSignOut() }}>Sign out</button>
            </div>}
          </div>
        </div>
      </header>
      <div className="student-shell">
        <nav className="student-side" aria-label="Sections">
          {nav.map((item) => (
            <button key={item.page} className={page === item.page ? 'is-active' : ''} aria-current={page === item.page ? 'page' : undefined} onClick={() => onPage(item.page)}>
              <span>{item.label}</span>{!!item.count && <span className="chip">{item.count}</span>}
            </button>
          ))}
        </nav>
        <main className="student-main">{children}</main>
      </div>
    </div>
  )
}

function Stat({ label, value, warn }: { label: string; value: ReactNode; warn?: boolean }) {
  return <div className="stat-card"><span>{label}</span><b className={warn ? 'is-warn' : ''}>{value}</b></div>
}

function downloadCsv(filename: string, rows: Row[], columns: string[]) {
  const escape = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`
  const csv = [columns.join(','), ...rows.map((row) => columns.map((column) => escape(row[column])).join(','))].join('\n')
  const link = document.createElement('a')
  link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
  link.download = filename
  link.click()
  URL.revokeObjectURL(link.href)
}

function daysSince(value: unknown) {
  const time = new Date(String(value ?? '')).getTime()
  if (Number.isNaN(time)) return '—'
  const days = Math.floor((Date.now() - time) / 86_400_000)
  return days <= 0 ? 'today' : days === 1 ? '1 day' : `${days} days`
}

/* ---------------------------------------------------------- employer: board */

const DECLINE_REASONS = [
  'Another candidate was a closer fit for this role.',
  'We need more experience with the required skills.',
  'All positions for this internship have been filled.',
  'The timing does not work for this placement.',
]

type Decision =
  | { kind: 'interview'; applicationId: number; name: string }
  | { kind: 'decline'; applicationId: number; name: string }
  | { kind: 'offer'; applicationId: number; name: string }

/** Small dialog for the decisions that need more than a click. */
function DecisionDialog({ decision, onCancel, onConfirm }: {
  decision: Decision; onCancel: () => void; onConfirm: (extra: Record<string, string>) => Promise<void>
}) {
  const [when, setWhen] = useState('')
  const [note, setNote] = useState('')
  const [reason, setReason] = useState(DECLINE_REASONS[0])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const minimum = useMemo(() => {
    const date = new Date(Date.now() + 60 * 60 * 1000)
    date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
    return date.toISOString().slice(0, 16)
  }, [])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      if (decision.kind === 'interview') await onConfirm({ interview_at: new Date(when).toISOString(), interview_note: note })
      else if (decision.kind === 'decline') await onConfirm({ reason })
      else await onConfirm({})
    } catch (reason) {
      setError(messageOf(reason))
      setBusy(false)
    }
  }

  const title = decision.kind === 'interview' ? `Invite ${decision.name} to interview` : decision.kind === 'decline' ? `Decline ${decision.name}` : `Make an offer to ${decision.name}`
  return (
    <div className="dialog-backdrop" role="presentation" onClick={onCancel}>
      <form className="card dialog" role="dialog" aria-modal="true" aria-label={title} onClick={(event) => event.stopPropagation()} onSubmit={(event) => void submit(event)}>
        <h2>{title}</h2>
        {decision.kind === 'interview' && <div className="stack" style={{ marginTop: 12 }}>
          <label className="field">Date and time<input type="datetime-local" min={minimum} value={when} onChange={(event) => setWhen(event.target.value)} required autoFocus /></label>
          <label className="field">Where, or how to join <small>Optional. Shared with the student.</small><input maxLength={500} placeholder="e.g. Our Kampala office, Plot 12 Lumumba Ave" value={note} onChange={(event) => setNote(event.target.value)} /></label>
        </div>}
        {decision.kind === 'decline' && <label className="field" style={{ marginTop: 12 }}>Reason (shared kindly with the student)
          <select value={reason} onChange={(event) => setReason(event.target.value)}>{DECLINE_REASONS.map((item) => <option key={item}>{item}</option>)}</select>
        </label>}
        {decision.kind === 'offer' && <p className="muted" style={{ fontSize: 14 }}>The student's university coordinator then approves the placement. This uses one of the listing's positions.</p>}
        {error && <div className="notice is-error" role="alert" style={{ marginTop: 12 }}>{error}</div>}
        <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
          <button className={`btn ${decision.kind === 'decline' ? 'btn-danger' : 'btn-primary'}`} disabled={busy}>{busy ? 'Saving…' : decision.kind === 'interview' ? 'Send invitation' : decision.kind === 'decline' ? 'Decline application' : 'Make offer'}</button>
          <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        </div>
      </form>
    </div>
  )
}

const COLUMNS: { key: string; title: string; statuses: string[] }[] = [
  { key: 'new', title: 'New', statuses: ['submitted', 'under_review'] },
  { key: 'shortlisted', title: 'Shortlisted', statuses: ['shortlisted'] },
  { key: 'interview', title: 'Interview', statuses: ['interview'] },
  { key: 'accepted', title: 'Offer sent', statuses: ['accepted'] },
  { key: 'rejected', title: 'Declined', statuses: ['rejected'] },
]

async function loadAllApplicants(token: string, listingId: number) {
  const rows: Row[] = []
  for (let page = 1; page <= 10; page += 1) {
    const result = await employerRequest<{ applicants: Row[] }>('applicants', token, { listing_id: listingId, page })
    rows.push(...result.applicants)
    if (result.applicants.length < 20) break
  }
  return rows
}

export function EmployerBoard({ token, listings, listingId, onListing, onOpen, toast }: {
  token: string; listings: Row[]; listingId: number | null; onListing: (id: number) => void
  onOpen: (applicationId: number, order: number[]) => void; toast: (message: string) => void
}) {
  const [rows, setRows] = useState<Row[] | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [verifiedOnly, setVerifiedOnly] = useState(false)
  const [strong, setStrong] = useState(false)
  const [view, setView] = useState<'board' | 'list'>('board')
  const [decision, setDecision] = useState<Decision | null>(null)
  const [dragOver, setDragOver] = useState('')
  const listing = listings.find((item) => Number(item.listing_id) === listingId)

  function load() {
    if (!listingId) return
    setError('')
    loadAllApplicants(token, listingId).then(setRows).catch((reason: unknown) => setError(messageOf(reason)))
  }
  useEffect(() => { setRows(null); load() }, [listingId, token])

  const shown = (rows ?? []).filter((row) => {
    const text = `${row.applicant_name} ${row.programme} ${row.university}`.toLowerCase()
    return (!query.trim() || text.includes(query.trim().toLowerCase()))
      && (!verifiedOnly || row.student_verified)
      && (!strong || Number(row.match_score ?? 0) > 60)
  })
  const weekAgo = Date.now() - 7 * 86_400_000
  const newThisWeek = (rows ?? []).filter((row) => new Date(String(row.submitted_at)).getTime() >= weekAgo).length

  async function decide(applicationId: number, action: string, extra: Record<string, string> = {}) {
    await employerRequest('decide', token, { application_id: applicationId, action, ...extra })
    setDecision(null)
    load()
    toast(action === 'shortlist' ? 'Moved to shortlisted.' : action === 'interview' ? 'Interview invitation sent.' : action === 'accept' ? 'Offer made. The university will approve the placement.' : 'Application declined.')
  }

  function drop(event: DragEvent, column: string) {
    event.preventDefault()
    setDragOver('')
    const applicationId = Number(event.dataTransfer.getData('text/plain'))
    const row = rows?.find((item) => Number(item.application_id) === applicationId)
    if (!row) return
    const name = String(row.applicant_name)
    if (COLUMNS.find((item) => item.key === column)?.statuses.includes(String(row.status))) return
    if (column === 'shortlisted') void decide(applicationId, 'shortlist').catch((reason: unknown) => toast(messageOf(reason)))
    else if (column === 'interview') setDecision({ kind: 'interview', applicationId, name })
    else if (column === 'accepted') setDecision({ kind: 'offer', applicationId, name })
    else if (column === 'rejected') setDecision({ kind: 'decline', applicationId, name })
    else toast('Applications can’t move back to New.')
  }

  const order = shown.map((row) => Number(row.application_id))
  return (
    <>
      <div className="apps-head" style={{ alignItems: 'flex-end' }}>
        <label className="field" style={{ fontSize: 12, letterSpacing: '.08em', color: 'var(--s-muted)' }}>APPLICANTS FOR
          <select className="board-listing" value={listingId ?? ''} onChange={(event) => onListing(Number(event.target.value))}>
            {!listingId && <option value="">Choose an internship</option>}
            {listings.map((item) => <option key={String(item.listing_id)} value={String(item.listing_id)}>{String(item.title)} ({String(item.status)})</option>)}
          </select>
        </label>
        <div className="tabs">
          <button className={`btn btn-sm ${view === 'board' ? 'is-current' : ''}`} aria-pressed={view === 'board'} onClick={() => setView('board')}>Board</button>
          <button className={`btn btn-sm ${view === 'list' ? 'is-current' : ''}`} aria-pressed={view === 'list'} onClick={() => setView('list')}>List</button>
          <button className="btn btn-sm" disabled={!rows?.length} onClick={() => downloadCsv(`applicants-${listingId}.csv`, shown, ['applicant_name', 'programme', 'year_of_study', 'university', 'match_score', 'status', 'submitted_at'])}>Export CSV</button>
        </div>
      </div>
      {listings.length === 0 && <div className="card empty">Post an internship to start receiving applicants.</div>}
      {listing && <>
        <div className="stat-grid">
          <Stat label="NEW THIS WEEK" value={rows ? newThisWeek : '…'} />
          <Stat label="POSITIONS FILLED" value={`${Number(listing.slots_filled ?? 0)} / ${Number(listing.slots ?? 0)}`} />
          <Stat label="CLOSES" value={shortDate(String(listing.application_deadline ?? ''))} />
          <Stat label="APPLICANTS" value={rows ? rows.length : '…'} />
        </div>
        <div className="board-filters">
          <label className="sr-only" htmlFor="board-search">Search by name, programme or university</label>
          <input id="board-search" className="search-input" placeholder="Search by name, programme or university" value={query} onChange={(event) => setQuery(event.target.value)} />
          <label className="check-line"><input type="checkbox" checked={verifiedOnly} onChange={(event) => setVerifiedOnly(event.target.checked)} /> Verified students only</label>
          <label className="check-line"><input type="checkbox" checked={strong} onChange={(event) => setStrong(event.target.checked)} /> Match above 60%</label>
        </div>
        {error && <div className="notice is-error">{error}</div>}
        {!rows && !error && <div className="card empty">Loading applicants…</div>}
        {rows && view === 'board' && <>
          <div className="board" role="list">
            {COLUMNS.map((column) => {
              const cards = shown.filter((row) => column.statuses.includes(String(row.status)))
              return (
                <section key={column.key} className={`board-column ${dragOver === column.key ? 'is-over' : ''}`} aria-label={column.title}
                  onDragOver={(event) => { event.preventDefault(); setDragOver(column.key) }} onDragLeave={() => setDragOver('')} onDrop={(event) => drop(event, column.key)}>
                  <h3>{column.title}<span>{cards.length}</span></h3>
                  {cards.map((row) => (
                    <button key={String(row.application_id)} className="board-card" draggable
                      onDragStart={(event) => event.dataTransfer.setData('text/plain', String(row.application_id))}
                      onClick={() => onOpen(Number(row.application_id), order)}>
                      <b>{String(row.applicant_name)}</b>
                      <small>{String(row.programme)} · Yr {String(row.year_of_study)}</small>
                      {row.status === 'interview' && row.interview_at ? <small className="blue">{new Date(String(row.interview_at)).toLocaleString('en-UG', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</small>
                        : row.status === 'accepted' ? <small>Waiting for university approval</small>
                          : <small><span className="blue">{Math.round(Number(row.match_score ?? 0))}%</span> match · {row.student_verified ? 'Verified' : <span className="amber">Pending</span>}</small>}
                    </button>
                  ))}
                </section>
              )
            })}
          </div>
          <p className="muted" style={{ fontSize: 13 }}>Drag a card to move it to the next stage, or open it for full details.</p>
        </>}
        {rows && view === 'list' && <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
          <table className="s-table">
            <thead><tr><th>Applicant</th><th>Programme</th><th>Match</th><th>Status</th><th>Applied</th><th /></tr></thead>
            <tbody>{shown.map((row) => (
              <tr key={String(row.application_id)}>
                <td><b>{String(row.applicant_name)}</b><div className="muted">{String(row.university)}</div></td>
                <td>{String(row.programme)} · Yr {String(row.year_of_study)}</td>
                <td>{Math.round(Number(row.match_score ?? 0))}%</td>
                <td><span className="status-pill">{String(row.status).replaceAll('_', ' ')}</span></td>
                <td>{shortDate(String(row.submitted_at))}</td>
                <td><button className="btn btn-sm" onClick={() => onOpen(Number(row.application_id), order)}>Open</button></td>
              </tr>
            ))}</tbody>
          </table>
          {shown.length === 0 && <div className="empty">No applicants match these filters.</div>}
        </div>}
      </>}
      {decision && <DecisionDialog decision={decision} onCancel={() => setDecision(null)}
        onConfirm={(extra) => decide(decision.applicationId, decision.kind === 'interview' ? 'interview' : decision.kind === 'offer' ? 'accept' : 'reject', extra)} />}
    </>
  )
}

/* --------------------------------------------------- employer: applicant */

type ApplicantDetail = {
  profile: { full_name: string; programme: string; year_of_study: number; university: string; preferred_location: string | null; skills: { name: string }[]; interests: { name: string }[] }
  application_id: number; listing_title: string; submitted_at: string; cover_note: string | null; match_score: number | null
  status: string; has_cv: boolean; interview_at: string | null; interview_note: string | null
  listing_skills: { name: string; required: boolean; has: boolean }[]; can_message: boolean
}

const STAGE_LABEL: Record<string, string> = { submitted: 'New', under_review: 'New', shortlisted: 'Shortlisted', interview: 'Interview', accepted: 'Offer sent', rejected: 'Declined' }

export function EmployerApplicant({ token, applicationId, order, onOpen, onBack, onMessage, toast }: {
  token: string; applicationId: number; order: number[]; onOpen: (id: number) => void; onBack: () => void
  onMessage: (row: Row) => void; toast: (message: string) => void
}) {
  const [detail, setDetail] = useState<ApplicantDetail | null>(null)
  const [error, setError] = useState('')
  const [decision, setDecision] = useState<Decision | null>(null)
  const [reason, setReason] = useState(DECLINE_REASONS[0])
  const [busy, setBusy] = useState(false)
  const index = order.indexOf(applicationId)

  function load() {
    setError('')
    employerRequest<ApplicantDetail>('view_applicant', token, { application_id: applicationId }).then(setDetail).catch((reason: unknown) => setError(messageOf(reason)))
  }
  useEffect(() => { setDetail(null); load() }, [applicationId, token])

  async function decide(action: string, extra: Record<string, string> = {}) {
    await employerRequest('decide', token, { application_id: applicationId, action, ...extra })
    setDecision(null)
    load()
    toast('Application updated.')
  }

  async function downloadCv() {
    try {
      // The employer API sends the file itself, not JSON.
      const file = await employerDownload('download_cv', token, { application_id: applicationId })
      const bytes = new Uint8Array(await file.slice(0, 4).arrayBuffer())
      const isPdf = bytes[0] === 0x25 && bytes[1] === 0x50
      const link = document.createElement('a')
      link.href = URL.createObjectURL(new Blob([file], { type: isPdf ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }))
      link.download = `${detail?.profile.full_name ?? 'applicant'} CV.${isPdf ? 'pdf' : 'docx'}`
      link.click()
      URL.revokeObjectURL(link.href)
    } catch (reason) {
      toast(messageOf(reason))
    }
  }

  const name = detail?.profile.full_name ?? 'Applicant'
  const status = detail?.status ?? ''
  const open = !['accepted', 'rejected'].includes(status)
  return (
    <>
      <div className="apps-head">
        <button className="btn-link" onClick={onBack}>Back to applicants</button>
        <div className="tabs">
          <button className="btn btn-sm" disabled={index <= 0} onClick={() => onOpen(order[index - 1])}>Previous applicant</button>
          <button className="btn btn-sm" disabled={index < 0 || index >= order.length - 1} onClick={() => onOpen(order[index + 1])}>Next applicant</button>
        </div>
      </div>
      {error && <div className="notice is-error">{error}</div>}
      {!detail && !error && <div className="card empty">Loading…</div>}
      {detail && <>
        <section className="card applicant-head">
          <span className="site-avatar" style={{ width: 64, height: 64, fontSize: 20 }}>{initialsOf(name)}</span>
          <div style={{ flex: 1 }}>
            <h1 style={{ fontSize: 30 }}>{name}</h1>
            <div style={{ color: 'var(--s-text)' }}>{detail.profile.programme} · Year {detail.profile.year_of_study} · {detail.profile.university}</div>
            <div style={{ color: 'var(--s-green)', fontSize: 14 }}>Applied {shortDate(detail.submitted_at)} for {detail.listing_title}</div>
          </div>
          {detail.match_score != null && <div style={{ textAlign: 'right' }}><div className="score" style={{ fontSize: 34 }}>{Math.round(detail.match_score)}%</div><div className="side-label" style={{ margin: 0 }}>Match</div></div>}
        </section>
        <div className="detail-grid" style={{ marginTop: 16 }}>
          <div className="detail-main">
            <section className="card">
              <h2>Skills against your listing</h2>
              <div className="chip-row" style={{ marginTop: 10 }}>
                {detail.listing_skills.length === 0 && <span className="muted">This listing has no skills tagged.</span>}
                {detail.listing_skills.map((skill) => <span key={skill.name} className={`chip ${skill.has ? 'chip-green' : 'chip-amber'}`}>{skill.name}{skill.has ? '' : ' (missing)'}{skill.required ? '' : ' · nice to have'}</span>)}
              </div>
              {detail.profile.skills.length > 0 && <p className="muted" style={{ fontSize: 13, marginBottom: 0 }}>All skills: {detail.profile.skills.map((skill) => skill.name).join(', ')}</p>}
            </section>
            <section className="card">
              <h2>Cover note</h2>
              <p className="prose" style={{ marginBottom: 0 }}>{detail.cover_note?.trim() || <span className="muted">No cover note.</span>}</p>
            </section>
            <section className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}><h2>CV</h2>{detail.has_cv && <button className="btn btn-sm" onClick={() => void downloadCv()}>Download CV</button>}</div>
              {!detail.has_cv && <p className="muted" style={{ marginBottom: 0 }}>This student hasn't uploaded a CV yet.</p>}
            </section>
          </div>
          <aside className="detail-side">
            <section className="card">
              <div className="side-label">Stage: {STAGE_LABEL[status] ?? status}</div>
              {status === 'interview' && detail.interview_at && <div className="notice is-info" style={{ marginBottom: 10 }}>Interview {new Date(detail.interview_at).toLocaleString('en-UG', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}{detail.interview_note ? ` · ${detail.interview_note}` : ''}</div>}
              <div className="stack" style={{ gap: 8 }}>
                {['submitted', 'under_review'].includes(status) && <button className="btn btn-primary" disabled={busy} onClick={() => { setBusy(true); void decide('shortlist').catch((reason: unknown) => toast(messageOf(reason))).finally(() => setBusy(false)) }}>Shortlist</button>}
                {status === 'shortlisted' && <button className="btn btn-primary" onClick={() => setDecision({ kind: 'interview', applicationId, name })}>Invite to interview</button>}
                {['shortlisted', 'interview'].includes(status) && <button className={`btn ${status === 'interview' ? 'btn-primary' : ''}`} onClick={() => setDecision({ kind: 'offer', applicationId, name })}>Make an offer</button>}
                {detail.can_message && <button className="btn" onClick={() => onMessage({ application_id: applicationId, applicant_name: name, listing_title: detail.listing_title, application_status: status })}>Message applicant</button>}
                {status === 'accepted' && <p className="muted" style={{ fontSize: 14, margin: 0 }}>Offer made. The student's university approves the placement.</p>}
                {status === 'rejected' && <p className="muted" style={{ fontSize: 14, margin: 0 }}>This application was declined.</p>}
              </div>
            </section>
            {open && <section className="card">
              <div className="side-label">Not a fit?</div>
              <label className="field">Reason (shared kindly with the student)
                <select value={reason} onChange={(event) => setReason(event.target.value)}>{DECLINE_REASONS.map((item) => <option key={item}>{item}</option>)}</select>
              </label>
              <button className="btn btn-danger btn-block" style={{ marginTop: 10 }} disabled={busy} onClick={() => { if (window.confirm(`Decline ${name}'s application?`)) { setBusy(true); void decide('reject', { reason }).catch((error: unknown) => toast(messageOf(error))).finally(() => setBusy(false)) } }}>Decline application</button>
            </section>}
          </aside>
        </div>
      </>}
      {decision && <DecisionDialog decision={decision} onCancel={() => setDecision(null)}
        onConfirm={(extra) => decide(decision.kind === 'interview' ? 'interview' : decision.kind === 'offer' ? 'accept' : 'reject', extra)} />}
    </>
  )
}

export function PlacedInterns({ token }: { token: string }) {
  const [rows, setRows] = useState<Row[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    employerRequest<Row[]>('my_placements', token).then(setRows).catch((reason: unknown) => setError(messageOf(reason)))
  }, [token])
  return (
    <>
      <h1>Placed interns</h1>
      <p className="muted" style={{ margin: '4px 0 18px' }}>Students you made offers to, and where their university approval stands.</p>
      {error && <div className="notice is-error">{error}</div>}
      {!rows && !error && <div className="card empty">Loading…</div>}
      {rows && (rows.length === 0 ? <div className="card empty">No placements yet. Offers you make appear here.</div>
        : <div className="card" style={{ padding: 0, overflowX: 'auto' }}><table className="s-table">
          <thead><tr><th>Student</th><th>Internship</th><th>Status</th><th>Dates</th></tr></thead>
          <tbody>{rows.map((row) => (
            <tr key={String(row.placement_id)}>
              <td><b>{String(row.student_name ?? row.full_name ?? '')}</b><div className="muted">{String(row.programme ?? '')}</div></td>
              <td>{String(row.listing_title ?? row.title ?? '')}</td>
              <td><span className={`status-pill ${row.status === 'confirmed' ? 'is-green' : row.status === 'pending' ? '' : 'is-blue'}`}>{row.status === 'pending' ? 'Awaiting university' : String(row.status)}</span></td>
              <td>{row.start_date ? `${shortDate(String(row.start_date))} – ${shortDate(String(row.end_date ?? ''))}` : '—'}</td>
            </tr>
          ))}</tbody>
        </table></div>)}
    </>
  )
}

/* ---------------------------------------------------------- coordinator */

export type CoordinatorData = { stats: Row | null; students: Row[]; placements: Row[] }

function VerifyTable({ token, students, onDone, toast, limit }: { token: string; students: Row[]; onDone: () => void; toast: (message: string) => void; limit?: number }) {
  const waiting = students.filter((row) => !row.verified)
  const [selected, setSelected] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const shown = limit ? waiting.slice(0, limit) : waiting

  async function verify(ids: number[]) {
    setBusy(true)
    let done = 0
    for (const id of ids) {
      try {
        await roleApi.verifyStudent(token, id)
        done += 1
      } catch (reason) {
        toast(messageOf(reason))
      }
    }
    setBusy(false)
    setSelected([])
    if (done) toast(`${done} student${done === 1 ? '' : 's'} verified.`)
    onDone()
  }

  const allChecked = shown.length > 0 && shown.every((row) => selected.includes(Number(row.student_id)))
  return (
    <section className="card" style={{ padding: 0 }}>
      <div className="card-head">
        <div><h2>Students waiting for verification</h2><p className="muted" style={{ margin: 0, fontSize: 14 }}>Check each student's details against your records, then verify them so they can apply.</p></div>
        <button className="btn btn-primary btn-sm" disabled={!selected.length || busy} onClick={() => void verify(selected)}>Verify selected ({selected.length})</button>
      </div>
      {waiting.length === 0 ? <div className="empty">Everyone is verified. New sign-ups will appear here.</div>
        : <div style={{ overflowX: 'auto' }}><table className="s-table">
          <thead><tr>
            <th><input type="checkbox" aria-label="Select all" checked={allChecked} onChange={(event) => setSelected(event.target.checked ? shown.map((row) => Number(row.student_id)) : [])} /></th>
            <th>Name</th><th>Student no.</th><th>Programme</th><th>Email</th><th>Waiting</th><th>Action</th>
          </tr></thead>
          <tbody>{shown.map((row) => {
            const id = Number(row.student_id)
            return (
              <tr key={id}>
                <td><input type="checkbox" aria-label={`Select ${String(row.full_name)}`} checked={selected.includes(id)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, id] : current.filter((item) => item !== id))} /></td>
                <td>{String(row.full_name)}</td><td>{String(row.student_number ?? '—')}</td><td>{String(row.programme)}</td><td>{String(row.email ?? '')}</td>
                <td>{daysSince(row.registered_at)}</td>
                <td><button className="btn btn-sm" disabled={busy} onClick={() => void verify([id])}>Verify</button></td>
              </tr>
            )
          })}</tbody>
        </table></div>}
      {limit && waiting.length > limit && <p className="muted" style={{ padding: '0 16px 14px', fontSize: 13 }}>Showing {limit} of {waiting.length}. Open “Verify students” to see all.</p>}
    </section>
  )
}

function PlacementApprovals({ token, placements, onDone, toast }: { token: string; placements: Row[]; onDone: () => void; toast: (message: string) => void }) {
  const [notes, setNotes] = useState<Record<number, string>>({})
  const today = new Date().toISOString().slice(0, 10)
  const [starts, setStarts] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState(0)

  async function decide(id: number, action: 'confirmed' | 'rejected') {
    const note = (notes[id] ?? '').trim()
    if (action === 'rejected' && !note) {
      toast('Add a note to the student explaining why.')
      return
    }
    setBusy(id)
    try {
      await roleApi.decidePlacement(token, id, action, action === 'rejected' ? note : undefined, starts[id] || today)
      toast(action === 'confirmed' ? 'Placement approved.' : 'Placement rejected.')
      onDone()
    } catch (reason) {
      toast(messageOf(reason))
    } finally {
      setBusy(0)
    }
  }

  return (
    <section className="card">
      <h2>Placement approvals</h2>
      {placements.length === 0 && <p className="muted" style={{ marginBottom: 0 }}>No placements are waiting for you.</p>}
      <div className="stack" style={{ marginTop: 12 }}>
        {placements.map((row) => {
          const id = Number(row.placement_id)
          return (
            <div key={id} className="approval">
              <b>{String(row.student_name)} → {String(row.listing_title)}</b>
              <div className="muted" style={{ fontSize: 14 }}>{String(row.company_name)} · {row.is_remote ? 'Remote' : String(row.location ?? '')}{row.duration_weeks ? ` · ${String(row.duration_weeks)} weeks` : ''} · offered {shortDate(String(row.queued_at))}</div>
              <label className="field" style={{ marginTop: 8 }}>Start date <small>The end date follows from the internship's length.</small><input type="date" value={starts[id] ?? today} onChange={(event) => setStarts((current) => ({ ...current, [id]: event.target.value }))} /></label>
              <label className="field" style={{ marginTop: 8 }}>Note to student (required if rejecting)<textarea rows={2} maxLength={500} value={notes[id] ?? ''} onChange={(event) => setNotes((current) => ({ ...current, [id]: event.target.value }))} /></label>
              <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                <button className="btn btn-primary btn-sm" disabled={busy === id} onClick={() => void decide(id, 'confirmed')}>Approve</button>
                <button className="btn btn-danger btn-sm" disabled={busy === id} onClick={() => void decide(id, 'rejected')}>Reject</button>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

const PLACEMENT_PARTS = [
  { key: 'placed', label: 'Placed', color: '#174baa' },
  { key: 'pending', label: 'Awaiting approval', color: '#7ea2e8' },
  { key: 'unplaced', label: 'Not placed', color: '#dcdcd7' },
] as const

/** 100% stacked bar per programme: share of students placed, awaiting approval and not placed. */
function PlacementChart({ students }: { students: Row[] }) {
  const byProgramme = useMemo(() => {
    const groups = new Map<string, Record<'placed' | 'pending' | 'unplaced', number>>()
    for (const row of students) {
      const key = String(row.programme)
      const group = groups.get(key) ?? { placed: 0, pending: 0, unplaced: 0 }
      const state = String(row.placement_status) as 'placed' | 'pending' | 'unplaced'
      group[state in group ? state : 'unplaced'] += 1
      groups.set(key, group)
    }
    return [...groups.entries()].map(([programme, counts]) => ({ programme, ...counts, total: counts.placed + counts.pending + counts.unplaced }))
      .sort((a, b) => b.placed / b.total - a.placed / a.total || b.total - a.total)
  }, [students])
  const [hover, setHover] = useState('')

  if (byProgramme.length === 0) return <p className="muted">No students registered yet.</p>
  return (
    <figure className="pchart" style={{ margin: 0 }}>
      <div className="pchart-legend" aria-hidden="true">{PLACEMENT_PARTS.map((part) => <span key={part.key}><i style={{ background: part.color }} />{part.label}</span>)}</div>
      {byProgramme.map((row) => (
        <div key={row.programme} className="pchart-row">
          <div className="pchart-label"><span>{row.programme}</span><b>{Math.round((row.placed / row.total) * 100)}% placed</b></div>
          <div className="pchart-bar" aria-hidden="true">
            {PLACEMENT_PARTS.filter((part) => row[part.key] > 0).map((part) => {
              const id = `${row.programme}-${part.key}`
              return <span key={part.key} className={hover === id ? 'is-hover' : ''} style={{ flexGrow: row[part.key], background: part.color }}
                onMouseEnter={() => setHover(id)} onMouseLeave={() => setHover('')}>
                {hover === id && <em role="tooltip">{part.label}: {row[part.key]} of {row.total}</em>}
              </span>
            })}
          </div>
        </div>
      ))}
      <div className="sr-only"><table>
        <caption>Placement by programme</caption>
        <thead><tr><th>Programme</th><th>Placed</th><th>Awaiting approval</th><th>Not placed</th></tr></thead>
        <tbody>{byProgramme.map((row) => <tr key={row.programme}><td>{row.programme}</td><td>{row.placed}</td><td>{row.pending}</td><td>{row.unplaced}</td></tr>)}</tbody>
      </table></div>
    </figure>
  )
}

export function CoordinatorOverview({ token, data, onReload, toast, onPage }: {
  token: string; data: CoordinatorData; onReload: () => void; toast: (message: string) => void; onPage: (page: 'verify') => void
}) {
  const waiting = data.students.filter((row) => !row.verified).length
  const notApplied = data.students.filter((row) => Number(row.applications_count ?? 0) === 0).length
  return (
    <>
      <h1>Overview</h1>
      <div className="stat-grid" style={{ marginTop: 16 }}>
        <Stat label="REGISTERED STUDENTS" value={data.students.length} />
        <Stat label="PLACED" value={Number(data.stats?.placed ?? 0)} />
        <Stat label="AWAITING YOUR ACTION" value={waiting + data.placements.length} warn={waiting + data.placements.length > 0} />
        <Stat label="NOT YET APPLIED" value={notApplied} />
      </div>
      <VerifyTable token={token} students={data.students} onDone={onReload} toast={toast} limit={5} />
      {waiting > 5 && <button className="btn-link" style={{ marginTop: 6 }} onClick={() => onPage('verify')}>See all {waiting} students waiting</button>}
      <div className="apps-grid" style={{ marginTop: 18 }}>
        <PlacementApprovals token={token} placements={data.placements.slice(0, 3)} onDone={onReload} toast={toast} />
        <section className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <h2>Placement rate by programme</h2>
            <button className="btn btn-sm" onClick={() => downloadCsv('placement-by-student.csv', data.students, ['full_name', 'student_number', 'programme', 'year_of_study', 'placement_status', 'verified'])}>Export</button>
          </div>
          <PlacementChart students={data.students} />
        </section>
      </div>
    </>
  )
}

export function CoordinatorVerify({ token, data, onReload, toast }: { token: string; data: CoordinatorData; onReload: () => void; toast: (message: string) => void }) {
  return <><h1 style={{ marginBottom: 16 }}>Verify students</h1><VerifyTable token={token} students={data.students} onDone={onReload} toast={toast} /></>
}

export function CoordinatorApprovals({ token, data, onReload, toast }: { token: string; data: CoordinatorData; onReload: () => void; toast: (message: string) => void }) {
  return <><h1 style={{ marginBottom: 16 }}>Placement approvals</h1><PlacementApprovals token={token} placements={data.placements} onDone={onReload} toast={toast} /></>
}

export function CoordinatorStudents({ data, reports }: { data: CoordinatorData; reports?: boolean }) {
  const [query, setQuery] = useState('')
  const rows = data.students.filter((row) => `${row.full_name} ${row.student_number} ${row.programme}`.toLowerCase().includes(query.trim().toLowerCase()))
  const columns = ['full_name', 'student_number', 'programme', 'year_of_study', 'placement_status', 'verified']
  return (
    <>
      <div className="apps-head">
        <h1>{reports ? 'Reports' : 'All students'}</h1>
        <button className="btn btn-sm" onClick={() => downloadCsv('internlink-placement-report.csv', data.students, columns)}>Export CSV</button>
      </div>
      {reports && <section className="card" style={{ marginBottom: 18 }}><h2 style={{ marginBottom: 12 }}>Placement rate by programme</h2><PlacementChart students={data.students} /></section>}
      <section className="card" style={{ padding: 0 }}>
        <div className="card-head"><input className="search-input" style={{ maxWidth: 360 }} aria-label="Search students" placeholder="Search by name, number or programme" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
        <div style={{ overflowX: 'auto' }}><table className="s-table">
          <thead><tr><th>Name</th><th>Student no.</th><th>Programme</th><th>Year</th><th>Applications</th><th>Placement</th><th>Verified</th></tr></thead>
          <tbody>{rows.map((row) => (
            <tr key={String(row.student_id)}>
              <td>{String(row.full_name)}</td><td>{String(row.student_number ?? '—')}</td><td>{String(row.programme)}</td><td>{String(row.year_of_study)}</td>
              <td>{String(row.applications_count ?? 0)}</td>
              <td><span className={`status-pill ${row.placement_status === 'placed' ? 'is-green' : row.placement_status === 'pending' ? 'is-blue' : ''}`}>{String(row.placement_status)}</span></td>
              <td>{row.verified ? 'Yes' : <span className="amber">Waiting</span>}</td>
            </tr>
          ))}</tbody>
        </table></div>
        {rows.length === 0 && <div className="empty">No students found.</div>}
      </section>
    </>
  )
}

/* ---------------------------------------------------------------- admin */

export function AdminRequests({ token, registrations, onReload, toast }: { token: string; registrations: Row[]; onReload: () => void; toast: (message: string) => void }) {
  const [tab, setTab] = useState<'company' | 'university' | 'students' | 'suggested'>('company')
  const list = registrations.filter((row) => row.org_type === tab)
  const [selected, setSelected] = useState<number | null>(null)
  const current = list.find((row) => Number(row.org_id) === selected) ?? list[0]
  const [detail, setDetail] = useState<RegistrationDetail | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [requests, setRequests] = useState<UniversityRequest[] | null>(null)

  useEffect(() => {
    setDetail(null)
    setReason('')
    if (!current || tab === 'students') return
    let live = true
    adminApi.registrationDetail(token, tab, Number(current.org_id)).then((result) => { if (live) setDetail(result.registration) }).catch((error: unknown) => toast(messageOf(error)))
    return () => { live = false }
  }, [token, tab, current?.org_id])
  useEffect(() => {
    if (tab !== 'students') return
    adminApi.universityRequests(token).then((result) => setRequests(result.requests)).catch((error: unknown) => toast(messageOf(error)))
  }, [tab, token])

  async function decide(action: 'verified' | 'rejected') {
    if (!current) return
    if (action === 'rejected' && !reason.trim()) {
      toast('Write a reason. It is sent to the organisation.')
      return
    }
    setBusy(true)
    try {
      await roleApi.decideRegistration(token, tab, Number(current.org_id), action, action === 'rejected' ? reason.trim() : undefined)
      toast(action === 'verified' ? `${String(current.name)} verified.` : `${String(current.name)} rejected.`)
      setSelected(null)
      onReload()
    } catch (error) {
      toast(messageOf(error))
    } finally {
      setBusy(false)
    }
  }

  async function closeRequest(name: string, status: 'added' | 'declined') {
    try {
      await adminApi.closeUniversityRequest(token, name, status)
      setRequests((items) => items?.filter((item) => item.university_name !== name) ?? null)
      toast(status === 'added' ? `Marked ${name} as added.` : `Declined requests for ${name}.`)
    } catch (error) {
      toast(messageOf(error))
    }
  }

  const count = (type: string) => registrations.filter((row) => row.org_type === type).length
  return (
    <>
      <div className="apps-head">
        <h1>Organisation requests</h1>
        <div className="tabs" role="tablist">
          {(['company', 'university', 'students', 'suggested'] as const).map((key) => (
            <button key={key} role="tab" aria-selected={tab === key} className={`btn btn-sm ${tab === key ? 'is-current' : ''}`} onClick={() => { setTab(key); setSelected(null) }}>
              {key === 'company' ? `Companies (${count('company')})` : key === 'university' ? `Universities (${count('university')})` : key === 'students' ? 'Student requests for a university' : 'Company suggestions'}
            </button>
          ))}
        </div>
      </div>
      {tab === 'suggested' ? <CompanySuggestions token={token} toast={toast} /> : tab === 'students' ? (
        <section className="card" style={{ padding: 0 }}>
          {!requests && <div className="empty">Loading…</div>}
          {requests?.length === 0 && <div className="empty">No open requests. Students ask for their university at sign-up.</div>}
          {!!requests?.length && <div style={{ overflowX: 'auto' }}><table className="s-table">
            <thead><tr><th>University</th><th>Students asking</th><th>Coordinator emails</th><th>Latest</th><th /></tr></thead>
            <tbody>{requests.map((item) => (
              <tr key={item.university_name}>
                <td><b>{item.university_name}</b></td><td>{item.requests}</td>
                <td>{item.coordinator_emails.length ? item.coordinator_emails.map((email) => <a key={email} href={`mailto:${email}`} style={{ display: 'block' }}>{email}</a>) : <span className="muted">None given</span>}</td>
                <td>{shortDate(item.last_requested_at)}</td>
                <td><div style={{ display: 'flex', gap: 6 }}><button className="btn btn-sm" onClick={() => void closeRequest(item.university_name, 'added')}>Mark added</button><button className="btn btn-sm btn-danger" onClick={() => void closeRequest(item.university_name, 'declined')}>Decline</button></div></td>
              </tr>
            ))}</tbody>
          </table></div>}
        </section>
      ) : list.length === 0 ? <div className="card empty">No {tab === 'company' ? 'companies' : 'universities'} waiting for review.</div> : (
        <div className="requests-grid">
          <div className="request-list" role="list">
            {list.map((row) => (
              <button key={String(row.org_id)} role="listitem" className={current === row ? 'is-selected' : ''} onClick={() => setSelected(Number(row.org_id))}>
                <span><b>{String(row.name)}</b><small>{String(row.contact ?? '')} · submitted {shortDate(String(row.submitted_at))}</small></span>
                <em className={daysSince(row.submitted_at).includes('day') && parseInt(daysSince(row.submitted_at), 10) >= 2 ? 'amber' : ''}>{daysSince(row.submitted_at)}</em>
              </button>
            ))}
          </div>
          <section className="card">
            {!detail ? <div className="empty">Loading…</div> : <>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <span className="logo-box is-lg">{initialsOf(detail.name)}</span>
                <div><h2 style={{ fontSize: 24 }}>{detail.name}</h2>
                  <div className="muted" style={{ fontSize: 14 }}>
                    {detail.org_type === 'company' ? <>{detail.website ? <a href={detail.website} target="_blank" rel="noreferrer noopener">{detail.website}</a> : 'No website'} · {detail.sector} · {detail.location}</> : <>{detail.location} · @{detail.email_domain}</>}
                  </div>
                </div>
              </div>
              <div className="fact-grid">
                {detail.org_type === 'company' ? <>
                  <div><span>EMAIL DOMAIN</span>{detail.email_matches_website == null ? 'No website to compare' : detail.email_matches_website ? 'Matches website' : <b className="amber">Doesn't match website</b>}</div>
                  <div><span>DRAFT LISTINGS</span>{detail.draft_listings ?? 0} waiting to go live</div>
                </> : <>
                  <div><span>EMAIL DOMAIN</span>{detail.email_domain}</div>
                  <div><span>STUDENT REQUESTS</span>{detail.student_requests ?? 0} asked for this university</div>
                </>}
              </div>
              {detail.description && <p style={{ fontSize: 14 }}>{detail.description}</p>}
              <div className="side-label">{detail.org_type === 'company' ? 'People' : 'Coordinators'}</div>
              {detail.people.length === 0 ? <p className="muted">No accounts yet.</p> : detail.people.map((person) => (
                <div key={person.email} style={{ fontSize: 14, marginBottom: 6 }}><b>{person.full_name}</b> · <a href={`mailto:${person.email}`}>{person.email}</a>{person.phone ? ` · ${person.phone}` : ''} · {person.email_confirmed ? 'email confirmed' : <span className="amber">email not confirmed</span>}</div>
              ))}
              <label className="field" style={{ marginTop: 14 }}>Reason (required to reject, sent to the {detail.org_type})<textarea rows={3} maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
              <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
                <button className="btn btn-primary" disabled={busy} onClick={() => void decide('verified')}>Verify {detail.org_type}</button>
                <button className="btn btn-danger" disabled={busy} onClick={() => void decide('rejected')}>Reject</button>
              </div>
            </>}
          </section>
        </div>
      )}
    </>
  )
}

/* ------------------------------------------------- coordinator invites */

/** A university's coordinators, with a form to invite another by email. */
function CoordinatorTeam({ domain, departments, load, invite, canInvite, toast }: {
  domain: string; departments: CatalogItem[]; load: () => Promise<CoordinatorRow[]>
  invite: (email: string, departmentId?: number) => Promise<string>; canInvite: boolean; toast: (message: string) => void
}) {
  const [rows, setRows] = useState<CoordinatorRow[] | null>(null)
  const [email, setEmail] = useState('')
  const [departmentId, setDepartmentId] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  function refresh() {
    load().then(setRows).catch((reason: unknown) => setError(messageOf(reason)))
  }
  useEffect(refresh, [load])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      toast(await invite(email.trim(), departmentId ? Number(departmentId) : undefined))
      setEmail('')
      refresh()
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <section className="card" style={{ padding: 0, marginBottom: 16 }}>
        {!rows && !error && <div className="empty">Loading…</div>}
        {rows?.length === 0 && <div className="empty">No coordinators yet.</div>}
        {!!rows?.length && <div style={{ overflowX: 'auto' }}><table className="s-table">
          <thead><tr><th>Name</th><th>Email</th><th>Covers</th><th>Status</th></tr></thead>
          <tbody>{rows.map((row) => (
            <tr key={row.user_id}>
              <td>{row.invited ? <span className="muted">Not joined yet</span> : row.full_name}</td>
              <td>{row.email}</td>
              <td>{row.department ?? 'Whole university'}</td>
              <td><span className={`status-pill ${row.status === 'active' ? 'is-green' : ''}`}>{row.invited ? `Invited ${shortDate(row.created_at)}` : row.status}</span></td>
            </tr>
          ))}</tbody>
        </table></div>}
      </section>
      {canInvite ? <section className="card">
        <h2>Invite a coordinator</h2>
        <p className="muted" style={{ fontSize: 14, marginTop: 4 }}>They get an email with a link to set their name and password. The link works for 7 days.</p>
        <form className="stack" onSubmit={(event) => void submit(event)}>
          <div className="field-pair">
            <label className="field">Their university email<input type="email" required placeholder={`name@${domain}`} value={email} onChange={(event) => setEmail(event.target.value)} /></label>
            <label className="field">Covers
              <select value={departmentId} onChange={(event) => setDepartmentId(event.target.value)}>
                <option value="">Whole university</option>
                {departments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </label>
          </div>
          {error && <div className="notice is-error" role="alert">{error}</div>}
          <div><button className="btn btn-primary" disabled={busy}>{busy ? 'Sending…' : 'Send invite'}</button></div>
        </form>
      </section> : <div className="notice is-info">Only a coordinator for the whole university can invite colleagues.</div>}
      {error && !canInvite && <div className="notice is-error" style={{ marginTop: 10 }}>{error}</div>}
    </>
  )
}

/** Coordinator's own team page. */
export function CoordinatorTeamPage({ token, toast }: { token: string; toast: (message: string) => void }) {
  const [departments, setDepartments] = useState<CatalogItem[]>([])
  const [canInvite, setCanInvite] = useState(false)
  useEffect(() => {
    roleApi.coordinatorCatalog(token).then((catalog) => {
      setDepartments(catalog.departments)
      setCanInvite(catalog.can_add_departments)  // true only for university-wide coordinators
    }).catch(() => undefined)
  }, [token])
  const load = useMemo(() => () => coordinatorTeamApi.list(token).then((result) => result.coordinators), [token])
  const invite = (email: string, departmentId?: number) => coordinatorTeamApi.invite(token, email, departmentId).then((result) => result.message)
  return (
    <>
      <h1 style={{ marginBottom: 16 }}>Coordinators</h1>
      <CoordinatorTeam domain="your university's domain" departments={departments} load={load} invite={invite} canInvite={canInvite} toast={toast} />
    </>
  )
}

/** Admin: verified universities and their coordinators. */
export function AdminUniversities({ token, toast }: { token: string; toast: (message: string) => void }) {
  const [universities, setUniversities] = useState<VerifiedUniversity[] | null>(null)
  const [selected, setSelected] = useState<number | null>(null)
  const [departments, setDepartments] = useState<CatalogItem[]>([])
  const [error, setError] = useState('')
  useEffect(() => {
    adminApi.universities(token).then((result) => setUniversities(result.universities)).catch((reason: unknown) => setError(messageOf(reason)))
  }, [token])
  const current = universities?.find((item) => item.university_id === selected) ?? universities?.[0]
  useEffect(() => {
    setDepartments([])
    if (current) studentApi.departments(current.university_id).then((result) => setDepartments(result.departments)).catch(() => undefined)
  }, [current?.university_id])
  const load = useMemo(() => () => current ? adminApi.coordinators(token, current.university_id).then((result) => result.coordinators) : Promise.resolve([]), [token, current?.university_id])

  return (
    <>
      <h1 style={{ marginBottom: 16 }}>Universities</h1>
      {error && <div className="notice is-error">{error}</div>}
      {universities?.length === 0 && <div className="card empty">No verified universities yet.</div>}
      {current && <div className="requests-grid">
        <div className="request-list" role="list">
          {universities?.map((item) => (
            <button key={item.university_id} role="listitem" className={item === current ? 'is-selected' : ''} onClick={() => setSelected(item.university_id)}>
              <span><b>{item.name}</b><small>@{item.email_domain} · {item.students} student{item.students === 1 ? '' : 's'}</small></span>
              <em className={item.active_coordinators === 0 ? 'amber' : ''}>{item.active_coordinators} coordinator{item.active_coordinators === 1 ? '' : 's'}</em>
            </button>
          ))}
        </div>
        <div>
          <h2 style={{ marginBottom: 12 }}>{current.name}</h2>
          {current.active_coordinators === 0 && <div className="notice" style={{ marginBottom: 12 }}>This university has no active coordinator, so nobody can verify its students. Invite one below.</div>}
          <CoordinatorTeam key={current.university_id} domain={current.email_domain} departments={departments} load={load} canInvite toast={toast}
            invite={(email, departmentId) => adminApi.invite(token, current.university_id, email, departmentId).then((result) => {
              adminApi.universities(token).then((data) => setUniversities(data.universities)).catch(() => undefined)
              return result.message
            })} />
        </div>
      </div>}
    </>
  )
}

/* ------------------------------------------------- employer company profile */

type CompanyForm = { sector: string; location: string; description: string; contact_email: string; website: string }

/** The employer's company page: logo plus the details students see. */
export function EmployerCompanyProfile({ token, toast }: { token: string; toast: (message: string) => void }) {
  const [company, setCompany] = useState<Row | null>(null)
  const [banner, setBanner] = useState('')
  const [form, setForm] = useState<CompanyForm>({ sector: '', location: '', description: '', contact_email: '', website: '' })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [logoUrl, setLogoUrl] = useState<string | null>(null)
  const [logoBusy, setLogoBusy] = useState(false)
  const [logoError, setLogoError] = useState('')

  useEffect(() => {
    employerRequest<{ company: Row; banner: string | null }>('get_company', token).then((result) => {
      setCompany(result.company)
      setBanner(result.banner ?? '')
      setForm({
        sector: String(result.company.sector ?? ''), location: String(result.company.location ?? ''),
        description: String(result.company.description ?? ''), contact_email: String(result.company.contact_email ?? ''),
        website: String(result.company.website ?? ''),
      })
    }).catch((reason: unknown) => toast(messageOf(reason)))
  }, [token])

  useEffect(() => {
    let url: string | null = null
    employerLogoApi.preview(token).then((preview) => { url = preview; setLogoUrl(preview) })
    return () => { if (url) URL.revokeObjectURL(url) }
  }, [token])

  async function uploadLogo(file: File | undefined) {
    if (!file) return
    setLogoError('')
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
      setLogoError('Upload the logo as a PNG, JPG or WebP image.')
      return
    }
    if (file.size > MAX_LOGO_BYTES) {
      setLogoError('The logo must be 1 MB or smaller.')
      return
    }
    setLogoBusy(true)
    try {
      await employerLogoApi.upload(token, file)
      if (logoUrl) URL.revokeObjectURL(logoUrl)
      setLogoUrl(await employerLogoApi.preview(token))
      toast('Logo updated.')
    } catch (reason) {
      setLogoError(messageOf(reason))
    } finally {
      setLogoBusy(false)
    }
  }

  async function removeLogo() {
    setLogoBusy(true)
    try {
      await employerLogoApi.remove(token)
      if (logoUrl) URL.revokeObjectURL(logoUrl)
      setLogoUrl(null)
      toast('Logo removed.')
    } catch (reason) {
      setLogoError(messageOf(reason))
    } finally {
      setLogoBusy(false)
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setErrors({})
    try {
      await employerRequest('update_company', token, form)
      toast('Company details saved.')
    } catch (reason) {
      toast(messageOf(reason))
      if (reason && typeof reason === 'object' && 'fields' in reason) setErrors((reason as { fields: Record<string, string> }).fields)
    } finally {
      setSaving(false)
    }
  }

  const update = (name: keyof CompanyForm, value: string) => setForm((current) => ({ ...current, [name]: value }))
  if (!company) return <div className="card empty">Loading…</div>
  const name = String(company.name)
  return (
    <>
      <div className="apps-head">
        <h1>Company profile</h1>
        {company.verification_status === 'verified' && <a className="btn btn-sm" href={`/companies/${String(company.company_id)}`} target="_blank" rel="noreferrer">View public page</a>}
      </div>
      {banner && <div className={`notice ${company.verification_status === 'verified' ? 'is-ok' : ''}`} style={{ marginBottom: 14 }}>{banner}</div>}
      <section className="card" style={{ marginBottom: 16 }} aria-label="Logo">
        <h2>Logo</h2>
        <p className="muted" style={{ fontSize: 14, marginTop: 4 }}>Shown on your internships and company page. PNG, JPG or WebP, up to 1 MB. A square image works best.</p>
        <div className="logo-row">
          {logoUrl ? <img className="logo-box is-xl logo-img" src={logoUrl} alt={`${name} logo`} /> : <span className="logo-box is-xl">{initialsOf(name)}</span>}
          <label className={`btn ${logoBusy ? 'is-disabled' : ''}`}>
            <input type="file" className="sr-only" accept="image/png,image/jpeg,image/webp" disabled={logoBusy}
              onChange={(event) => { void uploadLogo(event.target.files?.[0]); event.target.value = '' }} />
            {logoBusy ? 'Uploading…' : logoUrl ? 'Replace logo' : 'Upload logo'}
          </label>
          {logoUrl && <button className="btn btn-danger" disabled={logoBusy} onClick={() => void removeLogo()}>Remove</button>}
        </div>
        {logoError && <div className="notice is-error" role="alert" style={{ marginTop: 10 }}>{logoError}</div>}
      </section>
      <section className="card">
        <h2>{name}</h2>
        <p className="muted" style={{ fontSize: 14, marginTop: 4 }}>The company name can only be changed by the InternLink team.</p>
        <form className="stack" onSubmit={(event) => void save(event)}>
          <div className="field-pair">
            <label className="field">Sector<input value={form.sector} onChange={(event) => update('sector', event.target.value)} required maxLength={100} />{errors.sector && <small className="amber">{errors.sector}</small>}</label>
            <label className="field">Location<input value={form.location} onChange={(event) => update('location', event.target.value)} required maxLength={150} />{errors.location && <small className="amber">{errors.location}</small>}</label>
          </div>
          <label className="field">About the company <small>Students read this on your company page.</small>
            <textarea rows={5} value={form.description} onChange={(event) => update('description', event.target.value)} maxLength={5000} />
          </label>
          <div className="field-pair">
            <label className="field">Contact email<input type="email" value={form.contact_email} onChange={(event) => update('contact_email', event.target.value)} required />{errors.contact_email && <small className="amber">{errors.contact_email}</small>}</label>
            <label className="field">Website<input type="url" placeholder="https://" value={form.website} onChange={(event) => update('website', event.target.value)} />{errors.website && <small className="amber">{errors.website}</small>}</label>
          </div>
          <div><button className="btn btn-primary" disabled={saving}>{saving ? 'Saving…' : 'Save details'}</button></div>
        </form>
      </section>
    </>
  )
}

/** Admin: companies students asked for. */
export function CompanySuggestions({ token, toast }: { token: string; toast: (message: string) => void }) {
  const [rows, setRows] = useState<CompanyRequest[] | null>(null)
  useEffect(() => {
    companyRequestApi.list(token).then((result) => setRows(result.requests)).catch((reason: unknown) => toast(messageOf(reason)))
  }, [token])

  async function close(name: string, status: 'invited' | 'declined') {
    try {
      await companyRequestApi.close(token, name, status)
      setRows((current) => current?.filter((item) => item.company_name !== name) ?? null)
      toast(status === 'invited' ? `Marked ${name} as invited.` : `Declined suggestions for ${name}.`)
    } catch (reason) {
      toast(messageOf(reason))
    }
  }

  return (
    <section className="card" style={{ padding: 0 }}>
      {!rows && <div className="empty">Loading…</div>}
      {rows?.length === 0 && <div className="empty">No open suggestions. Students suggest companies when a search finds nothing.</div>}
      {!!rows?.length && <div style={{ overflowX: 'auto' }}><table className="s-table">
        <thead><tr><th>Company</th><th>Students asking</th><th>Website</th><th>Latest</th><th /></tr></thead>
        <tbody>{rows.map((item) => (
          <tr key={item.company_name}>
            <td><b>{item.company_name}</b></td><td>{item.requests}</td>
            <td>{item.websites.length ? item.websites.map((site) => <a key={site} href={site} target="_blank" rel="noreferrer noopener" style={{ display: 'block' }}>{site}</a>) : <span className="muted">Not given</span>}</td>
            <td>{shortDate(item.last_requested_at)}</td>
            <td><div style={{ display: 'flex', gap: 6 }}><button className="btn btn-sm" onClick={() => void close(item.company_name, 'invited')}>Mark invited</button><button className="btn btn-sm btn-danger" onClick={() => void close(item.company_name, 'declined')}>Decline</button></div></td>
          </tr>
        ))}</tbody>
      </table></div>}
    </section>
  )
}
