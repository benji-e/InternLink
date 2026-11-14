import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Check } from 'lucide-react'
import { messageApi, type MessageThread } from './api'
import { initialsOf, messageOf, shortDate, Wordmark } from './PublicSite'
import { linkTo, navigate } from './router'
import type { Application, Opportunity, StudentProfile } from './types'
import './site.css'

export type StudentPage = 'home' | 'applications' | 'notifications' | 'profile'

const STEPS = [
  { key: 'submitted', label: 'Sent' },
  { key: 'under_review', label: 'Viewed' },
  { key: 'shortlisted', label: 'Shortlisted' },
  { key: 'accepted', label: 'Offer' },
]
const ACTIVE = ['submitted', 'under_review', 'shortlisted', 'accepted']
const STATUS_LABEL: Record<string, string> = {
  submitted: 'Sent', under_review: 'Viewed', shortlisted: 'Shortlisted', accepted: 'Offer', rejected: 'Not selected', withdrawn: 'Withdrawn',
}

export function StudentShell({ page, name, unreadAlerts, unreadMessages, onPage, onSignOut, children }: {
  page: StudentPage; name: string; unreadAlerts: number; unreadMessages: number
  onPage: (page: StudentPage) => void; onSignOut: () => void; children: ReactNode
}) {
  const [menu, setMenu] = useState(false)
  const [query, setQuery] = useState('')
  const items: { page: StudentPage | 'browse'; label: string; count?: number }[] = [
    { page: 'home', label: 'Home' },
    { page: 'browse', label: 'Browse internships' },
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

export function StudentHome({ profile, applications, recommendations, recommendationsError, loading, onPage }: {
  profile: StudentProfile; applications: Application[]; recommendations: Opportunity[]; recommendationsError: string; loading: boolean
  onPage: (page: StudentPage) => void
}) {
  const tasks = [
    { label: 'Confirm your email', done: true },
    { label: 'Choose your programme', done: Boolean(profile.programme) },
    { label: 'Add at least 5 skills', done: profile.skills.length >= 5, action: 'Add' },
    { label: 'Add your interests', done: profile.interests.length > 0, action: 'Add' },
    { label: 'Add your student number', done: Boolean(profile.studentNumber), action: 'Add' },
  ]
  const done = tasks.filter((task) => task.done).length + (profile.verified ? 1 : 0)
  const total = tasks.length + 1
  const count = (statuses: string[]) => applications.filter((item) => statuses.includes(item.status)).length
  const closing = recommendations.filter((item) => !item.appliedStatus && item.deadline).slice().sort((a, b) => a.deadline.localeCompare(b.deadline)).slice(0, 2)

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
            <div><span>SHORTLISTED</span><b>{count(['shortlisted'])}</b></div>
            <div><span>OFFERS</span><b>{count(['accepted'])}</b></div>
          </div>
          <button className="btn-link" onClick={() => onPage('applications')}>See all applications</button>
          {closing.length > 0 && <>
            <hr style={{ border: 0, borderTop: '1px solid var(--s-line-soft)', margin: '14px 0' }} />
            <div className="side-label">Recommended, closing soon</div>
            {closing.map((item) => <a key={item.id} style={{ display: 'block', fontSize: 14, marginBottom: 4 }} {...linkTo(`/internships/${item.id}`)}>{item.title} · closes {shortDate(item.deadline)}</a>)}
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
            <div className="top"><span className="logo-box">{initialsOf(item.company)}</span><span className="score">{item.match}%</span></div>
            <a className="listing-title" {...linkTo(`/internships/${item.id}`)}>{item.title}</a>
            <div className="listing-meta">{item.company} · {item.remote ? 'Remote' : item.location}{item.duration ? ` · ${item.duration} wks` : ''}</div>
            {item.skills.length > 0 && <div className="matches">Matches: {item.skills.join(', ')}</div>}
            <div className="actions">
              {item.appliedStatus ? <span className="status-pill is-blue">Applied</span> : <a className="btn btn-primary btn-sm" {...linkTo(`/internships/${item.id}`)}>View &amp; apply</a>}
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

/** Wraps an older page (profile, notifications) so it sits inside the new shell. */
export function LegacyPanel({ children }: { children: ReactNode }) {
  return <div className="legacy-panel">{children}</div>
}
