import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import {
  ArrowLeft, ArrowRight, Building2, Check, CheckCircle2, CircleHelp, GraduationCap, KeyRound, Mail, School, ShieldCheck,
} from 'lucide-react'
import { accountApi, ApiError, studentApi, type AuthUser, type CatalogItem, type University } from './api'
import { BrandMark } from './BrandMark'

export type Session = { token: string; user: AuthUser }
type AccountType = 'student' | 'employer' | 'university'

type View =
  | { name: 'login'; notice?: string }
  | { name: 'choose' }
  | { name: AccountType }
  | { name: 'forgot' }
  | { name: 'reset'; token: string }
  | { name: 'sent'; title: string; message: string; email?: string }

/** Pages reached from links in our emails. */
const AUTH_LINK_PATHS = ['/verify', '/verify-email', '/reset-password', '/signup']

export function isAuthLinkPath(pathname = window.location.pathname) {
  return AUTH_LINK_PATHS.includes(pathname.replace(/\/+$/, ''))
}

function messageFrom(error: unknown) {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}

function fieldErrors(error: unknown) {
  return error instanceof ApiError ? error.fields : {}
}

/** Reads an email link (verify, reset, sign-up) and clears it from the address bar. */
function useAuthLink(setView: (view: View) => void) {
  useEffect(() => {
    const path = window.location.pathname.replace(/\/+$/, '')
    const token = new URLSearchParams(window.location.search).get('token') ?? ''
    if (!AUTH_LINK_PATHS.includes(path)) return
    window.history.replaceState({}, '', '/')
    if (path === '/signup') {
      setView({ name: 'choose' })
    } else if (path === '/reset-password') {
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

export function AuthGate({ onLogin, toast }: { onLogin: (session: Session) => void; toast: string }) {
  const [view, setView] = useState<View>({ name: 'login' })
  useAuthLink(setView)
  const toLogin = (notice?: string) => setView({ name: 'login', notice })
  const sent = (title: string, message: string, email?: string) => setView({ name: 'sent', title, message, email })

  let card: ReactNode
  switch (view.name) {
    case 'choose':
      card = <ChooseAccount onBack={() => toLogin()} onChoose={(type) => setView({ name: type })} />
      break
    case 'student':
      card = <StudentForm onBack={() => setView({ name: 'choose' })} onDone={(message, email) => sent('Check your inbox', message, email)} />
      break
    case 'employer':
      card = <EmployerForm onBack={() => setView({ name: 'choose' })} onDone={(message, email) => sent('Check your inbox', message, email)} />
      break
    case 'university':
      card = <UniversityForm onBack={() => setView({ name: 'choose' })} onDone={(message, email) => sent('Check your inbox', message, email)} />
      break
    case 'forgot':
      card = <ForgotForm onBack={() => toLogin()} onDone={(message) => sent('Check your inbox', message)} />
      break
    case 'reset':
      card = <ResetForm token={view.token} onBack={() => toLogin()} onDone={(message) => toLogin(message)} />
      break
    case 'sent':
      card = <SentPanel title={view.title} message={view.message} email={view.email} onBack={() => toLogin()} />
      break
    default:
      card = <LoginForm notice={view.notice} onLogin={onLogin} onRegister={() => setView({ name: 'choose' })} onForgot={() => setView({ name: 'forgot' })} />
  }

  return (
    <div className="auth-page">
      <header className="auth-topbar"><BrandMark /><span className="auth-top-note">Your next opportunity starts here</span></header>
      <main className="auth-layout">
        <section className="auth-story">
          <span className="eyebrow"><span className="eyebrow-dot" /> INTERNSHIPS. OPPORTUNITY. GROWTH.</span>
          <h1>Make your next move<br /><em>count.</em></h1>
          <p>One trusted place to find internships, connect with employers and turn your education into experience.</p>
          <div className="story-points">
            <div><span className="story-check"><Check size={15} /></span><span><b>Students</b><small>Personalised internship recommendations</small></span></div>
            <div><span className="story-check"><Check size={15} /></span><span><b>Employers</b><small>Post internships and review ranked applicants</small></span></div>
            <div><span className="story-check"><Check size={15} /></span><span><b>Universities</b><small>Verify students and approve placements</small></span></div>
          </div>
          <div className="auth-story-foot"><ShieldCheck size={16} /> A safer bridge between campus and career.</div>
        </section>
        <section className="auth-card">
          {card}
          {toast && <div className="auth-message"><CircleHelp size={16} />{toast}</div>}
        </section>
      </main>
      <footer className="auth-footer">
        <span>© 2026 InternLink Uganda</span>
        <span>Secure sign-in for students, employers, coordinators and administrators</span>
      </footer>
    </div>
  )
}

function CardHeading({ icon, label, title, subtitle }: { icon: ReactNode; label: string; title: string; subtitle: string }) {
  return (
    <>
      <div className="auth-card-heading"><span className="auth-icon">{icon}</span><span className="tiny-label">{label}</span></div>
      <h2>{title}</h2>
      <p className="auth-subtitle">{subtitle}</p>
    </>
  )
}

function BackLink({ onClick, children = 'Back' }: { onClick: () => void; children?: ReactNode }) {
  return <button type="button" className="back-link" onClick={onClick}><ArrowLeft size={15} /> {children}</button>
}

function Field({ label, error, hint, children }: { label: string; error?: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label>
      {label}
      {children}
      {error ? <small className="field-error">{error}</small> : hint ? <small>{hint}</small> : null}
    </label>
  )
}

function LoginForm({ notice, onLogin, onRegister, onForgot }: {
  notice?: string; onLogin: (session: Session) => void; onRegister: () => void; onForgot: () => void
}) {
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
    <>
      <CardHeading icon={<GraduationCap size={20} />} label="INTERNLINK PORTAL" title="Welcome back" subtitle="Sign in to continue to your InternLink workspace." />
      {notice && <div className="notice-panel" role="status"><CheckCircle2 size={16} />{notice}</div>}
      <form className="auth-form" onSubmit={(event) => void submit(event)}>
        <label>Email address<input type="email" autoComplete="email" placeholder="you@example.com" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
        <label>Password<input type="password" autoComplete="current-password" placeholder="Enter your password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
        <div className="auth-form-row"><span>Use your registered email address</span><button type="button" className="text-button" onClick={onForgot}>Forgot password?</button></div>
        {error && <div className="form-error" role="alert">{error}</div>}
        {unconfirmed && !resent && <button type="button" className="button button-secondary full-button" onClick={() => void resend()}><Mail size={15} /> Send a new confirmation email</button>}
        {resent && <div className="notice-panel" role="status"><Mail size={16} />{resent}</div>}
        <button className="button button-primary full-button" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'} <ArrowRight size={16} /></button>
      </form>
      <div className="auth-register-line">New to InternLink? <button type="button" onClick={onRegister}>Create an account</button></div>
    </>
  )
}

const ACCOUNT_TYPES: { type: AccountType; title: string; detail: string; icon: ReactNode }[] = [
  { type: 'student', title: "I'm a student", detail: 'Find and apply for internships.', icon: <GraduationCap size={18} /> },
  { type: 'employer', title: "I'm hiring interns", detail: 'Register a company and post internships.', icon: <Building2 size={18} /> },
  { type: 'university', title: 'I work at a university', detail: 'Verify students and approve placements.', icon: <School size={18} /> },
]

function ChooseAccount({ onBack, onChoose }: { onBack: () => void; onChoose: (type: AccountType) => void }) {
  const [choice, setChoice] = useState<AccountType>('student')
  return (
    <>
      <BackLink onClick={onBack}>Back to sign in</BackLink>
      <CardHeading icon={<CheckCircle2 size={20} />} label="CREATE AN ACCOUNT" title="Who are you?" subtitle="Choose the account that fits you. You can't change this later." />
      <form className="auth-form" onSubmit={(event) => { event.preventDefault(); onChoose(choice) }}>
        <fieldset className="account-choices">
          <legend className="sr-only">Account type</legend>
          {ACCOUNT_TYPES.map((option) => (
            <label key={option.type} className={`account-choice ${choice === option.type ? 'chosen' : ''}`}>
              <input type="radio" name="account-type" value={option.type} checked={choice === option.type} onChange={() => setChoice(option.type)} />
              <span className="account-choice-icon">{option.icon}</span>
              <span><b>{option.title}</b><small>{option.detail}</small></span>
            </label>
          ))}
        </fieldset>
        <button className="button button-primary full-button">Continue <ArrowRight size={16} /></button>
      </form>
    </>
  )
}

function StudentForm({ onBack, onDone }: { onBack: () => void; onDone: (message: string, email: string) => void }) {
  const [universities, setUniversities] = useState<University[]>([])
  const [departments, setDepartments] = useState<CatalogItem[] | null>(null)
  const [programmes, setProgrammes] = useState<CatalogItem[]>([])
  const [values, setValues] = useState({ full_name: '', email: '', password: '', student_number: '', university_id: '', department_id: '', programme_id: '', year_of_study: '1' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    studentApi.universities()
      .then((result) => setUniversities(result.universities))
      .catch((reason: unknown) => setError(messageFrom(reason)))
  }, [])
  useEffect(() => {
    if (!values.university_id) { setDepartments(null); return }
    studentApi.departments(Number(values.university_id))
      .then((result) => setDepartments(result.departments))
      .catch((reason: unknown) => setError(messageFrom(reason)))
  }, [values.university_id])
  useEffect(() => {
    if (!values.department_id) { setProgrammes([]); return }
    studentApi.programmes(Number(values.department_id))
      .then((result) => setProgrammes(result.programmes))
      .catch((reason: unknown) => setError(messageFrom(reason)))
  }, [values.department_id])

  function update(name: keyof typeof values, value: string) {
    setValues((current) => ({
      ...current,
      [name]: value,
      ...(name === 'university_id' ? { department_id: '', programme_id: '' } : {}),
      ...(name === 'department_id' ? { programme_id: '' } : {}),
    }))
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const result = await studentApi.register({
        ...values,
        university_id: Number(values.university_id),
        department_id: Number(values.department_id),
        programme_id: Number(values.programme_id),
        year_of_study: Number(values.year_of_study),
      })
      onDone(result.message, values.email)
    } catch (reason) {
      setError(messageFrom(reason))
    } finally {
      setBusy(false)
    }
  }

  const universityNotReady = departments !== null && departments.length === 0
  return (
    <>
      <BackLink onClick={onBack} />
      <CardHeading icon={<GraduationCap size={20} />} label="STUDENT ACCOUNT" title="Create your account" subtitle="Register with your university email to get started." />
      <form className="auth-form registration-form" onSubmit={(event) => void submit(event)}>
        <label>Full name<input autoComplete="name" value={values.full_name} onChange={(event) => update('full_name', event.target.value)} required /></label>
        <label>University email<input type="email" autoComplete="email" placeholder="name@university.ac.ug" value={values.email} onChange={(event) => update('email', event.target.value)} required /></label>
        <label>Student number<input value={values.student_number} onChange={(event) => update('student_number', event.target.value)} required /></label>
        <Field label="University" hint="Can't find yours? Ask your internship coordinator to register it with “I work at a university”.">
          <select value={values.university_id} onChange={(event) => update('university_id', event.target.value)} required>
            <option value="">Select university</option>
            {universities.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </Field>
        {universityNotReady && <div className="form-error" role="status">This university hasn't finished setting up its departments yet. Try again later or contact your coordinator.</div>}
        <div className="form-pair">
          <label>Department<select value={values.department_id} onChange={(event) => update('department_id', event.target.value)} required disabled={!departments?.length}><option value="">Select department</option>{departments?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label>Programme<select value={values.programme_id} onChange={(event) => update('programme_id', event.target.value)} required disabled={!programmes.length}><option value="">Select programme</option>{programmes.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        </div>
        <label>Year of study<select value={values.year_of_study} onChange={(event) => update('year_of_study', event.target.value)}>{[1, 2, 3, 4, 5, 6].map((year) => <option key={year} value={year}>Year {year}</option>)}</select></label>
        <Field label="Password" hint="Use at least 10 characters.">
          <input type="password" autoComplete="new-password" minLength={10} value={values.password} onChange={(event) => update('password', event.target.value)} required />
        </Field>
        {error && <div className="form-error" role="alert">{error}</div>}
        <button className="button button-primary full-button" disabled={busy || !universities.length}>{busy ? 'Creating account…' : 'Create account'} <ArrowRight size={16} /></button>
        {!universities.length && !error && <small className="helper-text">Loading universities…</small>}
      </form>
    </>
  )
}

const EMPLOYER_PASSWORD_HINT = 'At least 8 characters, with upper and lower case letters and a digit.'

function EmployerForm({ onBack, onDone }: { onBack: () => void; onDone: (message: string, email: string) => void }) {
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
    <>
      <BackLink onClick={onBack} />
      <CardHeading icon={<Building2 size={20} />} label="EMPLOYER ACCOUNT" title="Register your company" subtitle="Draft listings straight away. They go live once we verify your company." />
      <form className="auth-form registration-form" onSubmit={(event) => void submit(event)}>
        <Field label="Company name" error={errors.company_name}><input autoComplete="organization" value={values.company_name} onChange={(event) => update('company_name', event.target.value)} required /></Field>
        <div className="form-pair">
          <Field label="Sector" error={errors.sector}><input placeholder="e.g. Software" value={values.sector} onChange={(event) => update('sector', event.target.value)} required /></Field>
          <Field label="Location" error={errors.location}><input placeholder="e.g. Kampala" value={values.location} onChange={(event) => update('location', event.target.value)} required /></Field>
        </div>
        <Field label="Website (optional)" error={errors.website}><input type="url" placeholder="https://" value={values.website} onChange={(event) => update('website', event.target.value)} /></Field>
        <Field label="Your full name" error={errors.rep_full_name}><input autoComplete="name" value={values.rep_full_name} onChange={(event) => update('rep_full_name', event.target.value)} required /></Field>
        <div className="form-pair">
          <Field label="Your work email" error={errors.rep_email}><input type="email" autoComplete="email" value={values.rep_email} onChange={(event) => update('rep_email', event.target.value)} required /></Field>
          <Field label="Phone (optional)" error={errors.rep_phone}><input type="tel" autoComplete="tel" placeholder="+256" value={values.rep_phone} onChange={(event) => update('rep_phone', event.target.value)} /></Field>
        </div>
        <Field label="Company contact email (optional)" error={errors.contact_email} hint="Where students and our team can reach the company. Defaults to your work email.">
          <input type="email" value={values.contact_email} onChange={(event) => update('contact_email', event.target.value)} />
        </Field>
        <Field label="Password" error={errors.password} hint={EMPLOYER_PASSWORD_HINT}>
          <input type="password" autoComplete="new-password" minLength={8} value={values.password} onChange={(event) => update('password', event.target.value)} required />
        </Field>
        {error && <div className="form-error" role="alert">{error}</div>}
        <button className="button button-primary full-button" disabled={busy}>{busy ? 'Registering…' : 'Register company'} <ArrowRight size={16} /></button>
      </form>
    </>
  )
}

function UniversityForm({ onBack, onDone }: { onBack: () => void; onDone: (message: string, email: string) => void }) {
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
    <>
      <BackLink onClick={onBack} />
      <CardHeading icon={<School size={20} />} label="UNIVERSITY ACCOUNT" title="Bring your university on board" subtitle="You'll be its first internship coordinator. Our team reviews every university." />
      <form className="auth-form registration-form" onSubmit={(event) => void submit(event)}>
        <label>University name<input value={values.university_name} onChange={(event) => update('university_name', event.target.value)} required /></label>
        <div className="form-pair">
          <label>Location<input placeholder="e.g. Gulu" value={values.location} onChange={(event) => update('location', event.target.value)} required /></label>
          <Field label="Email domain" hint="e.g. gu.ac.ug"><input value={values.email_domain} onChange={(event) => update('email_domain', event.target.value)} required /></Field>
        </div>
        <label>Your full name<input autoComplete="name" value={values.full_name} onChange={(event) => update('full_name', event.target.value)} required /></label>
        <Field label="Your staff email" hint="Must end with the university's email domain.">
          <input type="email" autoComplete="email" value={values.email} onChange={(event) => update('email', event.target.value)} required />
        </Field>
        <Field label="Password" hint="Use at least 10 characters.">
          <input type="password" autoComplete="new-password" minLength={10} value={values.password} onChange={(event) => update('password', event.target.value)} required />
        </Field>
        {error && <div className="form-error" role="alert">{error}</div>}
        <button className="button button-primary full-button" disabled={busy}>{busy ? 'Sending…' : 'Register university'} <ArrowRight size={16} /></button>
      </form>
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
    <>
      <BackLink onClick={onBack}>Back to sign in</BackLink>
      <CardHeading icon={<KeyRound size={20} />} label="ACCOUNT RECOVERY" title="Reset your password" subtitle="Enter your email and we'll send you a link to choose a new password." />
      <form className="auth-form" onSubmit={(event) => void submit(event)}>
        <label>Email address<input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
        {error && <div className="form-error" role="alert">{error}</div>}
        <button className="button button-primary full-button" disabled={busy}>{busy ? 'Sending…' : 'Send reset link'} <ArrowRight size={16} /></button>
      </form>
    </>
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
    <>
      <BackLink onClick={onBack}>Back to sign in</BackLink>
      <CardHeading icon={<KeyRound size={20} />} label="ACCOUNT RECOVERY" title="Choose a new password" subtitle="This signs you out of InternLink on other devices." />
      <form className="auth-form" onSubmit={(event) => void submit(event)}>
        <Field label="New password" hint="At least 10 characters. Employer accounts also need upper and lower case letters and a digit.">
          <input type="password" autoComplete="new-password" minLength={10} value={password} onChange={(event) => setPassword(event.target.value)} required />
        </Field>
        <label>Confirm new password<input type="password" autoComplete="new-password" minLength={10} value={confirm} onChange={(event) => setConfirm(event.target.value)} required /></label>
        {error && <div className="form-error" role="alert">{error}</div>}
        <button className="button button-primary full-button" disabled={busy}>{busy ? 'Saving…' : 'Save new password'} <ArrowRight size={16} /></button>
      </form>
    </>
  )
}

const RESEND_WAIT_SECONDS = 60

function SentPanel({ title, message, email, onBack }: { title: string; message: string; email?: string; onBack: () => void }) {
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
    <div className="success-panel" role="status">
      <Mail size={22} />
      <strong>{title}</strong>
      <p>{message}</p>
      {email && <p>Sent to <b>{email}</b>. The link expires in 24 hours.</p>}
      {resent && <p>{resent}</p>}
      {email && <button type="button" className="button button-secondary" disabled={wait > 0} onClick={() => void resend()}>{wait > 0 ? `Resend email in ${wait}s` : 'Resend email'}</button>}
      <button type="button" className="button button-secondary" onClick={onBack}>Return to sign in</button>
    </div>
  )
}
