import { useQueries, useQuery } from '@tanstack/react-query';
import { api, type MeetingIntelligence, type MeetingSummary } from '@/lib/api';

const DAY_MS = 86_400_000;

export interface OrgIntelligence {
  meetings: MeetingSummary[];
  intelligence: Array<{ meeting: MeetingSummary; data: MeetingIntelligence }>;
  failedCount: number;
  isLoading: boolean;
  isError: boolean;
  retry: () => void;
}

/** Meetings created within the last `periodDays` (all of them when null). */
export function meetingsInPeriod(
  meetings: MeetingSummary[],
  periodDays: number | null,
  now = Date.now(),
): MeetingSummary[] {
  if (periodDays === null) return meetings;
  const cutoff = now - periodDays * DAY_MS;
  return meetings.filter((m) => m.created_at !== null && Date.parse(m.created_at) >= cutoff);
}

/**
 * Extracted items across every meeting in the period, mirroring the window
 * the dashboard counts over (meeting created_at >= now - period_days).
 *
 * shortcut: N+1 intelligence fetches per page, add list endpoints when orgs exceed ~50 meetings
 */
export function useOrgIntelligence(periodDays: number | null): OrgIntelligence {
  const list = useQuery({ queryKey: ['meetings'], queryFn: api.listMeetings });
  const meetings = meetingsInPeriod(list.data ?? [], periodDays);

  const results = useQueries({
    queries: meetings.map((meeting) => ({
      queryKey: ['register-intelligence', meeting.id],
      queryFn: () => api.getIntelligence(meeting.id),
    })),
  });

  const intelligence = meetings.flatMap((meeting, i) => {
    const data = results[i]?.data;
    return data ? [{ meeting, data }] : [];
  });

  return {
    meetings,
    intelligence,
    failedCount: results.filter((r) => r.isError).length,
    isLoading: list.isLoading || results.some((r) => r.isLoading),
    isError: list.isError,
    retry: () => void list.refetch(),
  };
}
