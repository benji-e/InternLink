import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Check } from 'lucide-react'
import { alertApi, cvApi, MAX_CV_BYTES, messageApi, savedApi, type CvInfo, type JobAlert, type MessageThread, type SavedItem } from './api'
import { CompanyLogo, initialsOf, messageOf, SaveButton, shortDate, Wordmark, type SiteSession } from './PublicSite'
import { linkTo, navigate } from './router'
import type { Application, Opportunity, StudentProfile } from './types'
import './site.css'

export type StudentPage = 'home' | 'saved' | 'applications' | 'notifications' | 'profile'

const STEPS = [
  { key: 'submitted', label: 'Sent' },
  { key: 'under_review', label: 'Viewed' },
  { key: 'shortlisted', label: 'Shortlisted' },
  { key: 'interview', label: 'Interview' },
  { key: 'accepted', label: 'Offer' },
]
const ACTIVE = ['submitted', 'under_review', 'shortlisted', 'interview', 'accepted']
const STATUS_LABEL: Record<string, string> = {
  submitted: 'Sent', under_review: 'Viewed', shortlisted: 'Shortlisted', interview: 'Interview', accepted: 'Offer', rejected: 'Not selected', withdrawn: 'Withdrawn',
}

function dateTime(value: string) {
  return new Date(value).toLocaleString('en-UG', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

/** A one-event calendar file the student can open in Google/Outlook/Apple calendar. */
function calendarLink(application: Application) {
  if (!application.interviewAt) return '#'
  const start = new Date(application.interviewAt)
  const end = new Date(start.getTime() + 60 * 60 * 1000)
  const stamp = (date: Date) => date.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}/, '')
  const text = (value: string) => value.replace(/[\\,;]/g, (match) => `\\${match}`).replace(/\n/g, ' ')
  const ics = [
    'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//InternLink//Interview//EN', 'BEGIN:VEVENT',
    `UID:interview-${application.id}@internlink`, `DTSTAMP:${stamp(new Date())}`,
    `DTSTART:${stamp(start)}`, `DTEND:${stamp(end)}`,
    `SUMMARY:${text(`Interview: ${application.title} (${application.company})`)}`,
    ...(application.interviewNote ? [`DESCRIPTION:${text(application.interviewNote)}`] : []),
    'END:VEVENT', 'END:VCALENDAR',
  ].join('\r\n')
  return `data:text/calendar;charset=utf-8,${encodeURIComponent(ics)}`
}

export function StudentShell({ page, name, unreadAlerts, unreadMessages, savedCount, onPage, onSignOut, children }: {
  page: StudentPage; name: string; unreadAlerts: number; unreadMessages: number; savedCount: number
  onPage: (page: StudentPage) => void; onSignOut: () => void; children: ReactNode
}) {
  const [menu, setMenu] = useState(false)
  const [query, setQuery] = useState('')
  const items: { page: StudentPage | 'browse'; label: string; count?: number }[] = [
    { page: 'home', label: 'Home' },
    { page: 'browse', label: 'Browse internships' },
    { page: 'saved', label: `Saved (${savedCount})` },
    { page: 'applications', label: 'Applications', count: unreadMessages },
    { page: 'notifications', label: 'Notifications', count: unreadAlerts },
    { page: 'profile', label: 'Profile' },
  ]
  function search(event: FormEvent) {
    event.preventDefault()
    navigate(`/internships${query.trim() ? `?q=${encodeURIComponent(query.trim())}` : ''}`)
  }
  return (
    <div className="site is-grey">
      <header className="site-header">
        <div className="site-container site-header-inner" style={{ maxWidth: 'none' }}>
          <Wordmark to="/dashboard" />
          <form role="search" onSubmit={search} style={{ flex: '0 1 440px' }} className="hide-sm">
            <label className="sr-only" htmlFor="top-search">Search internships</label>
            <input id="top-search" className="search-input" placeholder="Search internships" value={query} onChange={(event) => setQuery(event.target.value)} />
          </form>
          <div className="site-header-actions" style={{ position: 'relative' }}>
            <button className="btn btn-sm" onClick={() => onPage('notifications')}>Alerts · {unreadAlerts}</button>
            <button className="btn btn-sm" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu((value) => !value)}>{initialsOf(name)} ▾</button>
            {menu && <div role="menu" className="card" style={{ position: 'absolute', right: 0, top: 44, padding: 12, minWidth: 200, zIndex: 40 }}>
              <div style={{ fontWeight: 600, marginBottom: 8 }}>{name}</div>
              <button role="menuitem" className="btn btn-sm btn-block" onClick={() => { setMenu(false); onPage('profile') }}>Profile</button>
              <button role="menuitem" className="btn btn-sm btn-block" style={{ marginTop: 6 }} onClick={() => { setMenu(false); onSignOut() }}>Sign out</button>
            </div>}
          </div>
        </div>
      </header>
      <div className="student-shell">
        <nav className="student-side" aria-label="Student">
          {items.map((item) => (
            <button key={item.page} className={page === item.page ? 'is-active' : ''} aria-current={page === item.page ? 'page' : undefined}
              onClick={() => item.page === 'browse' ? navigate('/internships') : onPage(item.page)}>
              <span>{item.label}</span>{!!item.count && <span className="chip">{item.count}</span>}
            </button>
          ))}
        </nav>
        <main className="student-main">{children}</main>
      </div>
    </div>
  )
}

export function StudentHome({ session, profile, applications, recommendations, recommendationsError, saved, loading, onPage, onSavedChange }: {
  session: SiteSession; profile: StudentProfile; applications: Application[]; recommendations: Opportunity[]; recommendationsError: string; saved: SavedItem[]; loading: boolean
  onSavedChange: () => void
  onPage: (page: StudentPage) => void
}) {
  const tasks = [
    { label: 'Confirm your email', done: true },
    { label: 'Choose your programme', done: Boolean(profile.programme) },
    { label: 'Add at least 5 skills', done: profile.skills.length >= 5, action: 'Add' },
    { label: 'Add your interests', done: profile.interests.length > 0, action: 'Add' },
    { label: 'Upload your CV', done: profile.hasCv, action: 'Upload' },
    { label: 'Add your student number', done: Boolean(profile.studentNumber), action: 'Add' },
  ]
  const done = tasks.filter((task) => task.done).length + (profile.verified ? 1 : 0)
  const total = tasks.length + 1
  const count = (statuses: string[]) => applications.filter((item) => statuses.includes(item.status)).length
  const closing = saved.filter((item) => item.is_open && !item.application_status).slice(0, 3)
  const savedIds = new Set(saved.map((item) => item.listing_id))

  return (
    <>
      <h1>Welcome back, {profile.fullName.split(' ')[0]}</h1>
      <p className="muted" style={{ margin: '4px 0 0' }}>Here's what needs your attention.</p>
      <div className="home-grid">
        <section className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><h2>Finish setting up</h2><b>{done} of {total} done</b></div>
          <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}><i style={{ width: `${(done / total) * 100}%` }} /></div>
          {tasks.map((task) => (
            <div key={task.label} className="todo">
              <span className={`tick ${task.done ? 'is-done' : ''}`}>{task.done && <Check size={14} />}</span>
              <span>{task.label}</span>
              {!task.done && task.action && <button className="btn btn-sm" onClick={() => onPage('profile')}>{task.action}</button>}
            </div>
          ))}
          <div className="todo">
            {profile.verified ? <span className="tick is-done"><Check size={14} /></span> : <span className="tick is-warn">!</span>}
            <span>University verification {profile.verified ? 'complete' : <b style={{ color: 'var(--s-amber)' }}>pending</b>}</span>
          </div>
          {!profile.verified && <p className="muted" style={{ fontSize: 13, margin: '4px 0 0' }}>Your internship coordinator verifies your details. You can apply once they do.</p>}
        </section>
        <section className="card">
          <h2>My applications</h2>
          <div className="mini-stats">
            <div><span>SENT</span><b>{applications.length}</b></div>
            <div><span>IN REVIEW</span><b>{count(['under_review'])}</b></div>
            <div><span>INTERVIEW</span><b>{count(['interview'])}</b></div>
            <div><span>OFFERS</span><b>{count(['accepted'])}</b></div>
          </div>
          <button className="btn-link" onClick={() => onPage('applications')}>See all applications</button>
          {closing.length > 0 && <>
            <hr style={{ border: 0, borderTop: '1px solid var(--s-line-soft)', margin: '14px 0' }} />
            <div className="side-label">Saved, closing soon</div>
            {closing.map((item) => <a key={item.listing_id} style={{ display: 'block', fontSize: 14, marginBottom: 4 }} {...linkTo(`/internships/${item.listing_id}`)}>{item.title} · closes {shortDate(item.application_deadline)}</a>)}
          </>}
        </section>
      </div>

      <div className="section-head" style={{ marginTop: 28 }}>
        <div><h2 style={{ fontSize: 22 }}>Recommended for you</h2><p className="muted" style={{ margin: 0 }}>Based on your programme, skills and interests.</p></div>
        <a {...linkTo('/internships')}>See all</a>
      </div>
      {loading && <div className="card empty">Loading recommendations…</div>}
      {!loading && recommendationsError && <div className="card empty">{recommendationsError} <button className="btn-link" onClick={() => onPage('profile')}>Update profile</button></div>}
      {!loading && !recommendationsError && recommendations.length === 0 && <div className="card empty">No recommendations yet. Add skills and interests to your profile, or <a {...linkTo('/internships')}>browse all internships</a>.</div>}
      {!loading && recommendations.length > 0 && <div className="rec-grid">
        {recommendations.slice(0, 6).map((item) => (
          <article key={item.id} className="rec-card">
            <div className="top"><CompanyLogo companyId={item.companyId} name={item.company} hasLogo={item.hasLogo} /><span className="score">{item.match}%</span></div>
            <a className="listing-title" {...linkTo(`/internships/${item.id}`)}>{item.title}</a>
            <div className="listing-meta">{item.company} · {item.remote ? 'Remote' : item.location}{item.duration ? ` · ${item.duration} wks` : ''}</div>
            {item.skills.length > 0 && <div className="matches">Matches: {item.skills.join(', ')}</div>}
            <div className="actions">
              {item.appliedStatus ? <span className="status-pill is-blue">Applied</span> : <>
                <a className="btn btn-primary btn-sm" {...linkTo(`/internships/${item.id}`)}>View &amp; apply</a>
                <SaveButton session={session} listingId={item.id} saved={savedIds.has(item.id)} onChange={onSavedChange} />
              </>}
            </div>
          </article>
        ))}
      </div>}
    </>
  )
}

function Tracker({ status }: { status: string }) {
  const reached = STEPS.findIndex((step) => step.key === status)
  const stopped = status === 'rejected' || status === 'withdrawn'
  return (
    <div className="tracker" aria-label={`Status: ${STATUS_LABEL[status] ?? status}`}>
      {STEPS.map((step, index) => {
        const isDone = stopped ? index === 0 : index <= reached
        return <div key={step.key} className={isDone ? 'is-done' : ''}><i />{step.label}</div>
      })}
    </div>
  )
}

function pillClass(status: string) {
  if (status === 'accepted') return 'is-green'
  if (status === 'rejected' || status === 'withdrawn') return 'is-red'
  return status === 'submitted' ? '' : 'is-blue'
}

export function StudentApplications({ token, applications, onWithdraw, onRead }: {
  token: string; applications: Application[]; onWithdraw: (application: Application) => void; onRead: () => void
}) {
  const [tab, setTab] = useState<'active' | 'closed'>('active')
  const shown = applications.filter((item) => (tab === 'active') === ACTIVE.includes(item.status))
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const selected = shown.find((item) => item.id === selectedId) ?? shown[0] ?? null

  return (
    <>
      <div className="apps-head">
        <h1>Applications</h1>
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === 'active'} className={`btn btn-sm ${tab === 'active' ? 'is-current' : ''}`} onClick={() => setTab('active')}>Active ({applications.filter((item) => ACTIVE.includes(item.status)).length})</button>
          <button role="tab" aria-selected={tab === 'closed'} className={`btn btn-sm ${tab === 'closed' ? 'is-current' : ''}`} onClick={() => setTab('closed')}>Closed</button>
        </div>
      </div>
      {shown.length === 0 ? <div className="card empty">{tab === 'active' ? <>No active applications. <a {...linkTo('/internships')}>Browse internships</a></> : 'No closed applications.'}</div>
        : <div className="apps-grid">
          <div>
            {shown.map((item) => (
              <div key={item.id} role="button" tabIndex={0} className={`app-card ${selected?.id === item.id ? 'is-selected' : ''}`}
                onClick={() => setSelectedId(item.id)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedId(item.id) } }}>
                <div className="top">
                  <div><h3>{item.title}</h3><div className="muted" style={{ fontSize: 14 }}>{item.company} · applied {shortDate(item.submitted)}</div></div>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                    {!!item.unread && <span className="chip">{item.unread} new</span>}
                    <span className={`status-pill ${pillClass(item.status)}`}>{STATUS_LABEL[item.status] ?? item.status}</span>
                  </div>
                </div>
                <Tracker status={item.status} />
                {item.status === 'interview' && item.interviewAt && <div className="app-note">
                  Next: interview on <b>{dateTime(item.interviewAt)}</b>{item.interviewNote ? ` · ${item.interviewNote}` : ''} · <a href={calendarLink(item)} download="interview.ics" onClick={(event) => event.stopPropagation()}>Add to calendar</a>
                </div>}
                {item.status === 'rejected' && item.decisionNote && <div className="app-note">Employer's note: {item.decisionNote}</div>}
                {item.placementStatus && <div className="app-note">Placement {item.placementStatus === 'pending' ? 'waiting for your university to approve' : item.placementStatus}.</div>}
                {['submitted', 'under_review'].includes(item.status) && <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                  <a className="btn btn-sm" {...linkTo(`/internships/${item.opportunityId}`)}>View internship</a>
                  <button className="btn btn-sm" onClick={(event) => { event.stopPropagation(); if (window.confirm(`Withdraw your application for ${item.title}?`)) onWithdraw(item) }}>Withdraw</button>
                </div>}
              </div>
            ))}
          </div>
          {selected && <Conversation key={selected.id} token={token} application={selected} onRead={onRead} />}
        </div>}
    </>
  )
}

function Conversation({ token, application, onRead }: { token: string; application: Application; onRead: () => void }) {
  const [thread, setThread] = useState<MessageThread | null>(null)
  const [error, setError] = useState('')
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let current = true
    messageApi.thread(token, application.id)
      .then((data) => { if (current) { setThread(data); if (application.unread) onRead() } })
      .catch((reason: unknown) => { if (current) setError(messageOf(reason)) })
    return () => { current = false }
  }, [token, application.id])

  async function send(event: FormEvent) {
    event.preventDefault()
    if (!body.trim()) return
    setBusy(true)
    setError('')
    try {
      const { message } = await messageApi.reply(token, application.id, body)
      setThread((current) => current && { ...current, messages: [...current.messages, message] })
      setBody('')
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="chat" aria-label={`Messages about ${application.title}`}>
      <div className="chat-head">
        <span className="logo-box">{initialsOf(application.company)}</span>
        <div><b>{application.company} · {application.title}</b>{thread?.employer_name && <div className="muted" style={{ fontSize: 13 }}>{thread.employer_name}</div>}</div>
      </div>
      <div className="chat-body">
        {!thread && !error && <div className="muted">Loading messages…</div>}
        {thread && thread.messages.length === 0 && <div className="muted" style={{ fontSize: 14 }}>No messages yet. Employers can message you once they shortlist you, and you can reply here.</div>}
        {thread?.messages.map((message) => (
          <div key={message.message_id} className={`bubble ${message.mine ? 'is-mine' : ''}`}>
            {message.body}
            <small>{new Date(message.sent_at).toLocaleString('en-UG', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}{message.mine && message.is_read ? ' · Read' : ''}</small>
          </div>
        ))}
        {error && <div className="notice is-error">{error}</div>}
      </div>
      {thread?.can_reply && <form className="chat-form" onSubmit={(event) => void send(event)}>
        <label className="sr-only" htmlFor="reply">Write a reply</label>
        <textarea id="reply" placeholder="Write a reply…" maxLength={5000} value={body} onChange={(event) => setBody(event.target.value)} />
        <button className="btn btn-primary" disabled={busy || !body.trim()}>Send</button>
      </form>}
    </section>
  )
}

export function SavedPage({ session, saved, onChange }: { session: SiteSession; saved: SavedItem[]; onChange: () => void }) {
  async function remove(listingId: number) {
    if (!session) return
    await savedApi.unsave(session.token, listingId).catch(() => undefined)
    onChange()
  }
  return (
    <>
      <h1>Saved internships</h1>
      <p className="muted" style={{ margin: '4px 0 18px' }}>Internships you saved to come back to.</p>
      {session && <JobAlerts token={session.token} />}
      {saved.length === 0 ? <div className="card empty">Nothing saved yet. Use <b>Save</b> on any internship to keep it here. <a {...linkTo('/internships')}>Browse internships</a></div>
        : saved.map((item) => (
          <article key={item.listing_id} className="result-card">
            <CompanyLogo companyId={item.company_id} name={item.company_name} hasLogo={item.has_logo} />
            <div>
              <div className="muted" style={{ fontSize: 13 }}>{item.company_name} · {item.sector}</div>
              {item.is_open ? <a className="listing-title" {...linkTo(`/internships/${item.listing_id}`)}>{item.title}</a> : <span className="listing-title" style={{ textDecoration: 'none' }}>{item.title}</span>}
              <div className="listing-meta" style={{ marginTop: 4 }}>{item.is_remote ? 'Remote' : item.location} · {item.duration_weeks} weeks</div>
            </div>
            <div className="result-side">
              <span>{item.is_open ? `Closes ${shortDate(item.application_deadline)}` : 'Closed'}</span>
              <div style={{ display: 'flex', gap: 6 }}>
                {item.application_status ? <span className="status-pill is-blue">Applied</span> : item.is_open && <a className="btn btn-primary btn-sm" {...linkTo(`/internships/${item.listing_id}#apply`)}>Apply</a>}
                <button className="btn btn-sm" onClick={() => void remove(item.listing_id)}>Remove</button>
              </div>
            </div>
          </article>
        ))}
    </>
  )
}

/** The student's saved searches. New matches are emailed once a day. */
function JobAlerts({ token }: { token: string }) {
  const [alerts, setAlerts] = useState<JobAlert[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    alertApi.list(token).then((result) => setAlerts(result.alerts)).catch((reason: unknown) => setError(messageOf(reason)))
  }, [token])

  async function remove(alert: JobAlert) {
    try {
      await alertApi.remove(token, alert.alert_id)
      setAlerts((current) => current?.filter((item) => item.alert_id !== alert.alert_id) ?? null)
    } catch (reason) {
      setError(messageOf(reason))
    }
  }

  return (
    <section className="card" style={{ marginBottom: 18 }} aria-label="Job alerts">
      <h2>Job alerts</h2>
      <p className="muted" style={{ fontSize: 14, marginTop: 4 }}>We email you once a day when new internships match. Add one with <b>Get alerts for this search</b> on the <a {...linkTo('/internships')}>search page</a>.</p>
      {error && <div className="notice is-error">{error}</div>}
      {alerts?.length === 0 && <p className="muted" style={{ marginBottom: 0 }}>No job alerts yet.</p>}
      {alerts?.map((alert) => (
        <div key={alert.alert_id} className="todo">
          <span style={{ flex: 1 }}><a {...linkTo(`/internships?${new URLSearchParams(alert.filters)}`)}>{alert.label}</a>
            <span className="muted" style={{ fontSize: 13 }}> · {alert.last_sent_at ? `last email ${shortDate(alert.last_sent_at)}` : 'no matches emailed yet'}</span></span>
          <button className="btn btn-sm" onClick={() => void remove(alert)}>Remove</button>
        </div>
      ))}
    </section>
  )
}

function fileSize(bytes: number) {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`
}

/** Upload, replace, download or remove the student's CV. Employers see it when the student applies. */
export function CvCard({ token, onChange }: { token: string; onChange?: () => void }) {
  const [cv, setCv] = useState<CvInfo | null | undefined>(undefined)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)

  useEffect(() => {
    cvApi.info(token).then((result) => setCv(result.cv)).catch((reason: unknown) => setError(messageOf(reason)))
  }, [token])

  async function upload(file: File | undefined) {
    if (!file) return
    setError('')
    if (!/\.(pdf|docx)$/i.test(file.name)) {
      setError('Upload your CV as a PDF or Word (.docx) file.')
      return
    }
    if (file.size > MAX_CV_BYTES) {
      setError(`That file is ${fileSize(file.size)}. Your CV must be 4 MB or smaller.`)
      return
    }
    setBusy(true)
    try {
      setCv((await cvApi.upload(token, file)).cv)
      onChange?.()
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!window.confirm('Remove your CV? Employers will no longer see it.')) return
    setBusy(true)
    try {
      await cvApi.remove(token)
      setCv(null)
      onChange?.()
    } catch (reason) {
      setError(messageOf(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card" style={{ marginBottom: 18 }} aria-label="CV">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <h2>Your CV</h2>
        <span className="muted" style={{ fontSize: 13 }}>PDF or Word (.docx), up to 4 MB. Employers see it when you apply.</span>
      </div>
      {cv === undefined && !error && <p className="muted">Loading…</p>}
      {cv && <div className="cv-file">
        <span className="logo-box">{cv.content_type.includes('pdf') ? 'PDF' : 'DOC'}</span>
        <div style={{ flex: 1, minWidth: 0 }}><b style={{ overflowWrap: 'anywhere' }}>{cv.filename}</b><div className="muted" style={{ fontSize: 13 }}>{fileSize(cv.size_bytes)} · uploaded {shortDate(cv.uploaded_at)}</div></div>
        <button className="btn btn-sm" disabled={busy} onClick={() => void cvApi.download(token).catch((reason: unknown) => setError(messageOf(reason)))}>Download</button>
        <button className="btn btn-sm btn-danger" disabled={busy} onClick={() => void remove()}>Remove</button>
      </div>}
      {cv !== undefined && <label className={`dropzone ${dragging ? 'is-over' : ''}`}
        onDragOver={(event) => { event.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)}
        onDrop={(event) => { event.preventDefault(); setDragging(false); void upload(event.dataTransfer.files[0]) }}>
        <input type="file" className="sr-only" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          disabled={busy} onChange={(event) => { void upload(event.target.files?.[0]); event.target.value = '' }} />
        {busy ? 'Uploading…' : <>{cv ? 'Replace your CV: drop a new file here or ' : 'Drop your CV here or '}<span className="btn-link">browse</span></>}
      </label>}
      {error && <div className="notice is-error" role="alert" style={{ marginTop: 10 }}>{error}</div>}
    </section>
  )
}

/** Wraps an older page (profile, notifications) so it sits inside the new shell. */
export function LegacyPanel({ children }: { children: ReactNode }) {
  return <div className="legacy-panel">{children}</div>
}
