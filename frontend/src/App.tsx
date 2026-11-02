import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import {
  ArrowDownUp, ArrowLeft, ArrowRight, Bell, BriefcaseBusiness,
  Check, CheckCircle2, ChevronDown, ChevronRight, CircleHelp, Clock3, FileText,
  Filter, GraduationCap, LayoutDashboard, LogOut, MapPin, Menu, Search,
  ShieldCheck, SlidersHorizontal, Sparkles, Users, X,
} from 'lucide-react'
import { ApiError, employerRequest, roleApi, studentApi, type AuthUser, type CatalogItem, type University } from './api'
import type { Application, Opportunity, Page, Role, StudentProfile } from './types'
import './App.css'

type LiveUser = AuthUser
type LiveSession = { token: string; user: LiveUser }
type NotificationItem = { id: number; title: string; message: string; time: string; read: boolean }

const SESSION_KEY = 'internlink-student-session'

const studentNav: { page: Page; label: string; icon: typeof LayoutDashboard }[] = [
  { page: 'dashboard', label: 'Recommended', icon: Sparkles },
  { page: 'browse', label: 'Browse internships', icon: Search },
  { page: 'applications', label: 'My applications', icon: FileText },
  { page: 'notifications', label: 'Notifications', icon: Bell },
  { page: 'profile', label: 'My profile', icon: GraduationCap },
]

const employerNav: { page: Page; label: string; icon: typeof LayoutDashboard }[] = [
  { page: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { page: 'listings', label: 'My listings', icon: BriefcaseBusiness },
  { page: 'applicants', label: 'Applicants', icon: Users },
  { page: 'messages', label: 'Messages', icon: Bell },
]

const universityNav: { page: Page; label: string; icon: typeof LayoutDashboard }[] = [
  { page: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { page: 'approvals', label: 'Pending approvals', icon: CheckCircle2 },
  { page: 'students', label: 'Students', icon: Users },
  { page: 'reports', label: 'Reports', icon: FileText },
]

const adminNav: { page: Page; label: string; icon: typeof LayoutDashboard }[] = [
  { page: 'approvals', label: 'Registrations', icon: ShieldCheck },
  { page: 'users', label: 'Users & roles', icon: Users },
  { page: 'reports', label: 'Activity log', icon: FileText },
]

const emptyProfile: StudentProfile = {
  fullName: 'Student',
  email: '',
  university: '',
  programme: '',
  year: 1,
  studentNumber: '',
  location: '',
  relocate: false,
  verified: false,
  skills: [],
  interests: [],
  completeness: 0,
}

function messageFrom(error: unknown) {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}

function readSession(): LiveSession | null {
  try {
    const stored = localStorage.getItem(SESSION_KEY)
    if (!stored) return null
    const value = JSON.parse(stored) as LiveSession
    return value.token && value.user && value.user.role ? value : null
  } catch {
    return null
  }
}

function mapOpportunity(row: Record<string, unknown>, index: number): Opportunity {
  return {
    id: Number(row.listing_id ?? row.id ?? index + 1),
    title: String(row.title ?? 'Internship opportunity'),
    company: String(row.company ?? row.company_name ?? 'Verified employer'),
    sector: String(row.sector ?? 'Opportunity'),
    location: String(row.location ?? 'Uganda'),
    remote: Boolean(row.is_remote ?? row.remote),
    duration: Number(row.duration_weeks ?? row.duration ?? 0),
    deadline: String(row.deadline ?? row.application_deadline ?? ''),
    slots: Number(row.slots_remaining ?? row.slots ?? 1),
    description: String(row.description ?? 'See the opportunity details for more information.'),
    skills: Array.isArray(row.required_skills) ? row.required_skills.map(String) : Array.isArray(row.matched_skills) ? row.matched_skills.map(String) : [],
    match: Number(row.score ?? row.match ?? 0),
    appliedStatus: typeof row.application_status === 'string' ? row.application_status : null,
  }
}

function mapApplication(row: Record<string, unknown>, index: number): Application {
  return {
    id: Number(row.application_id ?? row.id ?? index + 1),
    opportunityId: Number(row.listing_id ?? row.opportunityId ?? 0),
    title: String(row.title ?? 'Internship opportunity'),
    company: String(row.company_name ?? row.company ?? 'Employer'),
    location: String(row.location ?? 'Uganda'),
    submitted: String(row.submitted_at ?? row.submitted ?? ''),
    status: String(row.status ?? 'submitted'),
    match: Number(row.match_score ?? row.match ?? 0),
  }
}

function mapProfile(row: Record<string, unknown>): StudentProfile {
  const skills = Array.isArray(row.skills) ? row.skills.map((skill) => typeof skill === 'object' && skill !== null ? String((skill as Record<string, unknown>).name) : String(skill)) : []
  const interests = Array.isArray(row.interests) ? row.interests.map((interest) => typeof interest === 'object' && interest !== null ? String((interest as Record<string, unknown>).name) : String(interest)) : []
  return {
    fullName: String(row.full_name ?? 'Student'),
    email: String(row.email ?? ''),
    university: String(row.university ?? ''),
    programme: String(row.programme ?? ''),
    year: Number(row.year_of_study ?? 1),
    studentNumber: String(row.student_number ?? ''),
    location: String(row.preferred_location ?? ''),
    relocate: Boolean(row.willing_to_relocate),
    verified: Boolean(row.verified),
    skills,
    interests,
    completeness: Number(row.completeness_pct ?? 40),
  }
}

function App() {
  const restoredSession = useMemo(readSession, [])
  const [role, setRole] = useState<Role | null>(restoredSession?.user.role ?? null)
  const [page, setPage] = useState<Page>('dashboard')
  const [session, setSession] = useState<LiveSession | null>(restoredSession)
  const [profile, setProfile] = useState<StudentProfile>(emptyProfile)
  const [liveRecommendations, setLiveRecommendations] = useState<Opportunity[]>([])
  const [liveOpportunities, setLiveOpportunities] = useState<Opportunity[]>([])
  const [liveApplications, setLiveApplications] = useState<Application[]>([])
  const [liveNotifications, setLiveNotifications] = useState<NotificationItem[]>([])
  const [loading, setLoading] = useState(false)
  const [toast, setToast] = useState('')
  const [selectedOpportunity, setSelectedOpportunity] = useState<Opportunity | null>(null)
  const [showApply, setShowApply] = useState(false)
  const [search, setSearch] = useState('')
  const [sector, setSector] = useState('All sectors')
  const [location, setLocation] = useState('All locations')
  const [duration, setDuration] = useState('Any duration')
  const [applicationStatus, setApplicationStatus] = useState('All statuses')
  const [mobileMenu, setMobileMenu] = useState(false)
  const [accountMenu, setAccountMenu] = useState(false)
  const [selectedListingId, setSelectedListingId] = useState<number | null>(null)
  const [employerDashboard, setEmployerDashboard] = useState<Record<string, unknown> | null>(null)
  const [employerListings, setEmployerListings] = useState<Record<string, unknown>[]>([])
  const [employerApplicants, setEmployerApplicants] = useState<Record<string, unknown>[]>([])
  const [employerConversations, setEmployerConversations] = useState<Record<string, unknown>[]>([])
  const [selectedMessageConversation, setSelectedMessageConversation] = useState<Record<string, unknown> | null>(null)
  const [adminRegistrations, setAdminRegistrations] = useState<Record<string, unknown>[]>([])
  const [adminUsers, setAdminUsers] = useState<Record<string, unknown>[]>([])
  const [adminAudit, setAdminAudit] = useState<Record<string, unknown>[]>([])
  const [coordinatorStats, setCoordinatorStats] = useState<Record<string, unknown> | null>(null)
  const [coordinatorStudents, setCoordinatorStudents] = useState<Record<string, unknown>[]>([])
  const [coordinatorPlacements, setCoordinatorPlacements] = useState<Record<string, unknown>[]>([])
  const [roleLoading, setRoleLoading] = useState(false)

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(''), 3600)
    return () => window.clearTimeout(timer)
  }, [toast])

  useEffect(() => {
    const verifyToken = new URLSearchParams(window.location.search).get('token')
    if (window.location.pathname === '/verify' && verifyToken) {
      studentApi.verifyEmail(verifyToken)
        .then(() => setToast('Email verified. You can now sign in.'))
        .catch((error: unknown) => setToast(messageFrom(error)))
      window.history.replaceState({}, '', '/')
    }
  }, [])

  useEffect(() => {
    if (!session) return
    if (session.user.role === 'student') void loadLiveStudent(session)
    else void loadLiveRole(session)
  }, [session, selectedListingId])

  async function loadLiveRole(active: LiveSession) {
    setRoleLoading(true)
    try {
      if (active.user.role === 'employer') {
        const [dashboard, listings, conversations] = await Promise.all([
          employerRequest<Record<string, unknown>>('dashboard', active.token),
          employerRequest<Record<string, unknown>[]>('my_listings', active.token),
          employerRequest<Record<string, unknown>[]>('inbox', active.token),
        ])
        setEmployerDashboard(dashboard)
        setEmployerListings(listings)
        setEmployerConversations(conversations)
        if (listings.length) {
          const listingId = selectedListingId ?? Number(listings[0].listing_id)
          if (selectedListingId === null) setSelectedListingId(listingId)
          const result = await employerRequest<{ applicants: Record<string, unknown>[] }>('applicants', active.token, { listing_id: listingId })
          setEmployerApplicants(result.applicants)
        } else {
          setEmployerApplicants([])
        }
      } else if (active.user.role === 'admin') {
        const [registrations, users] = await Promise.all([
          roleApi.adminRegistrations(active.token),
          roleApi.adminUsers(active.token),
        ])
        setAdminRegistrations(registrations.registrations)
        setAdminUsers(users.users)
        const audit = await roleApi.adminAudit(active.token)
        setAdminAudit(audit.events)
      } else if (active.user.role === 'university') {
        const [dashboard, students, placements] = await Promise.all([
          roleApi.coordinatorDashboard(active.token),
          roleApi.coordinatorStudents(active.token),
          roleApi.coordinatorPlacements(active.token),
        ])
        setCoordinatorStats(dashboard.stats)
        setCoordinatorStudents(students.students)
        setCoordinatorPlacements(placements.placements)
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) signOut()
      else setToast(messageFrom(error))
    } finally {
      setRoleLoading(false)
    }
  }

  async function loadLiveStudent(active: LiveSession) {
    setLoading(true)
    try {
      const [profileResult, recommendationResult, applicationResult, notificationResult] = await Promise.all([
        studentApi.profile(active.token),
        studentApi.recommendations(active.token),
        studentApi.applications(active.token),
        studentApi.notifications(active.token),
      ])
      setProfile(mapProfile(profileResult.profile))
      setLiveRecommendations(recommendationResult.results.map(mapOpportunity))
      setLiveApplications(applicationResult.applications.map(mapApplication))
      setLiveNotifications(notificationResult.notifications.map((item, index) => ({
        id: Number(item.notification_id ?? index),
        title: String(item.title ?? 'InternLink update'),
        message: String(item.message ?? ''),
        time: String(item.created_at ?? ''),
        read: Boolean(item.is_read),
      })))
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        signOut()
      } else {
        setToast(messageFrom(error))
      }
    } finally {
      setLoading(false)
    }
  }

  function signOut() {
    localStorage.removeItem(SESSION_KEY)
    setSession(null)
    setRole(null)
    setPage('dashboard')
    setSelectedListingId(null)
    setLiveRecommendations([])
    setLiveApplications([])
    setLiveOpportunities([])
    setToast('')
  }

  function handleLogin(active: LiveSession) {
    localStorage.setItem(SESSION_KEY, JSON.stringify(active))
    setSession(active)
    setSelectedListingId(null)
    setProfile((current) => ({ ...current, fullName: active.user.full_name, email: active.user.email }))
    setRole(active.user.role)
    setPage(active.user.role === 'admin' ? 'approvals' : active.user.role === 'employer' ? 'dashboard' : 'dashboard')
    setToast('')
  }

  async function loadBrowseResults() {
    if (!session) return
    setLoading(true)
    const params = new URLSearchParams()
    if (search.trim()) params.set('search', search.trim())
    if (sector !== 'All sectors') params.set('sector', sector)
    if (location !== 'All locations') params.set('location', location)
    if (duration === '1–8 weeks') { params.set('min_weeks', '1'); params.set('max_weeks', '8') }
    if (duration === '9–16 weeks') { params.set('min_weeks', '9'); params.set('max_weeks', '16') }
    if (duration === '17+ weeks') params.set('min_weeks', '17')
    try {
      const result = await studentApi.opportunities(session.token, params)
      setLiveOpportunities(result.results.map(mapOpportunity))
    } catch (error) {
      setToast(messageFrom(error))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (page !== 'browse' || role !== 'student') return
    const timer = window.setTimeout(() => void loadBrowseResults(), 250)
    return () => window.clearTimeout(timer)
  }, [page, role, session, sector, location, duration, search])

  async function submitApplication(opportunity: Opportunity, coverNote: string) {
    if (!session) return
    setLoading(true)
    try {
      await studentApi.apply(session.token, opportunity.id, coverNote)
      setToast('Application submitted. You can track it in My applications.')
      setShowApply(false)
      setSelectedOpportunity(null)
      await loadLiveStudent(session)
    } catch (error) {
      setToast(messageFrom(error))
    } finally {
      setLoading(false)
    }
  }

  async function saveProfile(next: StudentProfile, selectedSkillIds: number[], selectedInterestIds: number[]) {
    if (!session) return
    setLoading(true)
    try {
      const result = await studentApi.saveProfile(session.token, {
        year_of_study: next.year,
        preferred_location: next.location,
        willing_to_relocate: next.relocate,
        skills: selectedSkillIds,
        interests: selectedInterestIds,
      })
      const updated = mapProfile(result.profile)
      setProfile(updated)
      setToast('Your profile was updated.')
      await loadLiveStudent(session)
    } catch (error) {
      setToast(messageFrom(error))
    } finally {
      setLoading(false)
    }
  }

  async function withdrawApplication(application: Application) {
    if (!session) return
    try {
      await studentApi.withdraw(session.token, application.id)
      await loadLiveStudent(session)
      setToast('Application withdrawn.')
    } catch (error) {
      setToast(messageFrom(error))
    }
  }

  async function markNotificationRead(id: number) {
    if (!session) return
    try {
      await studentApi.markNotificationRead(session.token, id)
      setLiveNotifications((current) => current.map((item) => item.id === id ? { ...item, read: true } : item))
    } catch (error) {
      setToast(messageFrom(error))
    }
  }

  if (!role) {
    return <AuthGate onLogin={handleLogin} toast={toast} />
  }

  const nav = role === 'student' ? studentNav : role === 'employer' ? employerNav : role === 'university' ? universityNav : adminNav
  const userName = session?.user.full_name ?? profile.fullName
  const applications = liveApplications
  const listings = liveOpportunities.map((opportunity) => ({
    ...opportunity,
    appliedStatus: applications.find((application) => application.opportunityId === opportunity.id)?.status ?? opportunity.appliedStatus,
  }))

  function changePage(next: Page) {
    setPage(next)
    setMobileMenu(false)
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="menu-toggle icon-button" aria-label="Open menu" onClick={() => setMobileMenu((open) => !open)}>
          <Menu size={20} />
        </button>
        <BrandMark />
        <div className="topbar-spacer" />
        <span className="live-badge"><span /> Connected</span>
        <button className="top-icon icon-button" aria-label="Help"><CircleHelp size={19} /></button>
        <button className="account-chip" onClick={() => setAccountMenu((open) => !open)} aria-expanded={accountMenu} aria-haspopup="menu" title="Account menu">
          <span className="avatar">{initials(userName)}</span>
          <span className="account-name">{userName.split(' ')[0]}</span>
          <ChevronDown size={15} />
        </button>
        {accountMenu && <div className="account-menu" role="menu">
          <strong>{userName}</strong><small>{session?.user.email}</small>
          <button role="menuitem" onClick={() => { setAccountMenu(false); signOut() }}>Log in with another account</button>
          <button role="menuitem" onClick={() => { setAccountMenu(false); signOut() }}><LogOut size={15} /> Log out</button>
        </div>}
      </header>

      <div className="workspace">
        <aside className={`sidebar ${mobileMenu ? 'sidebar-open' : ''}`}>
          <div className="workspace-label">{role === 'student' ? 'STUDENT SPACE' : role === 'employer' ? 'EMPLOYER SPACE' : role === 'university' ? 'UNIVERSITY SPACE' : 'ADMIN SPACE'}</div>
          <nav className="side-nav">
            {nav.map(({ page: navPage, label, icon: Icon }) => (
              <button key={navPage} className={`nav-item ${page === navPage ? 'active' : ''}`} onClick={() => changePage(navPage)}>
                <Icon size={18} strokeWidth={1.9} /><span>{label}</span>
                {navPage === 'notifications' && role === 'student' && <span className="nav-count">{liveNotifications.filter((item) => !item.read).length}</span>}
              </button>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <div className="help-card">
              <div className="help-icon"><CircleHelp size={17} /></div>
              <strong>Need a hand?</strong>
              <p>We're here to help you make your next move.</p>
              <button onClick={() => setToast('Support: hello@internlink.ug')}>Get support <ArrowRight size={14} /></button>
            </div>
            <button className="signout-link" onClick={signOut}><LogOut size={17} /> Sign out / switch role</button>
            <div className="sidebar-foot">© 2026 InternLink Uganda</div>
          </div>
        </aside>

        <main className="main-content">
          <div className="mobile-page-title">{nav.find((item) => item.page === page)?.label}</div>
          {role === 'student' && (
            <StudentWorkspace
              page={page}
              profile={profile}
              applications={applications}
              recommendations={liveRecommendations}
              opportunities={listings}
              loading={loading}
              search={search}
              setSearch={setSearch}
              sector={sector}
              setSector={setSector}
              location={location}
              setLocation={setLocation}
              duration={duration}
              setDuration={setDuration}
              applicationStatus={applicationStatus}
              setApplicationStatus={setApplicationStatus}
              notifications={liveNotifications}
              token={session?.token ?? ''}
              onApply={(opportunity) => { setSelectedOpportunity(opportunity); setShowApply(true) }}
              onSaveProfile={saveProfile}
              onWithdraw={withdrawApplication}
              onMarkNotificationRead={markNotificationRead}
              toast={setToast}
              onBrowse={loadBrowseResults}
            />
          )}
          {role === 'employer' && page === 'messages' && session && (
            <EmployerMessages token={session.token} conversations={employerConversations} initialConversation={selectedMessageConversation} toast={setToast} onRefresh={() => loadLiveRole(session)} />
          )}
          {role === 'employer' && page !== 'messages' && (
            <LiveRoleWorkspace role="employer" page={page} loading={roleLoading} data={employerDashboard} records={page === 'applicants' ? employerApplicants : employerListings} onPage={changePage} onRefresh={() => session && void loadLiveRole(session)} onSelectListing={(id) => { setSelectedListingId(id); setPage('applicants') }} onMessage={(row) => { setSelectedMessageConversation(row); setPage('messages') }} onLoadListing={async (id) => {
              if (!session) throw new Error('Sign in to manage listings.')
              return employerRequest<Record<string, unknown>>('listing_detail', session.token, { listing_id: id })
            }} onSaveListing={async (id, form) => {
              if (!session) return
              await employerRequest(id === null ? 'create_listing' : 'update_listing', session.token, {
                ...form,
                ...(id === null ? {} : { listing_id: id }),
              })
              await loadLiveRole(session)
              setToast(id === null ? 'Internship saved as a draft. Publish it when ready.' : 'Internship changes saved.')
            }} onAction={async (id, action) => {
              if (!session) return
              try {
                if (page === 'listings') {
                  await employerRequest('set_listing_status', session.token, {
                    listing_id: id,
                    status: action === 'Publish' ? 'open' : 'closed',
                  })
                } else {
                  await employerRequest('decide', session.token, { application_id: id, action: action.toLowerCase() })
                }
                await loadLiveRole(session)
              } catch (error) { setToast(messageFrom(error)) }
            }} />
          )}
          {role === 'university' && (
            <LiveRoleWorkspace role="university" page={page} loading={roleLoading} data={coordinatorStats} records={page === 'approvals' ? coordinatorPlacements : coordinatorStudents} onPage={changePage} onRefresh={() => session && void loadLiveRole(session)} onAction={async (id, action) => {
              if (!session) return
              try {
                if (page === 'students') await roleApi.verifyStudent(session.token, id)
                else await roleApi.decidePlacement(session.token, id, action === 'Approve' ? 'confirmed' : 'rejected', action === 'Reject' ? 'Rejected by university coordinator' : undefined)
                await loadLiveRole(session)
              } catch (error) { setToast(messageFrom(error)) }
            }} />
          )}
          {role === 'admin' && (
            <LiveRoleWorkspace role="admin" page={page} loading={roleLoading} data={null} records={page === 'users' ? adminUsers : page === 'reports' ? adminAudit : adminRegistrations} onPage={changePage} onRefresh={() => session && void loadLiveRole(session)} onAction={async (id, action, type) => {
              if (!session) return
              try {
                if (page === 'users') await roleApi.updateUser(session.token, id, action === 'Verify' ? 'active' : 'suspended')
                else await roleApi.decideRegistration(session.token, type ?? 'company', id, action === 'Verify' ? 'verified' : 'rejected', action === 'Reject' ? 'Rejected by platform administrator' : undefined)
                await loadLiveRole(session)
              } catch (error) { setToast(messageFrom(error)) }
            }} />
          )}
        </main>
      </div>

      {selectedOpportunity && (
        <OpportunityDialog
          opportunity={selectedOpportunity}
          apply={showApply}
          canApply={profile.verified}
          loading={loading}
          onClose={() => { setSelectedOpportunity(null); setShowApply(false) }}
          onApply={(note) => void submitApplication(selectedOpportunity, note)}
          onStartApply={() => setShowApply(true)}
        />
      )}
      {toast && <div className="toast"><CheckCircle2 size={17} />{toast}<button onClick={() => setToast('')} aria-label="Dismiss"><X size={15} /></button></div>}
    </div>
  )
}

function BrandMark() {
  return (
    <div className="brand-lockup">
      <span className="brand-icon"><span /><span /><span /></span>
      <span className="brand-name">intern<span>link</span></span>
      <span className="brand-region">UGANDA</span>
    </div>
  )
}

function LiveRoleWorkspace({
  role,
  page,
  loading,
  data,
  records,
  onPage,
  onRefresh,
  onSelectListing,
  onMessage,
  onLoadListing,
  onSaveListing,
  onAction,
}: {
  role: Exclude<Role, 'student'>
  page: Page
  loading: boolean
  data: Record<string, unknown> | null
  records: Record<string, unknown>[]
  onPage: (page: Page) => void
  onRefresh: () => void
  onSelectListing?: (listingId: number) => void
  onMessage?: (row: Record<string, unknown>) => void
  onLoadListing?: (listingId: number) => Promise<Record<string, unknown>>
  onSaveListing?: (listingId: number | null, form: Record<string, unknown>) => Promise<void>
  onAction: (id: number, action: string, type?: string) => Promise<void>
}) {
  const [creatingListing, setCreatingListing] = useState(false)
  const [savingListing, setSavingListing] = useState(false)
  const [listingError, setListingError] = useState('')
  const [editingListingId, setEditingListingId] = useState<number | null>(null)
  const [listingTags, setListingTags] = useState({
    programme_ids: [] as number[],
    required_skill_ids: [] as number[],
    optional_skill_ids: [] as number[],
    interest_ids: [] as number[],
  })
  const [listingForm, setListingForm] = useState({
    title: '',
    description: '',
    sector: '',
    location: '',
    duration_weeks: '12',
    slots: '1',
    application_deadline: '',
    is_remote: false,
  })
  const headings: Record<Role, string> = {
    student: 'Student workspace',
    employer: page === 'applicants' ? 'Applicants' : page === 'listings' ? 'My listings' : 'Employer dashboard',
    university: page === 'approvals' ? 'Placement approvals' : page === 'students' ? 'Students' : page === 'reports' ? 'Placement report' : 'University dashboard',
    admin: page === 'users' ? 'Users & roles' : page === 'reports' ? 'Activity log' : 'Organisation registrations',
  }
  const title = headings[role]
  const columns = role === 'employer' && page === 'applicants'
    ? ['applicant_name', 'programme', 'match_score', 'status', 'submitted_at']
    : role === 'employer'
      ? ['title', 'status', 'application_deadline', 'slots', 'applicants']
      : role === 'university' && page === 'approvals'
        ? ['student_name', 'programme', 'listing_title', 'company_name']
        : role === 'university'
          ? ['full_name', 'student_number', 'programme', 'year_of_study', 'placement_status', 'verified']
          : role === 'admin' && page === 'users'
            ? ['full_name', 'email', 'role', 'status', 'organisation']
            : ['name', 'org_type', 'contact', 'submitted_at']
  const actionForRow = (row: Record<string, unknown>) => {
    if (role === 'employer' && page === 'applicants') return { id: Number(row.application_id), type: undefined }
    if (role === 'university' && page === 'approvals') return { id: Number(row.placement_id), type: undefined }
    if (role === 'university') return { id: Number(row.student_id), type: undefined }
    if (role === 'admin' && page === 'users') return { id: Number(row.user_id), type: undefined }
    return { id: Number(row.org_id), type: String(row.org_type ?? 'company') }
  }

  return (
    <div className="page-wrap">
      <PageIntro
        eyebrow={role === 'admin' ? 'PLATFORM ADMIN' : role === 'university' ? 'UNIVERSITY COORDINATOR' : 'EMPLOYER SPACE'}
        title={title}
        description={role === 'admin' ? 'Manage registered organisations and platform accounts.' : role === 'university' ? 'Review student records and placement outcomes for your institution.' : 'Manage your internship opportunities and applicants.'}
        action={<div className="page-actions">{role === 'university' && page === 'reports' && <button className="button button-secondary button-small" onClick={() => downloadCsv('internlink-placement-report.csv', records, ['full_name', 'student_number', 'programme', 'year_of_study', 'placement_status', 'verified'])}>Export CSV</button>}<button className="button button-secondary button-small" onClick={onRefresh}>Refresh</button></div>}
      />
      {role === 'employer' && page === 'dashboard' && data && <div className="stats-strip four-stats">
        <MiniStat label="New applications" value={Number(data.new_applications ?? 0)} icon={<Users size={16} />} />
        <MiniStat label="Shortlisted" value={Number(data.shortlisted ?? 0)} icon={<CheckCircle2 size={16} />} />
        <MiniStat label="Unread messages" value={Number(data.unread_messages ?? 0)} icon={<Bell size={16} />} />
        <MiniStat label="Unread notifications" value={Number(data.unread_notifications ?? 0)} icon={<Bell size={16} />} />
      </div>}
      {role === 'university' && page === 'dashboard' && data && <div className="metric-grid">
        <MetricCard number={String(data.enrolled ?? 0)} label="Enrolled students" icon={<Users size={17} />} color="blue" />
        <MetricCard number={String(data.placed ?? 0)} label="Placed" icon={<CheckCircle2 size={17} />} color="green" />
        <MetricCard number={String(data.pending ?? 0)} label="Pending approval" icon={<Clock3 size={17} />} color="amber" />
        <MetricCard number={String(data.unplaced ?? 0)} label="Unplaced" icon={<GraduationCap size={17} />} color="purple" />
      </div>}
      {role === 'university' && page === 'reports' && data && <div className="metric-grid">
        <MetricCard number={String(data.enrolled ?? 0)} label="Enrolled students" icon={<Users size={17} />} color="blue" />
        <MetricCard number={String(data.placed ?? 0)} label="Placed" icon={<CheckCircle2 size={17} />} color="green" />
        <MetricCard number={String(data.pending ?? 0)} label="Pending approval" icon={<Clock3 size={17} />} color="amber" />
        <MetricCard number={String(data.unplaced ?? 0)} label="Unplaced" icon={<GraduationCap size={17} />} color="purple" />
      </div>}
      {role === 'admin' && <div className="university-tabs">
        <button className={page === 'approvals' ? 'selected' : ''} onClick={() => onPage('approvals')}>Registrations</button>
        <button className={page === 'users' ? 'selected' : ''} onClick={() => onPage('users')}>Users &amp; roles</button>
      </div>}
      {role === 'employer' && <div className="university-tabs">
        <button className={page === 'dashboard' ? 'selected' : ''} onClick={() => onPage('dashboard')}>Dashboard</button>
        <button className={page === 'listings' ? 'selected' : ''} onClick={() => onPage('listings')}>My listings</button>
        <button className={page === 'applicants' ? 'selected' : ''} onClick={() => onPage('applicants')}>Applicants</button>
      </div>}
      {role === 'university' && <div className="university-tabs">
        <button className={page === 'dashboard' ? 'selected' : ''} onClick={() => onPage('dashboard')}>Overview</button>
        <button className={page === 'approvals' ? 'selected' : ''} onClick={() => onPage('approvals')}>Placement approvals</button>
        <button className={page === 'students' ? 'selected' : ''} onClick={() => onPage('students')}>Students</button>
      </div>}
      {role === 'admin' && page === 'reports' && <AdminAuditLog records={records} />}
      {role !== 'admin' || page !== 'reports' ? <div className="table-card">
        <div className="table-toolbar"><div><h2>{title}</h2><p>Live records from the shared InternLink database.</p></div></div>
        {loading ? <LoadingState /> : records.length === 0 ? <EmptyState title="Nothing to review" detail="New records will appear here as accounts, opportunities and applications are created." /> : <div className="table-scroll"><table><thead><tr>{columns.map((column) => <th key={column}>{column.replaceAll('_', ' ')}</th>)}<th>Action</th></tr></thead><tbody>
          {records.map((row, index) => {
            const { id, type } = actionForRow(row)
            const alreadyVerified = Boolean(row.verified)
            const isActive = row.status === 'active'
            const actionLabel = role === 'employer' ? 'Shortlist' : role === 'university' ? page === 'students' ? alreadyVerified ? 'Verified' : 'Verify student' : 'Approve' : page === 'users' ? isActive ? 'Suspend' : 'Activate' : 'Verify'
            return <tr key={id || index}>
              {columns.map((column) => <td key={column}>{column === 'submitted_at' ? formatDate(String(row[column] ?? '')) : String(row[column] ?? '—')}</td>)}
              <td><div className="decision-actions">
                {role === 'employer' && page === 'applicants' && <button className="button button-mini" disabled={row.status === 'shortlisted'} onClick={() => void onAction(id, 'shortlist')}>Shortlist</button>}
                {role === 'employer' && page === 'applicants' && <button className="button button-mini button-reject" disabled={row.status === 'rejected'} onClick={() => void onAction(id, 'reject')}>Reject</button>}
                {role === 'employer' && page === 'applicants' && ['shortlisted', 'accepted'].includes(String(row.status)) && <button className="button button-mini" onClick={() => onMessage?.(row)}>Message</button>}
                {role === 'university' && page === 'students' && <button className="button button-mini" disabled={alreadyVerified} onClick={() => void onAction(id, 'Verify')}>{actionLabel}</button>}
                {role === 'university' && page === 'approvals' && <><button className="button button-mini" onClick={() => void onAction(id, 'Approve')}>Approve</button><button className="button button-mini button-reject" onClick={() => void onAction(id, 'Reject')}>Reject</button></>}
                {role === 'admin' && page === 'approvals' && <><button className="button button-mini" onClick={() => void onAction(id, 'Verify', type)}>Verify</button><button className="button button-mini button-reject" onClick={() => void onAction(id, 'Reject', type)}>Reject</button></>}
                {role === 'admin' && page === 'users' && row.role !== 'admin' && <button className={`button button-mini ${isActive ? 'button-reject' : ''}`} onClick={() => void onAction(id, isActive ? 'Suspend' : 'Verify')}>{actionLabel}</button>}
                {role === 'employer' && page === 'listings' && <button className="button button-mini" onClick={() => onSelectListing?.(id)}>View applicants</button>}
                {role === 'employer' && page === 'listings' && row.status !== 'closed' && <button className="button button-mini" disabled={!onLoadListing || savingListing} onClick={() => {
                  if (!onLoadListing) return
                  setListingError('')
                  void onLoadListing(id).then((listing) => {
                    const skills = Array.isArray(listing.skills) ? listing.skills as Record<string, unknown>[] : []
                    const programmes = Array.isArray(listing.programmes) ? listing.programmes as Record<string, unknown>[] : []
                    const interests = Array.isArray(listing.interests) ? listing.interests as Record<string, unknown>[] : []
                    setListingForm({
                      title: String(listing.title ?? ''),
                      description: String(listing.description ?? ''),
                      sector: String(listing.sector ?? ''),
                      location: String(listing.location ?? ''),
                      duration_weeks: String(listing.duration_weeks ?? '12'),
                      slots: String(listing.slots ?? '1'),
                      application_deadline: String(listing.application_deadline ?? '').slice(0, 10),
                      is_remote: Boolean(listing.is_remote),
                    })
                    setListingTags({
                      programme_ids: programmes.map((item) => Number(item.programme_id)),
                      required_skill_ids: skills.filter((item) => item.is_required).map((item) => Number(item.skill_id)),
                      optional_skill_ids: skills.filter((item) => !item.is_required).map((item) => Number(item.skill_id)),
                      interest_ids: interests.map((item) => Number(item.interest_id)),
                    })
                    setEditingListingId(id)
                    setCreatingListing(true)
                  }).catch((error: unknown) => setListingError(messageFrom(error)))
                }}>Edit</button>}
                {role === 'employer' && page === 'listings' && row.status === 'draft' && <button className="button button-mini" disabled={data?.company_status !== 'verified'} onClick={() => void onAction(id, 'Publish')}>Publish</button>}
                {role === 'employer' && page === 'listings' && row.status === 'open' && <button className="button button-mini button-reject" onClick={() => void onAction(id, 'Close')}>Close</button>}
              </div></td>
            </tr>
          })}
        </tbody></table></div>}
      </div> : null}
      {role === 'employer' && page === 'listings' && <section className="table-card listing-create-card">
        <div className="table-toolbar">
          <div><h2>{editingListingId === null ? 'Create an internship listing' : 'Edit internship listing'}</h2><p>{editingListingId === null ? 'Save a draft, then publish it when your company is verified.' : 'Update listing details while preserving its matching tags.'}</p></div>
          <button className="button button-primary button-small" onClick={() => {
            setCreatingListing((open) => !open)
            setListingError('')
            setEditingListingId(null)
            setListingTags({ programme_ids: [], required_skill_ids: [], optional_skill_ids: [], interest_ids: [] })
            setListingForm({ title: '', description: '', sector: '', location: '', duration_weeks: '12', slots: '1', application_deadline: '', is_remote: false })
          }}>
            {creatingListing ? 'Cancel' : 'New listing'}
          </button>
        </div>
        {creatingListing && <form className="auth-form listing-form" onSubmit={(event) => {
          event.preventDefault()
          if (!onSaveListing || savingListing) return
          setListingError('')
          setSavingListing(true)
          void onSaveListing(editingListingId, {
            ...listingForm,
            duration_weeks: Number(listingForm.duration_weeks),
            slots: Number(listingForm.slots),
            ...listingTags,
          }).then(() => {
            setCreatingListing(false)
            setEditingListingId(null)
            setListingForm({ title: '', description: '', sector: '', location: '', duration_weeks: '12', slots: '1', application_deadline: '', is_remote: false })
            setListingTags({ programme_ids: [], required_skill_ids: [], optional_skill_ids: [], interest_ids: [] })
          }).catch((error: unknown) => setListingError(messageFrom(error))).finally(() => setSavingListing(false))
        }}>
          <label>Role title<input value={listingForm.title} onChange={(event) => setListingForm((form) => ({ ...form, title: event.target.value }))} maxLength={150} required /></label>
          <label>Description<textarea value={listingForm.description} onChange={(event) => setListingForm((form) => ({ ...form, description: event.target.value }))} maxLength={10000} rows={4} required /></label>
          <div className="form-grid">
            <label>Sector<input value={listingForm.sector} onChange={(event) => setListingForm((form) => ({ ...form, sector: event.target.value }))} maxLength={100} required /></label>
            <label>Location<input value={listingForm.location} onChange={(event) => setListingForm((form) => ({ ...form, location: event.target.value }))} maxLength={150} required /></label>
            <label>Duration (weeks)<input type="number" min="1" max="52" value={listingForm.duration_weeks} onChange={(event) => setListingForm((form) => ({ ...form, duration_weeks: event.target.value }))} required /></label>
            <label>Positions<input type="number" min="1" max="500" value={listingForm.slots} onChange={(event) => setListingForm((form) => ({ ...form, slots: event.target.value }))} required /></label>
            <label>Application deadline<input type="date" min={new Date().toISOString().slice(0, 10)} value={listingForm.application_deadline} onChange={(event) => setListingForm((form) => ({ ...form, application_deadline: event.target.value }))} required /></label>
            <label className="checkbox-field"><input type="checkbox" checked={listingForm.is_remote} onChange={(event) => setListingForm((form) => ({ ...form, is_remote: event.target.checked }))} /> Remote position</label>
          </div>
          {listingError && <div className="form-error">{listingError}</div>}
          <button className="button button-primary" disabled={savingListing}>{savingListing ? 'Saving…' : editingListingId === null ? 'Save draft' : 'Save changes'} <ArrowRight size={15} /></button>
        </form>}
      </section>}
      {role === 'employer' && page === 'dashboard' && <button className="button button-primary" onClick={() => onPage('listings')}>Manage opportunities <ArrowRight size={15} /></button>}
    </div>
  )
}

function AdminAuditLog({ records }: { records: Record<string, unknown>[] }) {
  return <div className="table-card"><div className="table-toolbar"><div><h2>Recent activity</h2><p>Latest account and registration activity.</p></div></div>{records.length === 0 ? <EmptyState title="No activity records" detail="Activity will appear when the audit API is enabled." /> : <div className="table-scroll"><table><thead><tr><th>Actor</th><th>Action</th><th>Resource</th><th>Result</th><th>Time</th></tr></thead><tbody>{records.map((row, index) => <tr key={index}><td>{String(row.actor_name ?? 'System')}</td><td>{String(row.action ?? '')}</td><td>{String(row.resource_type ?? '')}</td><td>{String(row.result ?? '')}</td><td>{formatDate(String(row.occurred_at ?? ''))}</td></tr>)}</tbody></table></div>}</div>
}

function downloadCsv(filename: string, rows: Record<string, unknown>[], columns: string[]) {
  const escapeCell = (value: unknown) => {
    let text = String(value ?? '')
    if (/^[\s]*[=+\-@]/.test(text)) text = `'${text}`
    return `"${text.replaceAll('"', '""')}"`
  }
  const csv = [columns, ...rows.map((row) => columns.map((column) => row[column]))]
    .map((row) => row.map(escapeCell).join(','))
    .join('\r\n')
  const url = URL.createObjectURL(new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

function EmployerMessages({
  token,
  conversations,
  initialConversation,
  toast,
  onRefresh,
}: {
  token: string
  conversations: Record<string, unknown>[]
  initialConversation: Record<string, unknown> | null
  toast: (message: string) => void
  onRefresh: () => Promise<void>
}) {
  const initialId = initialConversation ? Number(initialConversation.application_id) : null
  const [selectedId, setSelectedId] = useState<number | null>(initialId)
  const [messages, setMessages] = useState<Record<string, unknown>[]>([])
  const [draft, setDraft] = useState('')
  const [loadingThread, setLoadingThread] = useState(false)
  const [sending, setSending] = useState(false)
  const selected = conversations.find((item) => Number(item.application_id) === selectedId)
    ?? (initialId === selectedId ? initialConversation : null)
  const status = String(selected?.application_status ?? selected?.status ?? '')
  const canSend = status === 'shortlisted' || status === 'accepted'

  useEffect(() => {
    if (selectedId === null && conversations.length) {
      setSelectedId(Number(conversations[0].application_id))
    }
  }, [selectedId, conversations])

  useEffect(() => {
    if (selectedId === null) {
      setMessages([])
      return
    }
    let active = true
    setLoadingThread(true)
    employerRequest<Record<string, unknown>[]>('get_thread', token, { application_id: selectedId })
      .then((thread) => { if (active) setMessages(thread) })
      .catch((error: unknown) => { if (active) toast(messageFrom(error)) })
      .finally(() => { if (active) setLoadingThread(false) })
    return () => { active = false }
  }, [selectedId, token, toast])

  async function sendMessage(event: FormEvent) {
    event.preventDefault()
    if (!selectedId || !canSend || !draft.trim() || sending) return
    setSending(true)
    try {
      await employerRequest('send_message', token, { application_id: selectedId, body: draft.trim() })
      setDraft('')
      await onRefresh()
      const thread = await employerRequest<Record<string, unknown>[]>('get_thread', token, { application_id: selectedId })
      setMessages(thread)
    } catch (error) {
      toast(messageFrom(error))
    } finally {
      setSending(false)
    }
  }

  return <div className="page-wrap">
    <PageIntro eyebrow="EMPLOYER SPACE" title="Messages" description="Talk with applicants you have shortlisted or accepted." action={<button className="button button-secondary button-small" onClick={() => void onRefresh()}>Refresh</button>} />
    <div className="conversation-layout">
      <aside className="conversation-list">
        <h2>Conversations</h2>
        {conversations.map((conversation) => {
          const id = Number(conversation.application_id)
          return <button key={id} className={`conversation-item ${selectedId === id ? 'selected' : ''}`} onClick={() => setSelectedId(id)}>
            <strong>{String(conversation.applicant_name ?? 'Applicant')}</strong>
            <span>{String(conversation.listing_title ?? 'Internship')}</span>
            {Number(conversation.unread ?? 0) > 0 && <small>{Number(conversation.unread)} unread</small>}
          </button>
        })}
        {conversations.length === 0 && !initialConversation && <EmptyState title="No conversations yet" detail="Shortlist an applicant, then start a conversation from their application." />}
      </aside>
      <section className="conversation-thread">
        <div className="table-toolbar"><div><h2>{String(selected?.applicant_name ?? 'Select a conversation')}</h2><p>{String(selected?.listing_title ?? 'Shortlisted applicants only')}</p></div></div>
        {loadingThread ? <LoadingState /> : <div className="message-history">
          {messages.length === 0 && <EmptyState title="Start the conversation" detail="Send a message to this shortlisted applicant." />}
          {messages.map((message, index) => <article key={Number(message.message_id ?? index)} className={`message-bubble ${message.mine ? 'mine' : ''}`}>
            <p>{String(message.body ?? '')}</p><small>{formatDate(String(message.sent_at ?? ''))}</small>
          </article>)}
        </div>}
        <form className="message-compose" onSubmit={(event) => void sendMessage(event)}>
          <label className="sr-only" htmlFor="employer-message">Message</label>
          <textarea id="employer-message" rows={3} maxLength={5000} value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={canSend ? 'Write a message…' : 'Messages are available after shortlisting or acceptance.'} disabled={!selected || !canSend} />
          <button className="button button-primary" disabled={!selected || !canSend || !draft.trim() || sending}>{sending ? 'Sending…' : 'Send message'} <ArrowRight size={15} /></button>
        </form>
      </section>
    </div>
  </div>
}

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase()
}

function AuthGate({ onLogin, toast }: { onLogin: (session: LiveSession) => void; toast: string }) {
  const [registering, setRegistering] = useState(false)
  return (
    <div className="auth-page">
      <header className="auth-topbar"><BrandMark /><span className="auth-top-note">Your next opportunity starts here</span></header>
      <main className="auth-layout">
        <section className="auth-story">
          <span className="eyebrow"><span className="eyebrow-dot" /> INTERNSHIPS. OPPORTUNITY. GROWTH.</span>
          <h1>Make your next move<br /><em>count.</em></h1>
          <p>One trusted place to find internships, connect with employers and turn your education into experience.</p>
          <div className="story-points">
            <div><span className="story-check"><Check size={15} /></span><span><b>Made for you</b><small>Personalised internship recommendations</small></span></div>
            <div><span className="story-check"><Check size={15} /></span><span><b>Every step, in view</b><small>Track every application in one place</small></span></div>
            <div><span className="story-check"><Check size={15} /></span><span><b>Trusted connections</b><small>Verified employers and universities</small></span></div>
          </div>
          <div className="auth-story-foot"><ShieldCheck size={16} /> A safer bridge between campus and career.</div>
        </section>
        <section className="auth-card">
          {registering
            ? <RegistrationForm onBack={() => setRegistering(false)} />
            : <LoginForm onRegister={() => setRegistering(true)} onLogin={onLogin} />}
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

function LoginForm({ onRegister, onLogin }: { onRegister: () => void; onLogin: (session: LiveSession) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      const response = await studentApi.login(email, password)
      onLogin({ token: response.access_token, user: response.user })
    } catch (reason) {
      setError(messageFrom(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="auth-card-heading"><span className="auth-icon"><GraduationCap size={20} /></span><span className="tiny-label">INTERNLINK PORTAL</span></div>
      <h2>Welcome back</h2>
      <p className="auth-subtitle">Sign in to continue to your InternLink workspace.</p>
      <form className="auth-form" onSubmit={(event) => void submit(event)}>
        <label>Email address<input type="email" autoComplete="email" placeholder="you@university.ac.ug" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
        <label>Password<input type="password" autoComplete="current-password" placeholder="Enter your password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
        <div className="auth-form-row"><span>Use your registered email address</span><button type="button" className="text-button" onClick={() => setError('Password reset is not configured yet. Contact your administrator.')}>Forgot password?</button></div>
        {error && <div className="form-error">{error}</div>}
        <button className="button button-primary full-button" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'} <ArrowRight size={16} /></button>
      </form>
      <div className="auth-register-line">Student? <button onClick={onRegister}>Create a student account</button></div>
    </>
  )
}

function RegistrationForm({ onBack }: { onBack: () => void }) {
  const [universities, setUniversities] = useState<University[]>([])
  const [departments, setDepartments] = useState<CatalogItem[]>([])
  const [programmes, setProgrammes] = useState<CatalogItem[]>([])
  const [values, setValues] = useState({ full_name: '', email: '', password: '', student_number: '', university_id: '', department_id: '', programme_id: '', year_of_study: '1' })
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    studentApi.universities()
      .then((result) => setUniversities(result.universities))
      .catch((reason: unknown) => setError(messageFrom(reason)))
  }, [])
  useEffect(() => {
    if (!values.university_id) { setDepartments([]); return }
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
    setMessage('')
    try {
      const result = await studentApi.register({
        ...values,
        university_id: Number(values.university_id),
        department_id: Number(values.department_id),
        programme_id: Number(values.programme_id),
        year_of_study: Number(values.year_of_study),
      })
      setMessage(result.message)
    } catch (reason) {
      setError(messageFrom(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button className="back-link" onClick={onBack}><ArrowLeft size={15} /> Back to sign in</button>
      <div className="auth-card-heading"><span className="auth-icon"><GraduationCap size={20} /></span><span className="tiny-label">STUDENT REGISTRATION</span></div>
      <h2>Create your account</h2>
      <p className="auth-subtitle">Register with your university email to get started.</p>
      {message
        ? <div className="success-panel"><CheckCircle2 size={22} /><strong>Check your inbox</strong><p>{message}</p><button className="button button-secondary" onClick={onBack}>Return to sign in</button></div>
        : <form className="auth-form registration-form" onSubmit={(event) => void submit(event)}>
          <label>Full name<input value={values.full_name} onChange={(event) => update('full_name', event.target.value)} required /></label>
          <label>University email<input type="email" placeholder="name@university.ac.ug" value={values.email} onChange={(event) => update('email', event.target.value)} required /></label>
          <label>Student number<input value={values.student_number} onChange={(event) => update('student_number', event.target.value)} required /></label>
          <label>University<select value={values.university_id} onChange={(event) => update('university_id', event.target.value)} required><option value="">Select university</option>{universities.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <div className="form-pair">
            <label>Department<select value={values.department_id} onChange={(event) => update('department_id', event.target.value)} required disabled={!departments.length}><option value="">Select department</option>{departments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
            <label>Programme<select value={values.programme_id} onChange={(event) => update('programme_id', event.target.value)} required disabled={!programmes.length}><option value="">Select programme</option>{programmes.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          </div>
          <label>Year of study<select value={values.year_of_study} onChange={(event) => update('year_of_study', event.target.value)}>{[1, 2, 3, 4, 5, 6].map((year) => <option key={year} value={year}>Year {year}</option>)}</select></label>
          <label>Password<input type="password" autoComplete="new-password" minLength={10} value={values.password} onChange={(event) => update('password', event.target.value)} required /><small>Use at least 10 characters.</small></label>
          {error && <div className="form-error">{error}</div>}
          <button className="button button-primary full-button" disabled={busy || !universities.length}>{busy ? 'Creating account…' : 'Create account'} <ArrowRight size={16} /></button>
          {!universities.length && !error && <small className="helper-text">University options load from the configured InternLink API.</small>}
        </form>}
    </>
  )
}

function StudentWorkspace(props: {
  page: Page; profile: StudentProfile; applications: Application[]; recommendations: Opportunity[]; opportunities: Opportunity[]
  loading: boolean; search: string; setSearch: (value: string) => void; sector: string; setSector: (value: string) => void
  location: string; setLocation: (value: string) => void; duration: string; setDuration: (value: string) => void
  applicationStatus: string; setApplicationStatus: (value: string) => void; notifications: NotificationItem[]
  token: string; onApply: (opportunity: Opportunity) => void
  onSaveProfile: (profile: StudentProfile, skillIds: number[], interestIds: number[]) => void
  onWithdraw: (application: Application) => void; onMarkNotificationRead: (id: number) => void
  toast: (message: string) => void; onBrowse: () => Promise<void>
}) {
  const [activeFilter, setActiveFilter] = useState(false)
  switch (props.page) {
    case 'browse':
      return <BrowsePage {...props} showFilters={activeFilter} onToggleFilters={() => setActiveFilter((value) => !value)} />
    case 'applications':
      return <ApplicationsPage {...props} />
    case 'notifications':
      return <NotificationsPage notifications={props.notifications} onRead={props.onMarkNotificationRead} />
    case 'profile':
      return <ProfilePage profile={props.profile} token={props.token} loading={props.loading} onSave={props.onSaveProfile} />
    default:
      return <StudentDashboard {...props} />
  }
}

function StudentDashboard(props: Pick<StudentWorkspaceProps, 'profile' | 'applications' | 'recommendations' | 'loading' | 'onApply' | 'toast'>) {
  const alreadyApplied = (opportunity: Opportunity) => props.applications.some((application) => application.opportunityId === opportunity.id)
  return (
    <div className="page-wrap">
      <PageIntro eyebrow="YOUR STUDENT SPACE" title={`Good morning, ${props.profile.fullName.split(' ')[0]}`} description="Your next opportunity is closer than you think." />
      <div className="dashboard-welcome">
        <div className="welcome-icon"><Sparkles size={18} /></div>
        <div><strong>Opportunities picked for you</strong><p>Based on your programme, skills and interests.</p></div>
        <span className="welcome-tag">PERSONALISED</span>
      </div>
      {!props.profile.verified && <VerificationNotice />}
      <div className="section-heading">
        <div><h2>Recommended for you <span className="count-pill">{props.recommendations.length}</span></h2><p>Strong matches based on your profile.</p></div>
        <button className="text-button arrow-link" onClick={() => props.toast('Choose Browse internships in the left menu to explore all current openings.')}>Explore all <ArrowRight size={15} /></button>
      </div>
      <div className="opportunity-list">
        {props.loading && <LoadingState />}
        {!props.loading && props.recommendations.length === 0 && <EmptyState title="No recommendations yet" detail="Add skills and interests to your profile, or browse all current internships." />}
        {!props.loading && props.recommendations.map((opportunity) => (
          <OpportunityCard
            key={opportunity.id}
            opportunity={opportunity}
            alreadyApplied={alreadyApplied(opportunity)}
            canApply={props.profile.verified}
            onApply={() => props.onApply(opportunity)}
          />
        ))}
      </div>
      <aside className="profile-nudge">
        <div className="nudge-icon"><GraduationCap size={19} /></div>
        <div className="nudge-copy"><strong>Make your profile work harder</strong><p>Add skills and interests to get recommendations that feel more like you.</p></div>
        <div className="nudge-progress"><span>{props.profile.completeness}% complete</span><div className="progress-track"><span style={{ width: `${props.profile.completeness}%` }} /></div></div>
        <button className="button button-secondary button-small" onClick={() => props.toast('Open My profile from the left menu to update your details.')}>Complete profile <ArrowRight size={14} /></button>
      </aside>
    </div>
  )
}

type StudentWorkspaceProps = Parameters<typeof StudentWorkspace>[0]

function BrowsePage(props: StudentWorkspaceProps & { showFilters: boolean; onToggleFilters: () => void }) {
  const [page, setPage] = useState(1)
  const filtered = useMemo(() => {
    const query = props.search.trim().toLowerCase()
    const list = props.opportunities.filter((opportunity) => {
      const queryMatch = !query || [opportunity.title, opportunity.company, opportunity.sector, opportunity.location, ...opportunity.skills].join(' ').toLowerCase().includes(query)
      const sectorMatch = props.sector === 'All sectors' || opportunity.sector === props.sector
      const locationMatch = props.location === 'All locations' || opportunity.location === props.location
      const durationMatch = props.duration === 'Any duration' ||
        (props.duration === '1–8 weeks' && opportunity.duration <= 8) ||
        (props.duration === '9–16 weeks' && opportunity.duration >= 9 && opportunity.duration <= 16) ||
        (props.duration === '17+ weeks' && opportunity.duration >= 17)
      return queryMatch && sectorMatch && locationMatch && durationMatch
    })
    return list
  }, [props.opportunities, props.search, props.sector, props.location, props.duration])
  const pages = Math.max(1, Math.ceil(filtered.length / 5))
  const shown = filtered.slice((page - 1) * 5, page * 5)

  return (
    <div className="page-wrap">
      <PageIntro eyebrow="FIND YOUR FIT" title="Browse internships" description="Explore verified opportunities from employers across Uganda." />
      <div className="browse-toolbar">
        <label className="search-field"><Search size={17} /><input placeholder="Search role, company or skill…" value={props.search} onChange={(event) => { props.setSearch(event.target.value); setPage(1) }} /><kbd>⌘ K</kbd></label>
        <button className={`button button-secondary filter-toggle ${props.showFilters ? 'selected' : ''}`} onClick={props.onToggleFilters}><SlidersHorizontal size={16} /> Filters <span className="filter-dot" /></button>
      </div>
      {props.showFilters && <div className="filter-panel">
        <label>Sector<select value={props.sector} onChange={(event) => { props.setSector(event.target.value); setPage(1) }}>{['All sectors', 'Software', 'Data', 'Telecommunications', 'Finance', 'Research'].map((item) => <option key={item}>{item}</option>)}</select></label>
        <label>Location<select value={props.location} onChange={(event) => { props.setLocation(event.target.value); setPage(1) }}>{['All locations', 'Kampala', 'Mbarara', 'Mbale'].map((item) => <option key={item}>{item}</option>)}</select></label>
        <label>Duration<select value={props.duration} onChange={(event) => { props.setDuration(event.target.value); setPage(1) }}>{['Any duration', '1–8 weeks', '9–16 weeks', '17+ weeks'].map((item) => <option key={item}>{item}</option>)}</select></label>
        <button className="text-button" onClick={() => { props.setSector('All sectors'); props.setLocation('All locations'); props.setDuration('Any duration') }}>Clear filters</button>
      </div>}
      <div className="results-bar"><span><b>{filtered.length}</b> opportunities found</span><span className="results-sort"><ArrowDownUp size={14} /> Best match</span></div>
      {props.loading && <LoadingState />}
      {!props.loading && shown.length === 0 && <EmptyState title="No opportunities match those filters" detail="Try changing your search or clearing one of the filters." />}
      <div className="opportunity-list">
        {shown.map((opportunity) => (
          <OpportunityCard
            key={opportunity.id}
            opportunity={opportunity}
            alreadyApplied={Boolean(opportunity.appliedStatus) || props.applications.some((application) => application.opportunityId === opportunity.id)}
            canApply={props.profile.verified}
            onApply={() => props.onApply(opportunity)}
          />
        ))}
      </div>
      {pages > 1 && <div className="pagination"><button disabled={page === 1} onClick={() => setPage((value) => value - 1)}>Previous</button><span>Page {page} of {pages}</span><button disabled={page === pages} onClick={() => setPage((value) => value + 1)}>Next</button></div>}
    </div>
  )
}

function OpportunityCard({ opportunity, alreadyApplied, canApply, onApply }: {
  opportunity: Opportunity; alreadyApplied: boolean; canApply: boolean; onApply: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  return (
    <article className="opportunity-card">
      <div className="company-avatar">{opportunity.company.slice(0, 1)}</div>
      <div className="opportunity-main">
        <div className="opportunity-overline">{opportunity.sector} <span>·</span> {opportunity.company}</div>
        <h3>{opportunity.title}</h3>
        <div className="opportunity-meta"><span><MapPin size={14} />{opportunity.remote ? 'Remote' : opportunity.location}</span><span><Clock3 size={14} />{opportunity.duration} weeks</span><span>{opportunity.slots} {opportunity.slots === 1 ? 'position' : 'positions'}</span></div>
        <div className="skill-tags">{opportunity.skills.slice(0, 4).map((skill) => <span key={skill}>{skill}</span>)}</div>
        {expanded && <p className="opportunity-description">{opportunity.description}</p>}
        <button className="details-link" onClick={() => setExpanded((value) => !value)}>{expanded ? 'Hide details' : 'View details'} <ChevronRight className={expanded ? 'rotate-icon' : ''} size={14} /></button>
      </div>
      <div className="opportunity-actions">
        <div className="match-box"><strong>{opportunity.match}%</strong><span>match</span></div>
        <button className={`button ${alreadyApplied ? 'button-applied' : 'button-primary'} button-small`} disabled={alreadyApplied || !canApply} onClick={onApply}>
          {alreadyApplied ? <><Check size={14} /> Applied</> : canApply ? 'Apply now' : 'Verify profile'}
        </button>
        <span className="deadline">Closes {formatDate(opportunity.deadline)}</span>
      </div>
    </article>
  )
}

function ApplicationsPage(props: StudentWorkspaceProps) {
  const rows = props.applications.filter((application) => props.applicationStatus === 'All statuses' || application.status.toLowerCase().replaceAll('_', ' ') === props.applicationStatus.toLowerCase())
  const statusOptions = ['All statuses', 'Submitted', 'Under review', 'Shortlisted', 'Accepted', 'Rejected', 'Withdrawn']
  return (
    <div className="page-wrap">
      <PageIntro eyebrow="KEEP TRACK" title="My applications" description="Every application, every update — all in one place." />
      <div className="stats-strip">
        <MiniStat label="Total sent" value={props.applications.length} />
        <MiniStat label="In review" value={props.applications.filter((item) => ['submitted', 'under_review'].includes(item.status)).length} />
        <MiniStat label="Shortlisted" value={props.applications.filter((item) => item.status === 'shortlisted').length} />
        <MiniStat label="Offers" value={props.applications.filter((item) => item.status === 'accepted').length} />
      </div>
      <div className="table-card">
        <div className="table-toolbar"><div><h2>Application history</h2><p>See the latest status from every employer.</p></div><label className="select-with-icon"><Filter size={14} /><select value={props.applicationStatus} onChange={(event) => props.setApplicationStatus(event.target.value)}>{statusOptions.map((item) => <option key={item}>{item}</option>)}</select></label></div>
        {rows.length === 0 ? <EmptyState title="No applications here yet" detail="When you apply to an internship, it will appear here." /> : <div className="table-scroll"><table><thead><tr><th>Opportunity</th><th>Employer</th><th>Applied</th><th>Match</th><th>Status</th><th /></tr></thead><tbody>
          {rows.map((application) => <tr key={application.id}><td><strong>{application.title}</strong><small>{application.location}</small></td><td>{application.company}</td><td>{formatDate(application.submitted)}</td><td><span className="table-match">{application.match}%</span></td><td><StatusBadge status={application.status} /></td><td>{!['withdrawn', 'rejected'].includes(application.status) && <button className="table-action" onClick={() => props.onWithdraw(application)}>Withdraw</button>}</td></tr>)}
        </tbody></table></div>}
      </div>
    </div>
  )
}

function NotificationsPage({ notifications, onRead }: { notifications: NotificationItem[]; onRead: (id: number) => void }) {
  return (
    <div className="page-wrap">
      <PageIntro eyebrow="STAY IN THE LOOP" title="Notifications" description="Important updates about your applications and opportunities." />
      <div className="notification-list">
        {notifications.length === 0 && <EmptyState title="You’re all caught up" detail="New updates will appear here." />}
        {notifications.map((item) => <article className={`notification-card ${item.read ? 'read' : ''}`} key={item.id}><span className="notification-icon"><Bell size={17} /></span><div><h3>{item.title}</h3><p>{item.message}</p><small>{item.time}</small></div>{!item.read && <button className="mark-read" onClick={() => onRead(item.id)}>Mark read</button>}</article>)}
      </div>
    </div>
  )
}

function ProfilePage({ profile, token, loading, onSave }: {
  profile: StudentProfile; token: string; loading: boolean
  onSave: (profile: StudentProfile, skillIds: number[], interestIds: number[]) => void
}) {
  const [form, setForm] = useState(profile)
  const [skillCatalog, setSkillCatalog] = useState<CatalogItem[]>([])
  const [interestCatalog, setInterestCatalog] = useState<CatalogItem[]>([])
  const [skillIds, setSkillIds] = useState<number[]>([])
  const [interestIds, setInterestIds] = useState<number[]>([])
  const [catalogError, setCatalogError] = useState('')
  useEffect(() => setForm(profile), [profile])
  useEffect(() => {
    studentApi.catalogs()
      .then((result) => {
        setSkillCatalog(result.skills)
        setInterestCatalog(result.interests)
        setSkillIds(result.skills.filter((item) => profile.skills.includes(item.name)).map((item) => item.id))
        setInterestIds(result.interests.filter((item) => profile.interests.includes(item.name)).map((item) => item.id))
      })
      .catch((error: unknown) => setCatalogError(messageFrom(error)))
  }, [token, profile.skills.join(','), profile.interests.join(',')])

  const selectedSkills = skillCatalog.filter((item) => skillIds.includes(item.id)).map((item) => item.name)
  const selectedInterests = interestCatalog.filter((item) => interestIds.includes(item.id)).map((item) => item.name)
  const toggleItem = (item: CatalogItem, type: 'skill' | 'interest') => {
    const setIds = type === 'skill' ? setSkillIds : setInterestIds
    const currentIds = type === 'skill' ? skillIds : interestIds
    setIds(currentIds.includes(item.id) ? currentIds.filter((value) => value !== item.id) : [...currentIds, item.id])
  }

  return (
    <div className="page-wrap">
      <PageIntro eyebrow="YOUR PROFILE" title="Tell your story" description="A complete profile helps employers and our matching engine see your potential." />
      <div className="profile-layout">
        <section className="profile-form-card">
          <div className="profile-card-top"><div className="large-avatar">{initials(profile.fullName)}</div><div><h2>{profile.fullName}</h2><p>{profile.programme} · Year {profile.year}</p></div><span className={`verification-pill ${profile.verified ? 'verified' : ''}`}>{profile.verified ? <><CheckCircle2 size={14} /> Verified</> : <><Clock3 size={14} /> Awaiting verification</>}</span></div>
          <div className="form-divider" />
          <div className="profile-section-title"><div><h3>Personal details</h3><p>Some information is managed by your university.</p></div></div>
          <div className="profile-fields">
            <label>Full name<input value={form.fullName} disabled /></label>
            <label>University email<input value={form.email} disabled /></label>
            <label>University<input value={form.university} disabled /></label>
            <label>Student number<input value={form.studentNumber} disabled /></label>
            <label>Programme<input value={form.programme} disabled /></label>
            <label>Year of study<select value={form.year} onChange={(event) => setForm((current) => ({ ...current, year: Number(event.target.value) }))}>{[1, 2, 3, 4, 5, 6].map((year) => <option key={year} value={year}>Year {year}</option>)}</select></label>
            <label>Preferred internship location<input value={form.location} placeholder="e.g. Kampala" onChange={(event) => setForm((current) => ({ ...current, location: event.target.value }))} /></label>
          </div>
          <label className="checkbox-row"><input type="checkbox" checked={form.relocate} onChange={(event) => setForm((current) => ({ ...current, relocate: event.target.checked }))} /><span>I am willing to relocate for the right opportunity.</span></label>
          <div className="form-divider" />
          <div className="profile-section-title"><div><h3>Your skills</h3><p>Pick the skills you can bring to an internship.</p></div><span className="selection-count">{selectedSkills.length} selected</span></div>
          <div className="choice-chips">{skillCatalog.map((item) => <button key={item.id} className={`choice-chip ${selectedSkills.includes(item.name) ? 'chosen' : ''}`} onClick={() => toggleItem(item, 'skill')}>{selectedSkills.includes(item.name) && <Check size={13} />}{item.name}</button>)}</div>
          <div className="profile-section-title interests-title"><div><h3>What interests you?</h3><p>We'll use these to personalise your matches.</p></div><span className="selection-count">{selectedInterests.length} selected</span></div>
          <div className="choice-chips">{interestCatalog.map((item) => <button key={item.id} className={`choice-chip ${selectedInterests.includes(item.name) ? 'chosen' : ''}`} onClick={() => toggleItem(item, 'interest')}>{selectedInterests.includes(item.name) && <Check size={13} />}{item.name}</button>)}</div>
          {catalogError && <p className="form-error">{catalogError}</p>}
          <div className="profile-save-row"><span><ShieldCheck size={15} /> Your profile is only shared with relevant employers.</span><button className="button button-primary" disabled={loading} onClick={() => onSave({ ...form, skills: selectedSkills, interests: selectedInterests }, skillIds, interestIds)}>{loading ? 'Saving…' : 'Save changes'} <ArrowRight size={15} /></button></div>
        </section>
        <aside className="profile-side">
          <div className="completion-card"><div className="completion-heading"><div><span className="tiny-label">PROFILE STRENGTH</span><strong>{profile.completeness}%</strong></div><span className="completion-ring">{profile.completeness}%</span></div><div className="progress-track"><span style={{ width: `${profile.completeness}%` }} /></div><p>{profile.completeness >= 80 ? 'You’re looking good. Keep your details current.' : 'A stronger profile helps us find better matches.'}</p><ul><li className="complete"><CheckCircle2 size={15} /> Personal details</li><li className={selectedSkills.length ? 'complete' : ''}><CheckCircle2 size={15} /> Skills</li><li className={selectedInterests.length ? 'complete' : ''}><CheckCircle2 size={15} /> Interests</li><li><FileText size={15} /> CV upload not connected yet</li></ul></div>
          <div className="verify-card"><div><ShieldCheck size={18} /><strong>University verification</strong></div><p>{profile.verified ? 'Your university has confirmed your student profile.' : 'A university coordinator needs to verify your student details before applications can be submitted.'}</p><span className={`verify-status ${profile.verified ? 'is-verified' : ''}`}><span />{profile.verified ? 'Verified student' : 'Pending review'}</span></div>
          <div className="privacy-note"><ShieldCheck size={15} /><span>Your personal details remain private. Employers see your profile when you apply.</span></div>
        </aside>
      </div>
    </div>
  )
}

function OpportunityDialog({ opportunity, apply, canApply, loading, onClose, onApply, onStartApply }: {
  opportunity: Opportunity; apply: boolean; canApply: boolean; loading: boolean; onClose: () => void
  onApply: (note: string) => void; onStartApply: () => void
}) {
  const [note, setNote] = useState('')
  return (
    <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <section className="modal-card opportunity-modal">
        <button className="modal-close icon-button" onClick={onClose} aria-label="Close"><X size={19} /></button>
        <div className="modal-company"><div className="company-avatar large">{opportunity.company.slice(0, 1)}</div><div><span className="opportunity-overline">{opportunity.sector} · Verified employer</span><h2>{opportunity.title}</h2><p>{opportunity.company}</p></div></div>
        <div className="modal-facts"><span><MapPin size={15} />{opportunity.remote ? 'Remote / Hybrid' : opportunity.location}</span><span><Clock3 size={15} />{opportunity.duration} weeks</span><span><BriefcaseBusiness size={15} />{opportunity.slots} open positions</span><span className="modal-match"><Sparkles size={15} />{opportunity.match}% match</span></div>
        <div className="modal-description"><h3>About this opportunity</h3><p>{opportunity.description}</p><h3>Skills employers are looking for</h3><div className="skill-tags">{opportunity.skills.map((skill) => <span key={skill}>{skill}</span>)}</div><p className="modal-deadline">Applications close {formatDate(opportunity.deadline)}.</p></div>
        {apply ? <div className="apply-section"><label>Introduce yourself <span>Optional</span><textarea rows={4} maxLength={2000} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Why are you interested in this opportunity?" /></label>{!canApply && <div className="form-error">A university coordinator must verify your profile before you can apply.</div>}<button className="button button-primary full-button" disabled={loading || !canApply} onClick={() => onApply(note)}>{loading ? 'Submitting…' : 'Submit application'} <ArrowRight size={15} /></button></div>
          : <div className="modal-bottom"><span><ShieldCheck size={15} /> Applications require a verified student profile.</span><button className="button button-primary" disabled={!canApply} onClick={onStartApply}>{canApply ? 'Apply for this internship' : 'Awaiting verification'} <ArrowRight size={15} /></button></div>}
      </section>
    </div>
  )
}

function PageIntro({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <div className="page-intro"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{action}</div>
}

function MiniStat({ label, value, icon }: { label: string; value: string | number; icon?: ReactNode }) {
  return <div className="mini-stat">{icon && <span className="mini-stat-icon">{icon}</span>}<div><span>{label}</span><strong>{value}</strong></div></div>
}

function MetricCard({ number, label, detail, icon, color }: { number: string; label: string; detail?: string; icon: ReactNode; color: string }) {
  return <div className={`metric-card ${color}`}><div className="metric-top"><span className="metric-icon">{icon}</span><span className="metric-trend"><ArrowRight size={13} /></span></div><strong>{number}</strong><span className="metric-label">{label}</span>{detail && <small>{detail}</small>}</div>
}

function StatusBadge({ status }: { status: string }) {
  const label = status.replaceAll('_', ' ')
  const cssStatus = status.toLowerCase().replaceAll(' ', '-').replaceAll('_', '-')
  return <span className={`status-badge status-${cssStatus}`}><i />{label}</span>
}

function VerificationNotice() {
  return <div className="verification-notice"><Clock3 size={17} /><div><strong>Profile verification pending</strong><p>You can explore and save opportunities. Your university must verify your profile before you can apply.</p></div><span className="status-badge status-pending"><i />Pending</span></div>
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><span><Search size={19} /></span><strong>{title}</strong><p>{detail}</p></div>
}

function LoadingState() {
  return <div className="loading-state"><span className="spinner" /> Loading your InternLink data…</div>
}

function formatDate(value: string) {
  if (!value) return 'soon'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('en-UG', { day: 'numeric', month: 'short', year: 'numeric' }).format(date)
}

export default App
