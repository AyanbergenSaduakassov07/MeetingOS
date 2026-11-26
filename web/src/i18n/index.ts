import i18n from 'i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import { initReactI18next } from 'react-i18next';
import en from './locales/en/translation.json';
import kk from './locales/kk/translation.json';
import ru from './locales/ru/translation.json';

/**
 * UI chrome only.
 *
 * Meeting content — transcripts, extracted decisions, action items, risks —
 * never routes through here. That text is data in whatever language it was
 * spoken, and translating it would silently rewrite the record the verifier
 * checked its citations against.
 */
export const SUPPORTED_LANGUAGES = [
  { code: 'en', label: 'EN', name: 'English' },
  { code: 'ru', label: 'RU', name: 'Русский' },
  { code: 'kk', label: 'KZ', name: 'Қазақша' },
] as const;

export type LanguageCode = (typeof SUPPORTED_LANGUAGES)[number]['code'];

/**
 * Every ISO 639-1 language. Any can be chosen in Settings; those without a
 * translation file fall back to English UI text but still drive date/number
 * formatting and the language summaries and answers are written in.
 */
export const ALL_LANGUAGE_CODES =
  'aa ab af ak am an ar as av ay az ba be bg bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms mt my na nb nd ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu'.split(
    ' ',
  );

/** Name of a language, written in `displayIn`. Falls back to the code. */
export function languageName(code: string, displayIn: string): string {
  try {
    return new Intl.DisplayNames([displayIn], { type: 'language' }).of(code) ?? code;
  } catch {
    return code;
  }
}

export const LANGUAGE_STORAGE_KEY = 'meetingos:lang';

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      ru: { translation: ru },
      kk: { translation: kk },
    },
    fallbackLng: 'en',
    load: 'currentOnly',
    interpolation: { escapeValue: false },
    react: { useSuspense: false },
    detection: {
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: LANGUAGE_STORAGE_KEY,
      caches: ['localStorage'],
      // 'ru-RU' → 'ru', so a browser locale finds its translation file.
      convertDetectedLanguage: (lng: string) => lng.split('-')[0],
    },
  });

// Screen readers pick voice and pronunciation from <html lang>, so it names the
// language the UI text is actually in (English for untranslated choices).
const syncHtmlLang = () =>
  document.documentElement.setAttribute('lang', i18n.resolvedLanguage ?? 'en');
syncHtmlLang();
i18n.on('languageChanged', syncHtmlLang);

export default i18n;
