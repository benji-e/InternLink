export type Role = 'student' | 'employer' | 'university' | 'admin'
export type Page = 'dashboard' | 'browse' | 'applications' | 'notifications' | 'profile' | 'applicants' | 'students' | 'approvals' | 'users' | 'listings' | 'messages' | 'reports' | 'catalog' | 'placed' | 'applicant' | 'verify'

export type Opportunity = {
  id: number
  title: string
  company: string
  sector: string
  location: string
  remote: boolean
  duration: number
  deadline: string
  slots: number
  description: string
  skills: string[]
  match: number
  appliedStatus?: string | null
}

export type Application = {
  id: number
  opportunityId: number
  title: string
  company: string
  location: string
  submitted: string
  status: string
  match: number
  unread: number
  placementStatus: string | null
  interviewAt: string | null
  interviewNote: string | null
  decisionNote: string | null
}

export type StudentProfile = {
  fullName: string
  email: string
  university: string
  programme: string
  year: number
  studentNumber: string
  location: string
  relocate: boolean
  verified: boolean
  skills: string[]
  interests: string[]
  completeness: number
}
