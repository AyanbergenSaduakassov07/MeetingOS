import { useMutation } from '@tanstack/react-query';
import { Check, Copy, Download, FileText, Loader2, Sparkles } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { languageName } from '@/i18n';
import { api, type MinuteLine, type Minutes } from '@/lib/api';
import { CitationTime } from './CitationTime';
import { Button } from './ui/button';
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from './ui/dialog';

// shortcut: mirrors backend SPOKEN_LANGUAGES (routes/meetings.py); other choices get English minutes until the backend allowlist widens
export const MINUTES_LANGUAGES = new Set([
  'en',
  'ru',
  'kk',
  'uz',
  'ky',
  'tr',
  'uk',
  'de',
  'fr',
  'es',
  'zh',
  'ar',
]);

/**
 * The executive summary is written only from the
 * extracted, cited items, so it cannot add a decision nobody made.
 */
export function SummaryPanel({
  meetingId,
  savedSummary,
  language,
}: {
  meetingId: string;
  savedSummary: string | null;
  language: string;
}) {
  const { t } = useTranslation();
  const summary = useMutation({
    mutationFn: () => api.getMinutes(meetingId, true, language),
  });
  const body = summary.data?.summary ?? savedSummary;

  return (
    <div className="space-y-2" data-testid="summary-panel">
      {body && (
        <p className="whitespace-pre-wrap text-sm leading-relaxed" data-testid="summary-text">
          {body}
        </p>
      )}
      {!summary.data?.summary && (
        <>
          <p className="text-sm text-muted-foreground">
            {summary.isSuccess
              ? t('summary.nothing')
              : summary.isError
                ? t('summary.failed')
                : body
                  ? null
                  : t('summary.hint')}
          </p>
          <Button
            type="button"
            size="sm"
            data-testid="summary-generate"
            className="rounded-md"
            onClick={() => summary.mutate()}
            disabled={summary.isPending}
          >
            {summary.isPending ? (
              <Loader2 aria-hidden="true" className="size-4 animate-spin" />
            ) : (
              <Sparkles aria-hidden="true" className="size-4" />
            )}
            {summary.isPending ? t('summary.generating') : t('summary.generate')}
          </Button>
        </>
      )}
    </div>
  );
}

const MINUTE_HEADINGS: Record<string, string> = {
  Resolutions: 'record.resolutions',
  Deferred: 'record.deferred',
  Actions: 'tabs.actions',
  'Risks noted': 'tabs.risks',
  'Undertakings given': 'tabs.commitments',
};

function MinutesLines({ lines }: { lines: MinuteLine[] }) {
  return (
    <ul className="list-disc space-y-2 pl-5">
      {lines.map((line, index) => (
        <li key={`${line.evidence_id ?? line.text}-${index}`}>
          {line.text}
          {line.start_ms !== null && <CitationTime ms={line.start_ms} />}
          {line.detail && <p className="text-muted-foreground">{line.detail}</p>}
        </li>
      ))}
    </ul>
  );
}

function MinutesPreview({ title, minutes }: { title: string; minutes: Minutes }) {
  const { t } = useTranslation();
  return (
    <article className="min-h-0 space-y-4 overflow-y-auto rounded-md border border-border bg-card p-4 font-serif leading-relaxed">
      <h3 className="break-words font-serif text-xl">{title}</h3>
      {minutes.sections.map(({ heading, lines }) => (
        <section key={heading}>
          <h4 className="font-semibold">
            {MINUTE_HEADINGS[heading] ? t(MINUTE_HEADINGS[heading]) : heading}
          </h4>
          <MinutesLines lines={lines} />
        </section>
      ))}
      {minutes.uncited.length > 0 && (
        <section>
          <h4 className="font-semibold text-warn">{t('record.uncited')}</h4>
          <MinutesLines lines={minutes.uncited} />
        </section>
      )}
      {minutes.line_count === 0 && <p className="text-muted-foreground">{t('summary.nothing')}</p>}
    </article>
  );
}

export function MinutesDialog({
  title,
  minutes,
  hasError,
  isOpen,
  onOpenChange,
  language,
  onLanguageChange,
}: {
  title: string;
  minutes: Minutes | undefined;
  hasError: boolean;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  language: string;
  onLanguageChange: (language: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const copy = useMutation({
    mutationFn: (markdown: string) => navigator.clipboard.writeText(markdown),
  });

  const download = (markdown: string) => {
    const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown' }));
    Object.assign(document.createElement('a'), { href: url, download: `${title}.md` }).click();
    URL.revokeObjectURL(url);
  };

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) copy.reset();
        onOpenChange(open);
      }}
    >
      <DialogTrigger asChild>
        <Button type="button" size="sm" variant="outline" className="rounded-md">
          <FileText aria-hidden="true" />
          {t('record.minutes')}
        </Button>
      </DialogTrigger>
      <DialogContent
        className="flex max-h-[85dvh] max-w-xl flex-col rounded-lg"
        aria-describedby={undefined}
      >
        <DialogTitle>{t('record.minutes')}</DialogTitle>
        <label className="flex flex-wrap items-center gap-2 text-sm">
          {t('record.summaryLanguage')}
          <select
            className="rounded-md border border-input bg-card px-2 py-1 capitalize"
            value={language}
            onChange={(event) => onLanguageChange(event.target.value)}
          >
            {[...MINUTES_LANGUAGES].map((code) => (
              <option key={code} value={code}>
                {languageName(code, i18n.language)}
              </option>
            ))}
          </select>
        </label>
        {minutes ? (
          <>
            <MinutesPreview title={title} minutes={minutes} />
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="rounded-md"
                onClick={() => copy.mutate(minutes.markdown)}
              >
                {copy.isSuccess ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                {t(copy.isSuccess ? 'summary.copied' : 'summary.copy')}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="rounded-md"
                onClick={() => download(minutes.markdown)}
              >
                <Download aria-hidden="true" />
                {t('summary.download')}
              </Button>
            </div>
            {copy.isError && (
              <p role="alert" className="text-sm text-destructive">
                {t('record.copyFailed')}
              </p>
            )}
          </>
        ) : (
          <output className="text-sm text-muted-foreground">
            {t(hasError ? 'record.minutesFailed' : 'common.loading')}
          </output>
        )}
      </DialogContent>
    </Dialog>
  );
}
