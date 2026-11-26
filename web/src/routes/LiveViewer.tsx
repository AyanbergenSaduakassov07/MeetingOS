import { Maximize } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useSearchParams } from 'react-router-dom';
import { LanguageToggle } from '@/components/LanguageToggle';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { type Caption, useLiveCaptions, viewerUrl } from '@/lib/live';
import { CaptionList, LanguagePicker, ORIGINAL, useLiveLanguages } from './LiveCaptions';
import { QrCode } from './LiveQr';

const PRESENT_LINES = 3;

/** Guest page opened from a viewer link. Lives outside AuthGate: the token is the credential. */
export function LiveViewer() {
  const { t } = useTranslation();
  const { sessionId = '' } = useParams();
  const [params] = useSearchParams();
  const token = params.get('t');
  const [lang, setLang] = useState(params.get('lang') || ORIGINAL);
  const languages = useLiveLanguages().data ?? [];
  const target = lang === ORIGINAL ? null : lang;
  const live = useLiveCaptions(sessionId, token, target);

  if (params.get('view') === 'present' && live.state !== 'error') {
    return (
      <Presenter
        captions={live.captions}
        partial={live.partial}
        lang={target}
        joinUrl={token ? viewerUrl(sessionId, token) : null}
        state={live.state}
      />
    );
  }
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

/** Big-screen view for a projector or shared screen: last few lines, large type, QR to join. */
function Presenter({
  captions,
  partial,
  lang,
  joinUrl,
  state,
}: {
  captions: Caption[];
  partial: string;
  lang: string | null;
  joinUrl: string | null;
  state: string;
}) {
  const { t } = useTranslation();
  const lines = captions.slice(-PRESENT_LINES).map((c) => {
    const translated = lang && c.language !== lang && c.translation;
    return { id: c.segment_id, text: translated || c.text };
  });
  return (
    <div className="relative flex min-h-dvh flex-col justify-end bg-black p-12 text-white">
      <div aria-live="polite" className="max-w-6xl space-y-6 text-4xl leading-snug md:text-5xl">
        {lines.length === 0 && !partial && <p className="text-white/50">{t('live.waiting')}</p>}
        {lines.map((l, i) => (
          <p key={l.id} className={i < lines.length - 1 ? 'text-white/60' : ''}>
            {l.text}
          </p>
        ))}
        {partial && !lang && <p className="text-white/50 italic">{partial}</p>}
      </div>
      <div className="absolute top-6 right-6 flex items-start gap-4">
        <span className="text-sm text-white/70">{t(`live.state.${state}`)}</span>
        <Button
          size="sm"
          variant="secondary"
          aria-label={t('live.fullscreen')}
          onClick={() => document.documentElement.requestFullscreen?.()}
        >
          <Maximize aria-hidden="true" className="size-4" />
        </Button>
        {joinUrl && (
          <figure className="text-center text-xs text-white/70">
            <QrCode value={joinUrl} label={t('live.qrLabel')} className="size-32 rounded" />
            <figcaption className="mt-1">{t('live.scanToJoin')}</figcaption>
          </figure>
        )}
      </div>
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
