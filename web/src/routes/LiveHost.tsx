import { useMutation } from '@tanstack/react-query';
import { Copy, Mic, MonitorUp, Presentation, Square } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useToast } from '@/components/ui/use-toast';
import { liveApi, type StartedSession, startCapture, useLiveCaptions, viewerUrl } from '@/lib/live';
import { CaptionList, LanguagePicker, ORIGINAL, useLiveLanguages } from './LiveCaptions';
import { QrCode } from './LiveQr';
import { StatusBadge } from './LiveViewer';

type Source = 'mic' | 'tab';

export function LiveHost() {
  const [session, setSession] = useState<StartedSession | null>(null);
  const [ended, setEnded] = useState<string | null>(null);
  if (ended) return <Ended meetingId={ended} onAgain={() => setEnded(null)} />;
  if (!session) return <StartForm onStarted={setSession} />;
  return (
    <Running
      session={session}
      onEnded={(meetingId) => {
        setSession(null);
        setEnded(meetingId);
      }}
    />
  );
}

function StartForm({ onStarted }: { onStarted: (s: StartedSession) => void }) {
  const { t } = useTranslation();
  const languages = useLiveLanguages().data ?? [];
  const [title, setTitle] = useState('');
  const [source, setSource] = useState<Source>('mic');
  const [lang, setLang] = useState(ORIGINAL);
  const [consent, setConsent] = useState(false);
  const start = useMutation({
    mutationFn: async () => {
      const s = await liveApi.start({
        title: title.trim(),
        consent_confirmed: consent,
        source_language: lang === ORIGINAL ? undefined : lang,
      });
      return { ...s, source };
    },
    onSuccess: onStarted,
  });

  return (
    <div className="mx-auto max-w-xl px-4 py-8 sm:px-6">
      <h1 className="mb-2 font-display text-2xl font-semibold">{t('live.title')}</h1>
      <p className="mb-6 text-muted-foreground">{t('live.intro')}</p>
      <Card className="space-y-5 p-4 sm:p-6">
        <div className="space-y-1.5">
          <Label htmlFor="live-title">{t('live.meetingTitle')}</Label>
          <Input
            id="live-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={200}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="live-source-lang">{t('live.spokenLanguage')}</Label>
          <LanguagePicker
            id="live-source-lang"
            value={lang}
            onChange={setLang}
            languages={languages}
            originalLabel={t('live.detectLanguage')}
          />
          <p className="text-xs text-muted-foreground">{t('live.spokenLanguageHint')}</p>
        </div>
        <fieldset className="space-y-1.5">
          <legend className="text-sm font-medium">{t('live.audioSource')}</legend>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              aria-pressed={source === 'mic'}
              variant={source === 'mic' ? 'default' : 'outline'}
              onClick={() => setSource('mic')}
            >
              <Mic aria-hidden="true" className="mr-2 size-4" />
              {t('live.microphone')}
            </Button>
            <Button
              type="button"
              aria-pressed={source === 'tab'}
              variant={source === 'tab' ? 'default' : 'outline'}
              onClick={() => setSource('tab')}
            >
              <MonitorUp aria-hidden="true" className="mr-2 size-4" />
              {t('live.browserTab')}
            </Button>
          </div>
        </fieldset>
        <div className="flex items-start gap-3">
          <Checkbox id="live-consent" checked={consent} onCheckedChange={setConsent} />
          <Label htmlFor="live-consent" className="leading-snug">
            {t('live.consent')}
          </Label>
        </div>
        {start.error && (
          <p role="alert" className="text-sm text-destructive">
            {start.error.message}
          </p>
        )}
        <Button
          disabled={!title.trim() || !consent || start.isPending}
          onClick={() => start.mutate()}
        >
          {start.isPending ? t('common.loading') : t('live.start')}
        </Button>
      </Card>
    </div>
  );
}

function Running({
  session,
  onEnded,
}: {
  session: StartedSession & { source?: Source };
  onEnded: (id: string) => void;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const languages = useLiveLanguages().data ?? [];
  const [lang, setLang] = useState(ORIGINAL);
  const [token, setToken] = useState(session.viewer_token);
  const [captureError, setCaptureError] = useState<string | null>(null);
  const stopRef = useRef<(() => void) | null>(null);
  const target = lang === ORIGINAL ? null : lang;
  const live = useLiveCaptions(session.session_id, null, target);
  const link = viewerUrl(session.session_id, token);

  useEffect(() => {
    let stopped = false;
    startCapture(session.session_id, session.source ?? 'mic')
      .then((stop) => {
        if (stopped) stop();
        else stopRef.current = stop;
      })
      .catch((e: Error) => setCaptureError(e.message));
    return () => {
      stopped = true;
      stopRef.current?.();
      stopRef.current = null;
    };
  }, [session.session_id, session.source]);

  const end = useMutation({
    mutationFn: () => {
      stopRef.current?.();
      stopRef.current = null;
      return liveApi.end(session.session_id);
    },
    onSuccess: (r) => onEnded(r.meeting_id),
  });
  const rotate = useMutation({
    mutationFn: async () => {
      await liveApi.revokeLinks(session.session_id);
      return liveApi.newLink(session.session_id);
    },
    onSuccess: (r) => {
      setToken(r.viewer_token);
      toast({ title: t('live.linkRotated') });
    },
  });

  return (
    <div className="mx-auto grid max-w-6xl gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <section className="min-w-0">
        <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2">
          <h1 className="mr-auto min-w-0 break-words font-display text-xl font-semibold">
            {live.title}
          </h1>
          <StatusBadge state={live.state} />
          <LanguagePicker id="host-lang" value={lang} onChange={setLang} languages={languages} />
        </div>
        {captureError && (
          <p role="alert" className="mb-4 text-sm text-destructive">
            {t('live.captureFailed', { error: captureError })}
          </p>
        )}
        <Card className="max-h-[70dvh] overflow-y-auto p-4 sm:p-6">
          <CaptionList
            captions={live.captions}
            partial={live.partial}
            lang={target}
            languages={languages}
          />
        </Card>
      </section>
      <aside className="min-w-0 space-y-4">
        <Card className="space-y-3 p-4">
          <h2 className="font-medium">{t('live.shareTitle')}</h2>
          <p className="text-xs text-muted-foreground">{t('live.shareHint')}</p>
          <QrCode value={link} label={t('live.qrLabel')} className="mx-auto size-40" />
          <Input
            readOnly
            value={link}
            onFocus={(e) => e.target.select()}
            aria-label={t('live.shareTitle')}
          />
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                navigator.clipboard.writeText(link).then(() => toast({ title: t('live.copied') }))
              }
            >
              <Copy aria-hidden="true" className="mr-2 size-4" />
              {t('live.copy')}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={rotate.isPending}
              onClick={() => rotate.mutate()}
            >
              {t('live.rotate')}
            </Button>
          </div>
          <Button size="sm" variant="outline" className="w-full" asChild>
            <a
              href={`${link}&view=present${target ? `&lang=${encodeURIComponent(target)}` : ''}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Presentation aria-hidden="true" className="mr-2 size-4" />
              {t('live.present')}
            </a>
          </Button>
          <p className="text-sm text-muted-foreground">
            {t('live.viewers', { count: live.viewers })}
          </p>
        </Card>
        <Card className="space-y-2 p-4 text-xs text-muted-foreground">
          <p>{t('live.engine', { asr: session.asr, translator: session.translator ?? '—' })}</p>
        </Card>
        <Button
          variant="destructive"
          className="w-full"
          disabled={end.isPending}
          onClick={() => end.mutate()}
        >
          <Square aria-hidden="true" className="mr-2 size-4" />
          {end.isPending ? t('live.ending') : t('live.end')}
        </Button>
        {end.error && (
          <p role="alert" className="text-sm text-destructive">
            {end.error.message}
          </p>
        )}
      </aside>
    </div>
  );
}

function Ended({ meetingId, onAgain }: { meetingId: string; onAgain: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="mx-auto max-w-xl space-y-4 px-4 py-8 text-center sm:px-6">
      <h1 className="font-display text-2xl font-semibold">{t('live.endedTitle')}</h1>
      <p className="text-muted-foreground">{t('live.endedBody')}</p>
      <div className="flex flex-wrap justify-center gap-3">
        <Button asChild>
          <Link to={`/meetings/${meetingId}`}>{t('live.openMeeting')}</Link>
        </Button>
        <Button variant="outline" onClick={onAgain}>
          {t('live.startAnother')}
        </Button>
      </div>
    </div>
  );
}
