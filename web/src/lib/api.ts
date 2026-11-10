/**
 * Typed client for the MeetingOS backend.
 *
 * Every shape here mirrors a Pydantic response model in
 * `backend/routes/meetings.py`. Keeping the fetch calls in one module means
 * the base URL and the error convention are decided once, not per component.
 */

const BASE = import.meta.env.VITE_API_URL ?? '';

export type MeetingStatus = 'processing' | 'analyzing' | 'completed' | 'failed' | 'queued' | string;

export type VerificationStatus =
  | 'verified'
  | 'low_confidence'
  | 'unsupported'
  | 'unverified'
  | string;

export interface MeetingSummary {
  id: string;
  org_id: string;
  title: string;
  status: MeetingStatus;
  source: string;
  visibility: string;
  language: string | null;
  scheduled_start: string | null;
  actual_start: string | null;
  actual_end: string | null;
  audio_duration_seconds: number | null;
  created_at: string | null;
}

export interface MeetingDetail extends MeetingSummary {
  description: string | null;
  summary: string | null;
  sentiment_score: number | null;
  processing_error: string | null;
  consent_confirmed_at: string | null;
  consent_note: string | null;
  updated_at: string | null;
}

export interface ExtractedItem {
  id: string;
  title: string;
  description: string | null;
  status: string | null;
  severity: string | null;
  priority: string | null;
  source_segment_id: string | null;
  source_segment_text: string | null;
  source_start_ms: number | null;
  source_end_ms: number | null;
  extraction_confidence: number | null;
  verification_status: VerificationStatus;
  verification_score: number | null;
  /** Set when this decision supersedes an earlier one — shown as "revisited". */
  supersedes_id: string | null;
}

export interface Topic {
  id: string;
  label: string;
  start_ms: number | null;
  end_ms: number | null;
  salience: number | null;
  keywords: string[];
}

export interface MeetingIntelligence {
  meeting_id: string;
  meeting_status: MeetingStatus;
  topics: Topic[];
  decisions: ExtractedItem[];
  action_items: ExtractedItem[];
  risks: ExtractedItem[];
  commitments: ExtractedItem[];
}

export interface StatLink {
  path: string;
  query: Record<string, string>;
}

export interface Stat {
  label: string;
  value: number;
  link: StatLink;
  tone: 'neutral' | 'good' | 'warn' | 'destructive';
}

export interface PersonActivity {
  person_id: string;
  name: string | null;
  meetings: number;
  decisions: number;
  commitments: number;
  total: number;
  link: StatLink;
}

export interface RiskSummary {
  id: string;
  title: string;
  severity: string | null;
  meeting_id: string | null;
  meeting_title: string | null;
  evidence_id: string | null;
  start_ms: number | null;
  verification_status: string | null;
}

export interface ExtractionQuality {
  total_items: number;
  verified: number;
  low_confidence: number;
  unsupported: number;
  unverified: number;
  /** Null when nothing has been extracted — a rate over zero items is not a rate. */
  verified_rate: number | null;
  mean_confidence: number | null;
  has_unverified: boolean;
  link: StatLink;
}

export interface Dashboard {
  org_id: string;
  period_days: number;
  period_start: string;
  meetings_in_period: number;
  decisions_approved: Stat;
  decisions_pending: Stat;
  decisions_reversed: Stat;
  overdue_commitments: Stat;
  open_risks: Stat;
  top_risks: RiskSummary[];
  most_active_people: PersonActivity[];
  extraction_quality: ExtractionQuality;
}

export interface CommitmentItem {
  id: string;
  kind: string;
  text: string;
  status: string;
  owner_id: string | null;
  owner_name: string | null;
  due_date: string | null;
  overdue: boolean;
  days_overdue: number | null;
  meeting_id: string | null;
  meeting_title: string | null;
  evidence_id: string | null;
  verification_status: string | null;
  start_ms: number | null;
}

export interface CommitmentList {
  items: CommitmentItem[];
  total: number;
  overdue_count: number;
}

export interface ProviderInfo {
  name: string;
  role: string;
  model: string | null;
  endpoint_host: string | null;
  is_cloud: boolean;
  configured: boolean;
  is_default: boolean;
}
export interface RuleInfo {
  name: string;
  category: string;
  description: string;
  enabled: boolean;
}
export interface RedactionInfo {
  enabled: boolean;
  source: string;
  rules: RuleInfo[];
  categories: string[];
  limitations: string[];
}
export interface DataResidencyInfo {
  data_dir: string;
  database: string;
  recordings_dir: string;
  documents_dir: string;
  single_tenant: boolean;
  allowed_inference_hosts: string[];
  notes: string[];
}
export interface AuditEntry {
  id: string;
  created_at: string | null;
  provider: string;
  model: string | null;
  operation: string;
  endpoint_host: string | null;
  is_cloud: boolean;
  characters_sent: number | null;
  items_sent: number | null;
  redaction_enabled: boolean;
  redactions_applied: number;
  succeeded: boolean;
  error: string | null;
  meeting_id: string | null;
}
export interface AuditSummary {
  total_calls: number;
  cloud_calls: number;
  local_calls: number;
  failed_calls: number;
  characters_sent: number;
  calls_without_redaction: number;
  distinct_hosts: string[];
}
export interface Privacy {
  providers: ProviderInfo[];
  redaction: RedactionInfo;
  residency: DataResidencyInfo;
  audit_summary: AuditSummary;
  recent_calls: AuditEntry[];
}

export interface Citation {
  segment_id: string;
  start_ms: number;
  end_ms: number;
  speaker_label: string | null;
  text: string;
}

export interface AskResponse {
  meeting_id: string;
  question: string;
  answer: string;
  citations: Citation[];
  /** The transcript does not cover the question. An honest refusal, not a failure. */
  not_discussed: boolean;
  /** The answer asserted something but cited nothing valid. Never show as fact. */
  unsupported: boolean;
  segments_considered: number;
  segments_retrieved: number;
}

export interface TranscriptSegment {
  id: string;
  sequence: number;
  start_ms: number;
  end_ms: number;
  speaker_label: string | null;
  text: string;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** Fired on any 401 so the app can drop back to the sign-in screen. */
export const UNAUTHORIZED_EVENT = 'meetingos:unauthorized';

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    credentials: 'same-origin',
    ...init,
    headers: { Accept: 'application/json', ...init.headers },
  });
  if (response.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  if (!response.ok) {
    // The backend returns {"detail": "..."}; fall back to the status line when
    // something else answers (a proxy error page, say).
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      /* keep statusText */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const get = <T>(path: string) => request<T>(path);
const sendJson = <T>(method: string, path: string, body: unknown) =>
  request<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

export interface Session {
  auth_required: boolean;
  authenticated: boolean;
}

export interface Minutes {
  meeting_id: string;
  line_count: number;
  cited_line_count: number;
  markdown: string;
  summary: string | null;
}

export const api = {
  getSession: () => get<Session>('/api/session'),
  login: (apiKey: string) => sendJson<void>('POST', '/api/session', { api_key: apiKey }),
  logout: () => request<void>('/api/session', { method: 'DELETE' }),

  listMeetings: () => get<MeetingSummary[]>('/api/meetings'),
  getMeeting: (id: string) => get<MeetingDetail>(`/api/meetings/${id}`),
  getIntelligence: (id: string) => get<MeetingIntelligence>(`/api/meetings/${id}/intelligence`),
  getTranscript: (id: string) => get<TranscriptSegment[]>(`/api/meetings/${id}/transcript`),
  audioUrl: (id: string) => `${BASE}/api/meetings/${id}/audio`,
  getDashboard: (periodDays = 90) => get<Dashboard>(`/api/dashboard?period_days=${periodDays}`),
  getPrivacy: () => get<Privacy>('/api/privacy'),
  updateRedaction: (enabled: boolean, rules: string[]) =>
    sendJson<RedactionInfo>('PUT', '/api/privacy/redaction', { enabled, rules }),
  listCommitments: (params: Record<string, string> = {}) =>
    get<CommitmentList>(`/api/commitments?${new URLSearchParams(params)}`),
  // Deterministic minutes; `summarise` adds an LLM paragraph written only from them.
  getMinutes: (id: string, summarise: boolean, language: string) =>
    request<Minutes>(
      `/api/meetings/${id}/minutes?${new URLSearchParams({ summarise: String(summarise), language })}`,
      { method: 'POST' },
    ),
  ask: (id: string, question: string) =>
    sendJson<AskResponse>('POST', `/api/meetings/${id}/ask`, { question }),

  uploadMeeting(
    file: File,
    title: string,
    consentNote: string,
    language: string | null = null,
  ): Promise<MeetingDetail> {
    const form = new FormData();
    form.append('file', file);
    form.append('title', title);
    form.append('consent_confirmed', 'true');
    if (consentNote.trim()) form.append('consent_note', consentNote.trim());
    if (language) form.append('language', language);
    return request<MeetingDetail>('/api/meetings/upload', { method: 'POST', body: form });
  },
};
