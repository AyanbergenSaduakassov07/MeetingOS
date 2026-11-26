import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useSearchParams } from 'react-router-dom';
import { LanguageToggle } from '@/components/LanguageToggle';
import { Label } from '@/components/ui/label';
import { useLiveCaptions } from '@/lib/live';
import { CaptionList, LanguagePicker, ORIGINAL, useLiveLanguages } from './LiveCaptions';

/** Guest page opened from a viewer link. Lives outside AuthGate: the token is the credential. */
export function LiveViewer() {
  const { t } = useTranslation();
  const { sessionId = '' } = useParams();
  const [params] = useSearchParams();
  const token = params.get('t');
  const [lang, setLang] = useState(ORIGINAL);
  const languages = useLiveLanguages().data ?? [];
  const target = lang === ORIGINAL ? null : lang;
  const live = useLiveCaptions(sessionId, token, target);

  return (
    <div className="min-h-dvh bg-background text-foreground">
      <header className="sticky top-0 z-10 flex flex-wrap items-center gap-4 border-b border-border bg-card px-6 py-3">
        <h1 className="mr-auto text-lg font-semibold">{live.title || t('live.title')}</h1>
        <StatusBadge state={live.state} />
        <div className="flex items-center gap-2">
          <Label htmlFor="viewer-lang">{t('live.captionLanguage')}</Label>
          <LanguagePicker id="viewer-lang" value={lang} onChange={setLang} languages={languages} />
        </div>
        <LanguageToggle />
      </header>
      <main className="mx-auto max-w-3xl px-6 py-8">
        {live.state === 'error' ? (
          <p role="alert" className="py-12 text-center text-destructive">
            {live.error ?? t('live.linkInvalid')}
          </p>
        ) : (
          <CaptionList
            captions={live.captions}
            partial={live.partial}
            lang={target}
            languages={languages}
          />
        )}
      </main>
    </div>
  );
}

export function StatusBadge({ state }: { state: string }) {
  const { t } = useTranslation();
  const tone =
    state === 'live' ? 'bg-red-500' : state === 'ended' ? 'bg-muted-foreground' : 'bg-amber-500';
  return (
    <span className="flex items-center gap-2 text-sm text-muted-foreground">
      <span aria-hidden="true" className={`size-2 rounded-full ${tone}`} />
      {t(`live.state.${state}`)}
    </span>
  );
}
