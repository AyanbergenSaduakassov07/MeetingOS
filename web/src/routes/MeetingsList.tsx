import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle, Loader2, Upload } from 'lucide-react';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { ConsentDialog } from '@/components/ConsentDialog';
import { api } from '@/lib/api';
import { formatTimestamp } from '@/lib/playback';
import { cn } from '@/lib/utils';

const STATUS_STYLES: Record<string, string> = {
  completed: 'bg-good-tint text-good',
  processing: 'bg-warn-tint text-warn',
  analyzing: 'bg-warn-tint text-warn',
  queued: 'bg-warn-tint text-warn',
  failed: 'bg-destructive/10 text-destructive',
};

export function MeetingsList() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);

  const meetings = useQuery({ queryKey: ['meetings'], queryFn: api.listMeetings });

  const upload = useMutation({
    mutationFn: ({ file, note, language }: { file: File; note: string; language: string | null }) =>
      api.uploadMeeting(file, file.name.replace(/\.[^.]+$/, ''), note, language),
    onSuccess: async (meeting) => {
      setUploadError(null);
      await queryClient.invalidateQueries({ queryKey: ['meetings'] });
      navigate(`/meetings/${meeting.id}`);
    },
    onError: (error) =>
      setUploadError(error instanceof Error ? error.message : t('common.unknownError')),
  });

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="font-display text-3xl font-black tracking-tight">{t('meetings.title')}</h1>

        <div>
          <input
            ref={fileRef}
            type="file"
            accept="audio/*,.wav,.mp3,.m4a,.ogg,.flac,.webm"
            className="sr-only"
            data-testid="upload-input"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) setPendingFile(file);
              event.target.value = '';
            }}
          />
          <button
            type="button"
            data-testid="upload-button"
            disabled={upload.isPending}
            onClick={() => fileRef.current?.click()}
            className="inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground transition-opacity duration-150 hover:opacity-90 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            {upload.isPending ? (
              <Loader2 aria-hidden="true" className="size-4 animate-spin" />
            ) : (
              <Upload aria-hidden="true" className="size-4" />
            )}
            {upload.isPending ? t('meetings.uploading') : t('nav.upload')}
          </button>
        </div>
      </div>

      <ConsentDialog
        file={pendingFile}
        onCancel={() => setPendingFile(null)}
        onConfirm={(file, note, language) => {
          setPendingFile(null);
          upload.mutate({ file, note, language });
        }}
      />

      {uploadError && (
        <p
          role="alert"
          data-testid="upload-error"
          className="mt-4 flex items-center gap-2 rounded-md bg-destructive/10 px-4 py-3 text-sm text-destructive"
        >
          <AlertCircle aria-hidden="true" className="size-4 shrink-0" />
          {uploadError}
        </p>
      )}

      {meetings.isLoading && (
        <p className="mt-8 text-sm text-muted-foreground">{t('common.loading')}</p>
      )}

      {meetings.isError && (
        <p role="alert" className="mt-8 text-sm text-destructive">
          {t('meetings.loadFailed')}
        </p>
      )}

      {meetings.data?.length === 0 && (
        <div className="mt-12 rounded-lg border border-dashed border-border p-10 text-center">
          <p className="font-medium">{t('meetings.empty')}</p>
          <p className="mt-1 text-sm text-muted-foreground">{t('meetings.emptyHint')}</p>
        </div>
      )}

      <ul className="mt-6 space-y-2" data-testid="meeting-list">
        {(meetings.data ?? []).map((meeting) => (
          <li key={meeting.id}>
            <Link
              to={`/meetings/${meeting.id}`}
              data-testid="meeting-row"
              className="flex min-h-16 items-center gap-4 rounded-lg border border-border bg-card px-4 py-3 transition-colors duration-150 hover:border-muted-foreground/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <div className="min-w-0 flex-1">
                {/* Meeting title is content — not routed through i18n. */}
                <p className="truncate font-medium">{meeting.title}</p>
                <p className="mt-0.5 font-mono text-xs tabular-nums text-muted-foreground">
                  {meeting.created_at
                    ? new Date(meeting.created_at).toLocaleDateString(i18n.language)
                    : '—'}
                  {' · '}
                  {meeting.audio_duration_seconds == null
                    ? '—'
                    : formatTimestamp(meeting.audio_duration_seconds * 1000)}
                </p>
              </div>
              <span
                className={cn(
                  'shrink-0 rounded-full px-2.5 py-1 text-xs font-medium',
                  STATUS_STYLES[meeting.status] ?? 'bg-muted text-muted-foreground',
                )}
              >
                {t(`status.${meeting.status}`, meeting.status)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
