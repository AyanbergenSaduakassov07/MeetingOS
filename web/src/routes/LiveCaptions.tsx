import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { type Caption, type LiveLanguage, liveApi } from '@/lib/live';

export const ORIGINAL = 'original';

export function useLiveLanguages() {
  return useQuery({
    queryKey: ['live-languages'],
    queryFn: liveApi.languages,
    staleTime: Infinity,
  });
}

export function LanguagePicker({
  value,
  onChange,
  languages,
  id,
  originalLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  languages: LiveLanguage[];
  id: string;
  originalLabel?: string;
}) {
  const { t } = useTranslation();
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger id={id} className="w-56">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ORIGINAL}>{originalLabel ?? t('live.original')}</SelectItem>
        {languages.map((l) => (
          <SelectItem key={l.code} value={l.code}>
            {l.native} · {l.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Scrolling caption list: original text, with the chosen translation under it. */
export function CaptionList({
  captions,
  partial,
  lang,
  languages,
}: {
  captions: Caption[];
  partial: string;
  lang: string | null;
  languages: LiveLanguage[];
}) {
  const { t } = useTranslation();
  const end = useRef<HTMLDivElement>(null);
  const rtl = languages.find((l) => l.code === lang)?.rtl ?? false;

  // biome-ignore lint/correctness/useExhaustiveDependencies: new captions are the trigger to scroll
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' });
  }, [captions.length, partial]);

  if (!captions.length && !partial) {
    return <p className="py-12 text-center text-muted-foreground">{t('live.waiting')}</p>;
  }
  return (
    <div aria-live="polite" className="space-y-4 text-lg leading-relaxed">
      {captions.map((c) => {
        // null = loaded from the snapshot untranslated (said before this language was opened): show the original.
        const showTranslation = lang && c.language !== lang && c.translation !== null;
        return (
          <div key={c.segment_id}>
            {showTranslation ? (
              <>
                <p dir={rtl ? 'rtl' : 'ltr'} className="text-xl font-medium">
                  {c.translation ?? (
                    <span className="text-muted-foreground italic">
                      {c.translationFailed ? t('live.translationFailed') : t('live.translating')}
                    </span>
                  )}
                </p>
                <p className="text-sm text-muted-foreground">{c.text}</p>
              </>
            ) : (
              <p className="text-xl">{c.text}</p>
            )}
          </div>
        );
      })}
      {partial && <p className="text-xl text-muted-foreground italic">{partial}</p>}
      <div ref={end} />
    </div>
  );
}
