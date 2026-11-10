import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FileText, Loader2, Lock, Upload } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '@/lib/api';

const ACCEPT = '.pdf,.txt,.md,.docx,.pptx';

/** Documents the org copilot can search beside meetings: contracts, decks, agendas. */
export function Library() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [sensitive, setSensitive] = useState(false);

  const documents = useQuery({ queryKey: ['documents'], queryFn: api.listDocuments });
  const upload = useMutation({
    mutationFn: () => api.uploadDocument(file as File, title.trim(), sensitive),
    onSuccess: () => {
      setFile(null);
      setTitle('');
      setSensitive(false);
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
  });

  return (
    <div className="mx-auto max-w-4xl px-6 py-8" data-testid="library">
      <h1 className="font-display text-3xl font-black tracking-tight">{t('library.title')}</h1>
      <p className="mt-1 text-sm text-muted-foreground">{t('library.subtitle')}</p>

      <form
        className="mt-6 flex flex-wrap items-end gap-3 rounded-lg border border-border bg-card p-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (file && title.trim()) upload.mutate();
        }}
      >
        <label className="flex min-w-48 flex-1 flex-col gap-1 text-sm">
          <span className="font-medium">{t('library.file')}</span>
          <input
            type="file"
            accept={ACCEPT}
            data-testid="library-file"
            className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-secondary file:px-3 file:py-1.5 file:text-sm"
            onChange={(event) => {
              const picked = event.target.files?.[0] ?? null;
              setFile(picked);
              if (picked && !title) setTitle(picked.name.replace(/\.[^.]+$/, ''));
            }}
          />
        </label>
        <label className="flex min-w-48 flex-1 flex-col gap-1 text-sm">
          <span className="font-medium">{t('library.docTitle')}</span>
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            maxLength={300}
            className="rounded-md border border-border bg-background px-3 py-1.5 outline-none focus:border-primary"
          />
        </label>
        <label className="flex items-center gap-2 pb-1.5 text-sm">
          <input
            type="checkbox"
            checked={sensitive}
            onChange={(event) => setSensitive(event.target.checked)}
          />
          {t('library.sensitive')}
        </label>
        <button
          type="submit"
          data-testid="library-upload"
          disabled={!file || !title.trim() || upload.isPending}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
        >
          {upload.isPending ? (
            <Loader2 aria-hidden="true" className="size-4 animate-spin" />
          ) : (
            <Upload aria-hidden="true" className="size-4" />
          )}
          {t('library.upload')}
        </button>
        <p className="w-full text-xs text-muted-foreground">{t('library.allowed')}</p>
        {upload.isError && (
          <p role="alert" className="w-full text-sm text-destructive">
            {upload.error.message}
          </p>
        )}
        {upload.data && !upload.data.indexed && (
          <p className="w-full text-sm text-warn">{t('library.notIndexed')}</p>
        )}
      </form>

      {documents.isLoading ? (
        <p className="mt-8 flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 aria-hidden="true" className="size-4 animate-spin" />
          {t('common.loading')}
        </p>
      ) : documents.isError ? (
        <p role="alert" className="mt-8 text-sm text-destructive">
          {documents.error.message}
        </p>
      ) : documents.data?.length ? (
        <ul className="mt-6 space-y-2" data-testid="library-list">
          {documents.data.map((doc) => (
            <li
              key={doc.id}
              className="flex items-center gap-3 rounded-lg border border-border bg-card px-4 py-3"
            >
              <FileText aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
              {/* Document titles are content, not chrome — never translated. */}
              <span className="min-w-0 flex-1 truncate text-sm font-medium">{doc.title}</span>
              {doc.is_sensitive && (
                <Lock aria-label={t('library.sensitive')} className="size-3.5 text-warn" />
              )}
              <span className="font-mono text-xs tabular-nums text-muted-foreground">
                {doc.size_bytes ? `${Math.ceil(doc.size_bytes / 1024)} KB` : '—'}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-8 text-sm text-muted-foreground">{t('library.empty')}</p>
      )}
    </div>
  );
}
