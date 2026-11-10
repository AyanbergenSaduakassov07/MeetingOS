import { useMutation } from '@tanstack/react-query';
import { Check, Copy, Download, Loader2, Sparkles } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '@/lib/api';

/**
 * Executive summary + minutes export. The summary is written only from the
 * extracted, cited items, so it cannot add a decision nobody made.
 */
export function SummaryPanel({ meetingId, title }: { meetingId: string; title: string }) {
  const { t, i18n } = useTranslation();
  const [copied, setCopied] = useState(false);
  const language = i18n.language.slice(0, 2);

  const summary = useMutation({
    mutationFn: () => api.getMinutes(meetingId, true, language),
  });
  const minutes = useMutation({
    mutationFn: () => api.getMinutes(meetingId, false, language),
  });

  const download = async () => {
    const { markdown } = await minutes.mutateAsync();
    const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown' }));
    const link = Object.assign(document.createElement('a'), { href: url, download: `${title}.md` });
    link.click();
    URL.revokeObjectURL(url);
  };

  const copy = async () => {
    const { markdown } = await minutes.mutateAsync();
    await navigator.clipboard.writeText(markdown);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const buttonClass =
    'inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium hover:bg-secondary disabled:opacity-50';

  return (
    <section
      className="mt-6 rounded-lg border border-border bg-card p-4"
      data-testid="summary-panel"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-sm font-bold">{t('summary.title')}</h2>
        <div className="flex gap-2">
          <button type="button" className={buttonClass} onClick={copy} disabled={minutes.isPending}>
            {copied ? (
              <Check aria-hidden="true" className="size-4" />
            ) : (
              <Copy aria-hidden="true" className="size-4" />
            )}
            {copied ? t('summary.copied') : t('summary.copy')}
          </button>
          <button
            type="button"
            className={buttonClass}
            onClick={download}
            disabled={minutes.isPending}
          >
            <Download aria-hidden="true" className="size-4" />
            {t('summary.download')}
          </button>
        </div>
      </div>

      {summary.data?.summary ? (
        <p className="mt-3 text-sm leading-relaxed" data-testid="summary-text">
          {summary.data.summary}
        </p>
      ) : (
        <div className="mt-3 space-y-2">
          <p className="text-sm text-muted-foreground">
            {summary.isSuccess
              ? t('summary.nothing')
              : summary.isError
                ? t('summary.failed')
                : t('summary.hint')}
          </p>
          <button
            type="button"
            data-testid="summary-generate"
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
            onClick={() => summary.mutate()}
            disabled={summary.isPending}
          >
            {summary.isPending ? (
              <Loader2 aria-hidden="true" className="size-4 animate-spin" />
            ) : (
              <Sparkles aria-hidden="true" className="size-4" />
            )}
            {summary.isPending ? t('summary.generating') : t('summary.generate')}
          </button>
        </div>
      )}
    </section>
  );
}
