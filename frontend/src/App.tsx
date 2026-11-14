import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import {
  ArrowRight, Bell, Check, CheckCircle2, Clock3, FileText, GraduationCap, Plus, Search, ShieldCheck, Users,
} from 'lucide-react'
import { ApiError, employerRequest, roleApi, savedApi, studentApi, type SavedItem, type AuthUser, type CatalogItem, type CoordinatorCatalog } from './api'
import { AcceptInvitePage, AuthGate, isAuthLinkPath } from './AuthPages'
import { HomePage, InternshipDetailPage, InternshipsPage } from './PublicSite'
import { CvCard, SavedPage, StudentApplications, StudentHome, StudentShell, type StudentPage } from './StudentPages'
import {
  AdminRequests, CoordinatorApprovals, CoordinatorOverview, CoordinatorStudents, CoordinatorVerify,
  AdminUniversities, CoordinatorTeamPage, EmployerApplicant, EmployerBoard, OrgShell, PlacedInterns, type OrgNavItem,
} from './OrgPages'
import { navigate, useLocation } from './router'
import type { Application, Opportunity, Page, Role, StudentProfile } from './types'
import './App.css'

type LiveUser = AuthUser
type LiveSession = { token: string; user: LiveUser }
type NotificationItem = { id: number; title: string; message: string; time: string; read: boolean }

const SESSION_KEY = 'internlink-student-session'

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
  hasCv: false,
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
    appliedStatus: typeof row.application_status === 'string' ? row.application_status : row.applied ? 'applied' : null,
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
    unread: Number(row.unread_messages ?? 0),
    placementStatus: typeof row.placement_status === 'string' ? row.placement_status : null,
    interviewAt: typeof row.interview_at === 'string' ? row.interview_at : null,
    interviewNote: typeof row.interview_note === 'string' ? row.interview_note : null,
    decisionNote: typeof row.decision_note === 'string' ? row.decision_note : null,
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
    hasCv: Boolean(row.has_cv),
  }
}

function App() {
  // Links from our emails (confirm, reset password) open the sign-in screens even if signed in.
  const restoredSession = useMemo(() => (isAuthLinkPath() ? null : readSession()), [])
  const { path, search: urlSearch } = useLocation()
  const [recommendationsError, setRecommendationsError] = useState('')
  const [savedItems, setSavedItems] = useState<SavedItem[]>([])
  const [role, setRole] = useState<Role | null>(restoredSession?.user.role ?? null)
  const [page, setPage] = useState<Page>('dashboard')
  const [session, setSession] = useState<LiveSession | null>(restoredSession)
  const [profile, setProfile] = useState<StudentProfile>(emptyProfile)
  const [liveRecommendations, setLiveRecommendations] = useState<Opportunity[]>([])
  const [liveApplications, setLiveApplications] = useState<Application[]>([])
  const [liveNotifications, setLiveNotifications] = useState<NotificationItem[]>([])
  const [loading, setLoading] = useState(false)
  const [toast, setToast] = useState('')
  const [selectedListingId, setSelectedListingId] = useState<number | null>(null)
  const [selectedApplicant, setSelectedApplicant] = useState<{ id: number; order: number[] } | null>(null)
  const [employerDashboard, setEmployerDashboard] = useState<Record<string, unknown> | null>(null)
  const [employerListings, setEmployerListings] = useState<Record<string, unknown>[]>([])
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
    if (!session) return
    if (session.user.role === 'student') void loadLiveStudent(session)
    else void loadLiveRole(session)
  }, [session])

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
        // Open the board on a live internship when there is one.
        const first = listings.find((item) => item.status === 'open') ?? listings[0]
        if (first && selectedListingId === null) setSelectedListingId(Number(first.listing_id))
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
        studentApi.recommendations(active.token).catch((error: unknown) => {
          if (error instanceof ApiError && error.status === 401) throw error
          return { results: [], error: messageFrom(error) }
        }),
        studentApi.applications(active.token),
        studentApi.notifications(active.token),
      ])
      setProfile(mapProfile(profileResult.profile))
      setLiveRecommendations(recommendationResult.results.map(mapOpportunity))
      setRecommendationsError('error' in recommendationResult ? String(recommendationResult.error) : '')
      void loadSaved(active)
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

  async function loadSaved(active: LiveSession) {
    try {
      setSavedItems((await savedApi.list(active.token)).saved)
    } catch {
      setSavedItems([])
    }
  }

  function signOut() {
    localStorage.removeItem(SESSION_KEY)
    navigate('/')
    setSession(null)
    setRole(null)
    setPage('dashboard')
    setSelectedListingId(null)
    setLiveRecommendations([])
    setLiveApplications([])
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
    const next = new URLSearchParams(window.location.search).get('next')
    navigate(next && next.startsWith('/') && !next.startsWith('//') ? next : '/dashboard', { replace: true })
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

  // Redirects happen after render: signed-out visitors go to sign-in, signed-in users skip it.
  const signedIn = Boolean(session && role)
  const isPublicPath = path === '/' || path === '/internships' || path === '/accept-invite' || /^\/internships\/\d+$/.test(path)
  const isAuthPath = path === '/signin' || path === '/signup' || isAuthLinkPath(path)
  const redirect = !signedIn && !isPublicPath && !isAuthPath ? `/signin?next=${encodeURIComponent(path + urlSearch)}`
    : signedIn && (path === '/signin' || path === '/signup') ? '/dashboard' : null
  useEffect(() => {
    if (redirect) navigate(redirect, { replace: true })
  }, [redirect])
  if (redirect) return null

  // Public pages work signed in or out.
  const siteSession = session && role ? session : null
  if (path === '/') return <HomePage session={siteSession} />
  if (path === '/accept-invite') return <AcceptInvitePage search={urlSearch} />
  if (path === '/internships') return <InternshipsPage session={siteSession} search={urlSearch} />
  const detailMatch = /^\/internships\/(\d+)$/.exec(path)
  if (detailMatch) return <InternshipDetailPage session={siteSession} id={Number(detailMatch[1])} onApplied={() => session && void loadLiveStudent(session)} />

  if (!role || !session) return <AuthGate path={path} search={urlSearch} onLogin={handleLogin} />

  if (role === 'student') {
    const studentPage = (new URLSearchParams(urlSearch).get('page') ?? 'home') as StudentPage
    const goStudent = (next: StudentPage) => navigate(next === 'home' ? '/dashboard' : `/dashboard?page=${next}`)
    const unreadMessages = liveApplications.reduce((total, item) => total + item.unread, 0)
    return (
      <StudentShell page={studentPage} name={session.user.full_name} unreadAlerts={liveNotifications.filter((item) => !item.read).length}
        unreadMessages={unreadMessages} savedCount={savedItems.length} onPage={goStudent} onSignOut={signOut}>
        {studentPage === 'applications' ? <StudentApplications token={session.token} applications={liveApplications} onWithdraw={(item) => void withdrawApplication(item)} onRead={() => void loadLiveStudent(session)} />
          : studentPage === 'notifications' ? <div className="legacy-panel"><NotificationsPage notifications={liveNotifications} onRead={(id) => void markNotificationRead(id)} /></div>
            : studentPage === 'saved' ? <SavedPage session={siteSession} saved={savedItems} onChange={() => void loadSaved(session)} />
            : studentPage === 'profile' ? <><CvCard token={session.token} onChange={() => void loadLiveStudent(session)} /><div className="legacy-panel"><ProfilePage profile={profile} token={session.token} loading={loading} onSave={saveProfile} /></div></>
              : <StudentHome session={siteSession} profile={profile} applications={liveApplications} recommendations={liveRecommendations} recommendationsError={recommendationsError} saved={savedItems} loading={loading} onPage={goStudent} onSavedChange={() => void loadSaved(session)} />}
        {toast && <div className="toast-s" role="status">{toast}</div>}
      </StudentShell>
    )
  }

  function changePage(next: Page) {
    setPage(next)
  }

  const pageToast = toast && <div className="toast-s" role="status">{toast}</div>

  if (role === 'employer') {
    const unread = employerConversations.reduce((total, item) => total + Number(item.unread ?? 0), 0)
    const navPage = page === 'applicant' ? 'applicants' : page
    return (
      <OrgShell suffix="for employers" page={navPage} onPage={changePage} name={session.user.full_name} onSignOut={signOut}
        nav={[
          { page: 'dashboard', label: 'Overview' },
          { page: 'listings', label: 'Internship listings' },
          { page: 'applicants', label: 'Applicants' },
          { page: 'messages', label: 'Messages', count: unread },
          { page: 'placed', label: 'Placed interns' },
        ] as OrgNavItem<Page>[]}
        action={<button className="btn btn-primary btn-sm" onClick={() => changePage('listings')}>Post an internship</button>}>
        {page === 'applicants' && <EmployerBoard token={session.token} listings={employerListings} listingId={selectedListingId} onListing={setSelectedListingId}
          onOpen={(id, order) => { setSelectedApplicant({ id, order }); setPage('applicant') }} toast={setToast} />}
        {page === 'applicant' && selectedApplicant && <EmployerApplicant token={session.token} applicationId={selectedApplicant.id} order={selectedApplicant.order}
          onOpen={(id) => setSelectedApplicant((current) => current && { ...current, id })} onBack={() => { setPage('applicants'); void loadLiveRole(session) }}
          onMessage={(row) => { setSelectedMessageConversation(row); setPage('messages') }} toast={setToast} />}
        {page === 'placed' && <PlacedInterns token={session.token} />}
        {page === 'messages' && <div className="legacy-panel">
            <EmployerMessages token={session.token} conversations={employerConversations} initialConversation={selectedMessageConversation} toast={setToast} onRefresh={() => loadLiveRole(session)} />
        </div>}
        {(page === 'dashboard' || page === 'listings') && <div className="legacy-panel">
            <LiveRoleWorkspace role="employer" page={page} loading={roleLoading} data={employerDashboard} records={employerListings} onPage={changePage} onRefresh={() => session && void loadLiveRole(session)} onSelectListing={(id) => { setSelectedListingId(id); setPage('applicants') }} onMessage={(row) => { setSelectedMessageConversation(row); setPage('messages') }} onLoadListing={async (id) => {
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
        </div>}
        {pageToast}
      </OrgShell>
    )
  }

  if (role === 'university') {
    const coordinator = { stats: coordinatorStats, students: coordinatorStudents, placements: coordinatorPlacements }
    const reload = () => void loadLiveRole(session)
    const waiting = coordinatorStudents.filter((row) => !row.verified).length
    return (
      <OrgShell suffix="universities" page={page} onPage={changePage} name={session.user.full_name} onSignOut={signOut}
        nav={[
          { page: 'dashboard', label: 'Overview' },
          { page: 'verify', label: 'Verify students', count: waiting },
          { page: 'approvals', label: 'Placement approvals', count: coordinatorPlacements.length },
          { page: 'students', label: 'All students' },
          { page: 'reports', label: 'Reports' },
          { page: 'catalog', label: 'Departments & programmes' },
          { page: 'team', label: 'Coordinators' },
        ] as OrgNavItem<Page>[]}>
        {roleLoading && !coordinatorStats ? <div className="card empty">Loading…</div>
          : page === 'verify' ? <CoordinatorVerify token={session.token} data={coordinator} onReload={reload} toast={setToast} />
            : page === 'approvals' ? <CoordinatorApprovals token={session.token} data={coordinator} onReload={reload} toast={setToast} />
              : page === 'students' ? <CoordinatorStudents data={coordinator} />
                : page === 'reports' ? <CoordinatorStudents data={coordinator} reports />
                  : page === 'catalog' ? <div className="legacy-panel"><CoordinatorCatalogPage token={session.token} onPage={changePage} toast={setToast} /></div>
                  : page === 'team' ? <CoordinatorTeamPage token={session.token} toast={setToast} />
                    : <CoordinatorOverview token={session.token} data={coordinator} onReload={reload} toast={setToast} onPage={changePage} />}
        {pageToast}
      </OrgShell>
    )
  }

  return (
    <OrgShell suffix="admin" page={page} onPage={changePage} name={session.user.full_name} onSignOut={signOut}
      nav={[
        { page: 'approvals', label: 'Organisation requests', count: adminRegistrations.length },
        { page: 'universities', label: 'Universities' },
        { page: 'users', label: 'Users' },
        { page: 'reports', label: 'Activity log' },
      ] as OrgNavItem<Page>[]}>
      {page === 'approvals' ? <AdminRequests token={session.token} registrations={adminRegistrations} onReload={() => void loadLiveRole(session)} toast={setToast} />
        : page === 'universities' ? <AdminUniversities token={session.token} toast={setToast} />
        : <div className="legacy-panel">
            <LiveRoleWorkspace role="admin" page={page} loading={roleLoading} data={null} records={page === 'users' ? adminUsers : page === 'reports' ? adminAudit : adminRegistrations} onPage={changePage} onRefresh={() => session && void loadLiveRole(session)} onAction={async (id, action, type) => {
              if (!session) return
              try {
                if (page === 'users') await roleApi.updateUser(session.token, id, action === 'Verify' ? 'active' : 'suspended')
                else await roleApi.decideRegistration(session.token, type ?? 'company', id, action === 'Verify' ? 'verified' : 'rejected', action === 'Reject' ? 'Rejected by platform administrator' : undefined)
                await loadLiveRole(session)
              } catch (error) { setToast(messageFrom(error)) }
            }} />
        </div>}
      {pageToast}
    </OrgShell>
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
        <button onClick={() => onPage('catalog')}>Departments &amp; programmes</button>
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

function CoordinatorCatalogPage({ token, onPage, toast }: { token: string; onPage: (page: Page) => void; toast: (message: string) => void }) {
  const [catalog, setCatalog] = useState<CoordinatorCatalog | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [departmentName, setDepartmentName] = useState('')
  const [programme, setProgramme] = useState({ department_id: '', name: '', programme_group: '' })

  async function load() {
    try {
      setCatalog(await roleApi.coordinatorCatalog(token))
    } catch (loadError) {
      setError(messageFrom(loadError))
    }
  }

  useEffect(() => { void load() }, [token])

  async function submit(action: () => Promise<unknown>, done: string, reset: () => void) {
    setBusy(true)
    setError('')
    try {
      await action()
      reset()
      await load()
      toast(done)
    } catch (submitError) {
      setError(messageFrom(submitError))
    } finally {
      setBusy(false)
    }
  }

  const departments = catalog?.departments ?? []
  const readyCount = departments.filter((department) => department.programmes.length > 0).length

  return (
    <div className="page-wrap">
      <PageIntro
        eyebrow="UNIVERSITY COORDINATOR"
        title="Departments & programmes"
        description="Students choose from this list when they create an account. A department needs at least one programme before students can pick it."
        action={<div className="page-actions"><button className="button button-secondary button-small" onClick={() => onPage('dashboard')}>Back to overview</button></div>}
      />
      {catalog && departments.length === 0 && <div className="form-error" role="status">Your university has no departments yet, so students can't sign up. Add a department and a programme below.</div>}
      {error && <div className="form-error" role="alert">{error}</div>}
      <div className="table-card">
        <div className="table-toolbar"><div><h2>Current catalog</h2><p>{catalog ? `${departments.length} department${departments.length === 1 ? '' : 's'}, ${readyCount} open for student sign-up.` : 'Loading…'}</p></div></div>
        {!catalog ? <LoadingState /> : departments.length === 0 ? <EmptyState title="No departments yet" detail="Add your first department below." /> : <div className="table-scroll"><table><thead><tr><th>Department</th><th>Programmes</th></tr></thead><tbody>
          {departments.map((department) => <tr key={department.id}>
            <td>{department.name}</td>
            <td>{department.programmes.length === 0 ? <span className="status-badge status-pending"><i />No programmes yet</span> : department.programmes.map((item) => `${item.name} (${item.programme_group.replaceAll('_', ' ')})`).join(', ')}</td>
          </tr>)}
        </tbody></table></div>}
      </div>
      {catalog?.can_add_departments && <section className="table-card listing-create-card">
        <div className="table-toolbar"><div><h2>Add a department</h2><p>For example “Computer Science” or “Accounting and Finance”.</p></div></div>
        <form className="auth-form listing-form" onSubmit={(event) => {
          event.preventDefault()
          const name = departmentName.trim()
          void submit(() => roleApi.addDepartment(token, name), `${name} added.`, () => setDepartmentName(''))
        }}>
          <label>Department name<input value={departmentName} onChange={(event) => setDepartmentName(event.target.value)} maxLength={160} required /></label>
          <button className="button button-primary" disabled={busy}><Plus size={15} /> Add department</button>
        </form>
      </section>}
      {catalog && departments.length > 0 && <section className="table-card listing-create-card">
        <div className="table-toolbar"><div><h2>Add a programme</h2><p>The group lets matching treat related programmes, such as all computing degrees, as a partial fit.</p></div></div>
        <form className="auth-form listing-form" onSubmit={(event) => {
          event.preventDefault()
          const name = programme.name.trim()
          void submit(
            () => roleApi.addProgramme(token, Number(programme.department_id), name, programme.programme_group),
            `${name} added.`,
            () => setProgramme((current) => ({ ...current, name: '' })),
          )
        }}>
          <div className="form-grid">
            <label>Department<select value={programme.department_id} onChange={(event) => setProgramme((current) => ({ ...current, department_id: event.target.value }))} required><option value="">Select department</option>{departments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></label>
            <label>Programme group<select value={programme.programme_group} onChange={(event) => setProgramme((current) => ({ ...current, programme_group: event.target.value }))} required><option value="">Select group</option>{catalog.programme_groups.map((group) => <option key={group} value={group}>{group.replaceAll('_', ' ')}</option>)}</select></label>
          </div>
          <label>Programme name<input value={programme.name} onChange={(event) => setProgramme((current) => ({ ...current, name: event.target.value }))} maxLength={160} placeholder="e.g. BSc Computer Science" required /></label>
          <button className="button button-primary" disabled={busy}><Plus size={15} /> Add programme</button>
        </form>
      </section>}
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
          <div className="completion-card"><div className="completion-heading"><div><span className="tiny-label">PROFILE STRENGTH</span><strong>{profile.completeness}%</strong></div><span className="completion-ring">{profile.completeness}%</span></div><div className="progress-track"><span style={{ width: `${profile.completeness}%` }} /></div><p>{profile.completeness >= 80 ? 'You’re looking good. Keep your details current.' : 'A stronger profile helps us find better matches.'}</p><ul><li className="complete"><CheckCircle2 size={15} /> Personal details</li><li className={selectedSkills.length ? 'complete' : ''}><CheckCircle2 size={15} /> Skills</li><li className={selectedInterests.length ? 'complete' : ''}><CheckCircle2 size={15} /> Interests</li><li className={profile.hasCv ? 'complete' : ''}><FileText size={15} /> {profile.hasCv ? 'CV uploaded' : 'CV (upload it above)'}</li></ul></div>
          <div className="verify-card"><div><ShieldCheck size={18} /><strong>University verification</strong></div><p>{profile.verified ? 'Your university has confirmed your student profile.' : 'A university coordinator needs to verify your student details before applications can be submitted.'}</p><span className={`verify-status ${profile.verified ? 'is-verified' : ''}`}><span />{profile.verified ? 'Verified student' : 'Pending review'}</span></div>
          <div className="privacy-note"><ShieldCheck size={15} /><span>Your personal details remain private. Employers see your profile when you apply.</span></div>
        </aside>
      </div>
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
