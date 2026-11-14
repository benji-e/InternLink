import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Mail } from 'lucide-react'
import { accountApi, ApiError, publicApi, studentApi, type AuthUser, type ProgrammeOption, type University } from './api'
import { linkTo, navigate } from './router'
import { Wordmark } from './PublicSite'
import './site.css'

export type Session = { token: string; user: AuthUser }
export type AccountType = 'student' | 'employer' | 'university'

type View =
  | { name: 'login'; notice?: string }
  | { name: 'signup'; type: AccountType }
  | { name: 'forgot' }
  | { name: 'reset'; token: string }
  | { name: 'sent'; message: string; email?: string; type?: AccountType }
  | { name: 'reset-sent'; message: string }

/** Pages reached from links in our emails. */
const AUTH_LINK_PATHS = ['/verify', '/verify-email', '/reset-password']

export function isAuthLinkPath(pathname = window.location.pathname) {
  return AUTH_LINK_PATHS.includes(pathname.replace(/\/+$/, ''))
}

function messageFrom(error: unknown) {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}

function fieldErrors(error: unknown) {
  return error instanceof ApiError ? error.fields : {}
}

function accountType(value: string | null): AccountType {
  return value === 'employer' || value === 'university' ? value : 'student'
}

/** Reads an email link (verify, reset) and replaces it with the sign-in page. */
function useAuthLink(setView: (view: View) => void) {
  useEffect(() => {
    const path = window.location.pathname.replace(/\/+$/, '')
    const token = new URLSearchParams(window.location.search).get('token') ?? ''
    if (!AUTH_LINK_PATHS.includes(path)) return
    navigate('/signin', { replace: true })
    if (path === '/reset-password') {
      setView(token ? { name: 'reset', token } : { name: 'login', notice: 'That reset link is incomplete. Request a new one.' })
    } else if (!token) {
      setView({ name: 'login', notice: 'That confirmation link is incomplete.' })
    } else if (path === '/verify-email') {
      accountApi.verifyEmployerEmail(token)
        .then(() => setView({ name: 'login', notice: 'Email confirmed. You can sign in and draft listings while we verify your company.' }))
        .catch((error: unknown) => setView({ name: 'login', notice: messageFrom(error) }))
    } else {
      studentApi.verifyEmail(token)
        .then((result) => setView({
          name: 'login',
          notice: result.awaiting_review
            ? 'Email confirmed. You can sign in once an administrator approves your university.'
            : 'Email confirmed. You can now sign in.',
        }))
        .catch((error: unknown) => setView({ name: 'login', notice: messageFrom(error) }))
    }
  }, [setView])
}

/** Sign-in, sign-up and password recovery. `path` is /signin or /signup. */
export function AuthGate({ path, search, onLogin }: { path: string; search: string; onLogin: (session: Session) => void }) {
  const params = new URLSearchParams(search)
  const initial: View = path === '/signup' ? { name: 'signup', type: accountType(params.get('type')) } : { name: 'login' }
  const [view, setView] = useState<View>(initial)
  useAuthLink(setView)

  // Follow header links (Sign in / Create account) while this page is open.
  useEffect(() => {
    if (path === '/signup') setView((current) => current.name === 'signup' || current.name === 'sent' ? current : { name: 'signup', type: accountType(params.get('type')) })
    else if (path === '/signin') setView((current) => current.name === 'signup' ? { name: 'login' } : current)
  }, [path])

  const isSignup = view.name === 'signup' || view.name === 'sent'
  return (
    <div className="site is-grey">
      <header className="site-header">
        <div className="site-container site-header-inner">
          <Wordmark />
          <div className="site-header-actions" style={{ fontSize: 15 }}>
            {isSignup ? <span>Already have an account? <a {...linkTo('/signin')}>Sign in</a></span>
              : <span>New to InternLink? <a {...linkTo('/signup')}>Create account</a></span>}
          </div>
        </div>
      </header>
      <main className="site-main">
        <div className="site-container signup-wrap">
          {view.name === 'signup' && <SignUp type={view.type} onType={(type) => { setView({ name: 'signup', type }); navigate(`/signup?type=${type}`, { replace: true }) }} onDone={(message, email) => setView({ name: 'sent', message, email, type: view.type })} />}
          {view.name === 'sent' && <SentStep message={view.message} email={view.email} onChange={() => setView({ name: 'signup', type: view.type ?? 'student' })} />}
          {view.name === 'login' && <div className="auth-single"><LoginForm notice={view.notice} onLogin={onLogin} onForgot={() => setView({ name: 'forgot' })} /></div>}
          {view.name === 'forgot' && <div className="auth-single"><ForgotForm onBack={() => setView({ name: 'login' })} onDone={(message) => setView({ name: 'reset-sent', message })} /></div>}
          {view.name === 'reset-sent' && <div className="auth-single card"><div className="mail-badge"><Mail size={22} /></div><h2>Check your inbox</h2><p className="muted">{view.message}</p><button className="btn" onClick={() => setView({ name: 'login' })}>Back to sign in</button></div>}
          {view.name === 'reset' && <div className="auth-single"><ResetForm token={view.token} onBack={() => setView({ name: 'login' })} onDone={(message) => setView({ name: 'login', notice: message })} /></div>}
        </div>
      </main>
    </div>
  )
}

function Field({ label, error, hint, children }: { label: ReactNode; error?: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="field">
      {label}
      {children}
      {error ? <small style={{ color: 'var(--s-red)' }}>{error}</small> : hint ? <small>{hint}</small> : null}
    </label>
  )
}

function LoginForm({ notice, onLogin, onForgot }: { notice?: string; onLogin: (session: Session) => void; onForgot: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [unconfirmed, setUnconfirmed] = useState(false)
  const [resent, setResent] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setResent('')
    setUnconfirmed(false)
    setBusy(true)
    try {
      const response = await studentApi.login(email, password)
      onLogin({ token: response.access_token, user: response.user })
    } catch (reason) {
      setError(messageFrom(reason))
      setUnconfirmed(reason instanceof ApiError && reason.code === 'ACCOUNT_PENDING')
    } finally {
      setBusy(false)
    }
  }

  async function resend() {
    try {
      setResent((await accountApi.resendVerification(email)).message)
    } catch (reason) {
      setResent(messageFrom(reason))
    }
  }

  return (
    <section className="card">
      <h1 className="signup-title" style={{ fontSize: 28 }}>Sign in</h1>
      <p className="muted" style={{ marginTop: 0 }}>Welcome back to InternLink.</p>
      {notice && <div className="notice is-ok" role="status" style={{ marginBottom: 12 }}>{notice}</div>}
      <form className="stack" onSubmit={(event) => void submit(event)}>
        <Field label="Email"><input type="email" autoComplete="email" placeholder="you@example.com" value={email} onChange={(event) => setEmail(event.target.value)} required /></Field>
        <Field label={<span style={{ display: 'flex', justifyContent: 'space-between' }}>Password <button type="button" className="btn-link" style={{ fontSize: 13 }} onClick={onForgot}>Forgot password?</button></span>}>
          <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
        </Field>
        {error && <div className="notice is-error" role="alert">{error}</div>}
        {unconfirmed && !resent && <button type="button" className="btn" onClick={() => void resend()}><Mail size={15} /> Send a new confirmation email</button>}
        {resent && <div className="notice is-info" role="status">{resent}</div>}
        <button className="btn btn-primary btn-block" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </section>
  )
}

const ACCOUNT_TYPES: { type: AccountType; title: string; detail: string }[] = [
  { type: 'student', title: "I'm a student", detail: 'Find and apply for internships.' },
  { type: 'employer', title: "I'm hiring interns", detail: 'Register a company and post internships.' },
  { type: 'university', title: 'I work at a university', detail: 'Verify students and approve placements.' },
]

function Stepper({ step }: { step: 1 | 2 | 3 }) {
  const labels = ['Account type', 'Your details', 'Confirm email']
  return (
    <ol className="stepper" aria-label="Sign-up progress" style={{ listStyle: 'none', padding: 0 }}>
      {labels.map((label, index) => {
        const number = index + 1
        const state = number < step ? 'is-done' : number === step ? 'is-current' : ''
        return <li key={label} style={{ display: 'contents' }}>
          {index > 0 && <i aria-hidden="true" />}
          <span className={state} aria-current={number === step ? 'step' : undefined}><b>{number}</b>{label}</span>
        </li>
      })}
    </ol>
  )
}

function SignUp({ type, onType, onDone }: { type: AccountType; onType: (type: AccountType) => void; onDone: (message: string, email: string) => void }) {
  const [requesting, setRequesting] = useState(false)
  return (
    <>
      <Stepper step={2} />
      <h1 className="signup-title">Create your InternLink account</h1>
      <p className="muted" style={{ margin: 0 }}>Choose who you are. You can't change this later.</p>
      <fieldset className="type-grid" style={{ border: 0, padding: 0 }}>
        <legend className="sr-only">Account type</legend>
        {ACCOUNT_TYPES.map((option) => (
          <label key={option.type} className={`type-option ${type === option.type ? 'is-chosen' : ''}`}>
            <input type="radio" name="account-type" checked={type === option.type} onChange={() => { onType(option.type); setRequesting(false) }} />
            <span><b>{option.title}</b><small>{option.detail}</small></span>
          </label>
        ))}
      </fieldset>
      <div className={`signup-grid ${type === 'student' ? '' : 'is-single'}`}>
        {type === 'student' && <StudentForm onDone={onDone} onRequestUniversity={() => setRequesting(true)} />}
        {type === 'employer' && <EmployerForm onDone={onDone} />}
        {type === 'university' && <UniversityForm onDone={onDone} />}
        {type === 'student' && (requesting ? <RequestUniversity onClose={() => setRequesting(false)} /> : <section className="card">
          <span className="eyebrow-s">Before you start</span>
          <h2>Use your university email</h2>
          <p className="muted" style={{ fontSize: 14 }}>InternLink checks that you study at the university you choose, so sign up with the email address your university gave you (for example <b>name@std.must.ac.ug</b>). You'll add skills and interests after signing in.</p>
          <p style={{ fontSize: 14, margin: 0 }}>University not listed? <button type="button" className="btn-link" onClick={() => setRequesting(true)}>Request your university</button></p>
        </section>)}
      </div>
    </>
  )
}

function passwordStrength(password: string) {
  if (!password) return { score: 0, label: '' }
  let score = password.length >= 10 ? 1 : 0
  if (/\d/.test(password)) score += 1
  if (/[^A-Za-z0-9]/.test(password)) score += 1
  if (/[a-z]/.test(password) && /[A-Z]/.test(password) && password.length >= 12) score += 1
  const labels = ['too short', 'weak', 'fair', 'good', 'strong']
  const advice = password.length < 10 ? 'Use at least 10 characters.' : score < 3 ? 'Add a number or symbol.' : ''
  return { score, label: `Strength: ${labels[score]}.${advice ? ` ${advice}` : ''}` }
}

function StudentForm({ onDone, onRequestUniversity }: { onDone: (message: string, email: string) => void; onRequestUniversity: () => void }) {
  const [universities, setUniversities] = useState<University[]>([])
  const [universityText, setUniversityText] = useState('')
  const [programmes, setProgrammes] = useState<ProgrammeOption[] | null>(null)
  const [values, setValues] = useState({ full_name: '', email: '', password: '', student_number: '', programme_id: '', year_of_study: '1' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const university = universities.find((item) => item.name.toLowerCase() === universityText.trim().toLowerCase())

  useEffect(() => {
    studentApi.universities()
      .then((result) => setUniversities(result.universities))
      .catch((reason: unknown) => setError(messageFrom(reason)))
  }, [])
  // Ignore replies for an earlier choice, so a slow response can't show another university's programmes.
  useEffect(() => {
    setProgrammes(null)
    setValues((current) => ({ ...current, programme_id: '' }))
    if (!university) return
    let current = true
    publicApi.universityProgrammes(university.id)
      .then((result) => { if (current) setProgrammes(result.programmes) })
      .catch((reason: unknown) => { if (current) setError(messageFrom(reason)) })
    return () => { current = false }
  }, [university?.id])

  const update = (name: keyof typeof values, value: string) => setValues((current) => ({ ...current, [name]: value }))
  const programme = programmes?.find((item) => String(item.id) === values.programme_id)
  const departments = [...new Set(programmes?.map((item) => item.department) ?? [])]
  const strength = passwordStrength(values.password)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!university || !programme) {
      setError(!university ? 'Choose your university from the list.' : 'Choose your programme.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const result = await studentApi.register({
        ...values,
        university_id: university.id,
        department_id: programme.department_id,
        programme_id: programme.id,
        year_of_study: Number(values.year_of_study),
      })
      onDone(result.message, values.email)
    } catch (reason) {
      setError(messageFrom(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <span className="eyebrow-s">Step 2 · Student</span>
      <h2>Your details</h2>
      <form className="stack" style={{ marginTop: 14 }} onSubmit={(event) => void submit(event)}>
        <Field label="Full name"><input autoComplete="name" placeholder="e.g. Nakato Sarah" value={values.full_name} onChange={(event) => update('full_name', event.target.value)} required /></Field>
        <Field label="University" hint={<button type="button" className="btn-link" style={{ fontSize: 12 }} onClick={onRequestUniversity}>My university isn't listed</button>}>
          <input list="universities" placeholder={universities.length ? 'Start typing your university…' : 'Loading universities…'} value={universityText} onChange={(event) => setUniversityText(event.target.value)} required autoComplete="off" />
          <datalist id="universities">{universities.map((item) => <option key={item.id} value={item.name} />)}</datalist>
        </Field>
        {universityText && !university && universities.length > 0 && <div className="notice" role="status">Pick a university from the list, or request yours.</div>}
        <Field label="University email" hint={university?.email_domain ? `Use your ${university.email_domain} address (a student address such as std.${university.email_domain} works too).` : 'Use the email address your university gave you.'}>
          <input type="email" autoComplete="email" placeholder={university?.email_domain ? `name@${university.email_domain}` : 'you@university.ac.ug'} value={values.email} onChange={(event) => update('email', event.target.value)} required />
        </Field>
        <div className="field-pair">
          <Field label="Programme">
            <select value={values.programme_id} onChange={(event) => update('programme_id', event.target.value)} required disabled={!programmes?.length}>
              <option value="">{university ? (programmes ? 'Select programme' : 'Loading…') : 'Choose university first'}</option>
              {departments.map((department) => <optgroup key={department} label={department}>
                {programmes?.filter((item) => item.department === department).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </optgroup>)}
            </select>
          </Field>
          <Field label="Year of study">
            <select value={values.year_of_study} onChange={(event) => update('year_of_study', event.target.value)}>{[1, 2, 3, 4, 5, 6].map((year) => <option key={year} value={year}>Year {year}</option>)}</select>
          </Field>
        </div>
        {programmes && programmes.length === 0 && <div className="notice" role="status">This university hasn't added its programmes yet. Ask your internship coordinator to add them.</div>}
        <Field label="Student number"><input value={values.student_number} onChange={(event) => update('student_number', event.target.value)} required /></Field>
        <Field label="Password" hint={strength.label || 'At least 10 characters.'}>
          <input type="password" autoComplete="new-password" minLength={10} placeholder="At least 10 characters" value={values.password} onChange={(event) => update('password', event.target.value)} required />
          <div className="strength" aria-hidden="true">{[1, 2, 3, 4].map((step) => <i key={step} className={strength.score >= step ? 'is-on' : ''} />)}</div>
        </Field>
        {error && <div className="notice is-error" role="alert">{error}</div>}
        <button className="btn btn-primary btn-block" disabled={busy}>{busy ? 'Creating account…' : 'Create account'}</button>
      </form>
    </section>
  )
}

function RequestUniversity({ onClose }: { onClose: () => void }) {
  const [values, setValues] = useState({ university_name: '', requester_email: '', coordinator_email: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState('')
  const update = (name: keyof typeof values, value: string) => setValues((current) => ({ ...current, [name]: value }))

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      setDone((await publicApi.requestUniversity({ ...values, coordinator_email: values.coordinator_email || undefined })).message)
    } catch (reason) {
      setError(messageFrom(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <span className="eyebrow-s">If the university isn't listed</span>
      <h2>Request your university</h2>
      {done ? <div className="stack" style={{ marginTop: 12 }}><div className="notice is-ok" role="status">{done}</div><button className="btn" onClick={onClose}>Close</button></div>
        : <form className="stack" style={{ marginTop: 12 }} onSubmit={(event) => void submit(event)}>
          <Field label="University name"><input placeholder="Full university name" value={values.university_name} onChange={(event) => update('university_name', event.target.value)} required maxLength={160} /></Field>
          <Field label="Your email" hint="We'll tell you when your university joins."><input type="email" value={values.requester_email} onChange={(event) => update('requester_email', event.target.value)} required /></Field>
          <Field label="Coordinator's email (optional)" hint="Your internship coordinator, if you know them. We'll invite them."><input type="email" value={values.coordinator_email} onChange={(event) => update('coordinator_email', event.target.value)} /></Field>
          {error && <div className="notice is-error" role="alert">{error}</div>}
          <div style={{ display: 'flex', gap: 8 }}><button className="btn btn-primary" disabled={busy}>{busy ? 'Sending…' : 'Send request'}</button><button type="button" className="btn" onClick={onClose}>Cancel</button></div>
          <small className="muted">Student accounts need a listed university, so you'll be able to sign up once it joins.</small>
        </form>}
    </section>
  )
}

const EMPLOYER_PASSWORD_HINT = 'At least 8 characters, with upper and lower case letters and a digit.'
const SECTORS = ['Software', 'Data & analytics', 'Finance', 'Telecoms', 'Agriculture', 'Healthcare', 'Education', 'Engineering', 'Media', 'NGO', 'Government', 'Other']

function EmployerForm({ onDone }: { onDone: (message: string, email: string) => void }) {
  const [values, setValues] = useState({
    company_name: '', sector: '', location: '', website: '', contact_email: '',
    rep_full_name: '', rep_email: '', rep_phone: '', password: '',
  })
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const update = (name: keyof typeof values, value: string) => setValues((current) => ({ ...current, [name]: value }))

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setErrors({})
    try {
      // Company contact email defaults to the representative's own address.
      const result = await accountApi.registerEmployer({ ...values, contact_email: values.contact_email || values.rep_email })
      onDone(result.message, values.rep_email)
    } catch (reason) {
      setError(messageFrom(reason))
      setErrors(fieldErrors(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <span className="eyebrow-s">Step 2 · Employer</span>
      <h2>Your company</h2>
      <form className="stack" style={{ marginTop: 14 }} onSubmit={(event) => void submit(event)}>
        <Field label="Company name" error={errors.company_name}><input autoComplete="organization" value={values.company_name} onChange={(event) => update('company_name', event.target.value)} required /></Field>
        <Field label="Your full name" error={errors.rep_full_name}><input autoComplete="name" value={values.rep_full_name} onChange={(event) => update('rep_full_name', event.target.value)} required /></Field>
        <Field label="Your work email" error={errors.rep_email}><input type="email" autoComplete="email" placeholder="you@company.co.ug" value={values.rep_email} onChange={(event) => update('rep_email', event.target.value)} required /></Field>
        <div className="field-pair">
          <Field label="Sector" error={errors.sector}>
            <select value={values.sector} onChange={(event) => update('sector', event.target.value)} required>
              <option value="">Select sector</option>
              {SECTORS.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </Field>
          <Field label="Phone (optional)" error={errors.rep_phone}><input type="tel" autoComplete="tel" placeholder="+256 …" value={values.rep_phone} onChange={(event) => update('rep_phone', event.target.value)} /></Field>
        </div>
        <div className="field-pair">
          <Field label="Location" error={errors.location}><input placeholder="e.g. Kampala" value={values.location} onChange={(event) => update('location', event.target.value)} required /></Field>
          <Field label="Website (optional)" error={errors.website}><input type="url" placeholder="https://" value={values.website} onChange={(event) => update('website', event.target.value)} /></Field>
        </div>
        <Field label="Password" error={errors.password} hint={EMPLOYER_PASSWORD_HINT}>
          <input type="password" autoComplete="new-password" minLength={8} value={values.password} onChange={(event) => update('password', event.target.value)} required />
        </Field>
        <div className="notice is-info">You can sign in and draft listings straight away. Listings go live once our team verifies your company.</div>
        {error && <div className="notice is-error" role="alert">{error}</div>}
        <button className="btn btn-primary btn-block" disabled={busy}>{busy ? 'Registering…' : 'Register company'}</button>
      </form>
    </section>
  )
}

function UniversityForm({ onDone }: { onDone: (message: string, email: string) => void }) {
  const [values, setValues] = useState({ university_name: '', location: '', email_domain: '', full_name: '', email: '', password: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const update = (name: keyof typeof values, value: string) => setValues((current) => ({ ...current, [name]: value }))

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const result = await accountApi.registerUniversity(values)
      onDone(result.message, values.email)
    } catch (reason) {
      setError(messageFrom(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <span className="eyebrow-s">Step 2 · University</span>
      <h2>Bring your university on board</h2>
      <p className="muted" style={{ fontSize: 14 }}>You'll be its first internship coordinator. Our team reviews every university.</p>
      <form className="stack" onSubmit={(event) => void submit(event)}>
        <Field label="University name"><input value={values.university_name} onChange={(event) => update('university_name', event.target.value)} required /></Field>
        <div className="field-pair">
          <Field label="Location"><input placeholder="e.g. Gulu" value={values.location} onChange={(event) => update('location', event.target.value)} required /></Field>
          <Field label="Email domain" hint="e.g. gu.ac.ug"><input value={values.email_domain} onChange={(event) => update('email_domain', event.target.value)} required /></Field>
        </div>
        <Field label="Your full name"><input autoComplete="name" value={values.full_name} onChange={(event) => update('full_name', event.target.value)} required /></Field>
        <Field label="Your staff email" hint="Must end with the university's email domain."><input type="email" autoComplete="email" value={values.email} onChange={(event) => update('email', event.target.value)} required /></Field>
        <Field label="Password" hint="At least 10 characters."><input type="password" autoComplete="new-password" minLength={10} value={values.password} onChange={(event) => update('password', event.target.value)} required /></Field>
        {error && <div className="notice is-error" role="alert">{error}</div>}
        <button className="btn btn-primary btn-block" disabled={busy}>{busy ? 'Sending…' : 'Register university'}</button>
      </form>
    </section>
  )
}

const RESEND_WAIT_SECONDS = 60

function SentStep({ message, email, onChange }: { message: string; email?: string; onChange: () => void }) {
  const [wait, setWait] = useState(email ? RESEND_WAIT_SECONDS : 0)
  const [resent, setResent] = useState('')

  useEffect(() => {
    if (wait <= 0) return
    const timer = window.setTimeout(() => setWait((value) => value - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [wait])

  async function resend() {
    if (!email) return
    setWait(RESEND_WAIT_SECONDS)
    try {
      setResent((await accountApi.resendVerification(email)).message)
    } catch (reason) {
      setResent(messageFrom(reason))
    }
  }

  return (
    <>
      <Stepper step={3} />
      <section className="card auth-single" role="status" style={{ marginLeft: 0 }}>
        <span className="eyebrow-s">Step 3</span>
        <div className="mail-badge"><Mail size={22} /></div>
        <h2>Check your inbox</h2>
        <p>{email ? <>We sent a link to <b>{email}</b>. It expires in 24 hours.</> : message}</p>
        {email && <p className="muted" style={{ fontSize: 14 }}>{message}</p>}
        {resent && <div className="notice is-info" style={{ marginBottom: 12 }}>{resent}</div>}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {email && <button type="button" className="btn" disabled={wait > 0} onClick={() => void resend()}>{wait > 0 ? `Resend email in ${wait}s` : 'Resend email'}</button>}
          <button type="button" className="btn" onClick={onChange}>Change email</button>
          <a className="btn btn-primary" {...linkTo('/signin')}>Go to sign in</a>
        </div>
      </section>
    </>
  )
}

function ForgotForm({ onBack, onDone }: { onBack: () => void; onDone: (message: string) => void }) {
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      onDone((await accountApi.forgotPassword(email)).message)
    } catch (reason) {
      setError(messageFrom(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <h2>Reset your password</h2>
      <p className="muted" style={{ fontSize: 14 }}>Enter your email and we'll send you a link to choose a new password.</p>
      <form className="stack" onSubmit={(event) => void submit(event)}>
        <Field label="Email"><input type="email" autoComplete="email" placeholder="you@example.com" value={email} onChange={(event) => setEmail(event.target.value)} required /></Field>
        {error && <div className="notice is-error" role="alert">{error}</div>}
        <button className="btn btn-primary btn-block" disabled={busy}>{busy ? 'Sending…' : 'Send reset link'}</button>
        <button type="button" className="btn-link" onClick={onBack}>Back to sign in</button>
      </form>
    </section>
  )
}

function ResetForm({ token, onBack, onDone }: { token: string; onBack: () => void; onDone: (message: string) => void }) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    if (password !== confirm) {
      setError('The two passwords don’t match.')
      return
    }
    setBusy(true)
    try {
      onDone((await accountApi.resetPassword(token, password)).message)
    } catch (reason) {
      setError(messageFrom(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <h2>Choose a new password</h2>
      <p className="muted" style={{ fontSize: 14 }}>This signs you out of InternLink on other devices.</p>
      <form className="stack" onSubmit={(event) => void submit(event)}>
        <Field label="New password" hint="At least 10 characters. Employer accounts also need upper and lower case letters and a digit.">
          <input type="password" autoComplete="new-password" minLength={10} value={password} onChange={(event) => setPassword(event.target.value)} required />
        </Field>
        <Field label="Confirm new password"><input type="password" autoComplete="new-password" minLength={10} value={confirm} onChange={(event) => setConfirm(event.target.value)} required /></Field>
        {error && <div className="notice is-error" role="alert">{error}</div>}
        <button className="btn btn-primary btn-block" disabled={busy}>{busy ? 'Saving…' : 'Save new password'}</button>
        <button type="button" className="btn-link" onClick={onBack}>Back to sign in</button>
      </form>
    </section>
  )
}
