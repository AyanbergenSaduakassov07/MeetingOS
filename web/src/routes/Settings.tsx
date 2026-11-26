import { Check, Search } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { NavLink, Outlet } from 'react-router-dom';
import { ALL_LANGUAGE_CODES, languageName, SUPPORTED_LANGUAGES } from '@/i18n';
import { cn } from '@/lib/utils';

const TRANSLATED = new Set<string>(SUPPORTED_LANGUAGES.map((l) => l.code));
const SECTIONS = [
  { to: 'language', labelKey: 'settings.language' },
  { to: 'privacy', labelKey: 'settings.privacy' },
] as const;

/** Settings frame: section tabs above whichever settings page is open. */
export function SettingsLayout() {
  const { t } = useTranslation();
  return (
    <div>
      <div className="mx-auto max-w-4xl px-6 pt-8">
        <h1 className="font-display text-3xl font-semibold tracking-tight">
          {t('settings.title')}
        </h1>
        <nav aria-label={t('settings.title')} className="mt-4 flex gap-1 border-b border-border">
          {SECTIONS.map(({ to, labelKey }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  '-mb-px border-b-2 px-3 py-2 text-sm font-medium',
                  isActive
                    ? 'border-foreground text-foreground'
                    : 'border-transparent text-muted-foreground hover:text-foreground',
                )
              }
            >
              {t(labelKey)}
            </NavLink>
          ))}
        </nav>
      </div>
      <Outlet />
    </div>
  );
}

interface LanguageOption {
  code: string;
  native: string;
  local: string;
}

const capitalize = (text: string, locale: string) =>
  text.charAt(0).toLocaleUpperCase(locale) + text.slice(1);

function buildOptions(uiLanguage: string): LanguageOption[] {
  const seen = new Set<string>();
  return ALL_LANGUAGE_CODES.map((code) => ({
    code,
    native: capitalize(languageName(code, code), code),
    local: capitalize(languageName(code, uiLanguage), uiLanguage),
  }))
    .filter((option) => {
      // Skip codes the runtime cannot name, and aliases that resolve to the same name (ak/tw).
      if (option.native.toLowerCase() === option.code || seen.has(option.native)) return false;
      seen.add(option.native);
      return true;
    })
    .sort((a, b) => a.local.localeCompare(b.local, uiLanguage));
}

/** Pick any language; en/ru/kk also translate the interface. */
export function LanguageSettings() {
  const { t, i18n } = useTranslation();
  const [query, setQuery] = useState('');
  const current = i18n.language;
  const uiLanguage = i18n.resolvedLanguage ?? 'en';

  const options = buildOptions(uiLanguage);
  const needle = query.trim().toLocaleLowerCase();
  const matches = needle
    ? options.filter((o) =>
        [o.code, o.native, o.local].some((s) => s.toLocaleLowerCase().includes(needle)),
      )
    : options;
  const translated = matches.filter((o) => TRANSLATED.has(o.code));
  const others = matches.filter((o) => !TRANSLATED.has(o.code));

  const renderOption = (option: LanguageOption) => {
    const selected = option.code === current;
    return (
      <li key={option.code}>
        <label
          className={cn(
            'relative flex min-h-11 cursor-pointer items-center gap-3 px-4 py-2 text-sm hover:bg-muted',
            'has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-ring',
            selected && 'bg-secondary',
          )}
        >
          <input
            type="radio"
            name="language"
            value={option.code}
            checked={selected}
            onChange={() => void i18n.changeLanguage(option.code)}
            className="sr-only"
          />
          <span lang={option.code} className="font-medium">
            {option.native}
          </span>
          {option.local !== option.native && (
            <span className="text-muted-foreground">{option.local}</span>
          )}
          <span className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
            {TRANSLATED.has(option.code) && <span>{t('settings.translated')}</span>}
            {selected && (
              <Check aria-label={t('settings.current')} className="size-4 text-foreground" />
            )}
          </span>
        </label>
      </li>
    );
  };

  return (
    <div className="mx-auto max-w-4xl px-6 py-6" data-testid="language-settings">
      <p className="max-w-2xl text-sm text-muted-foreground">{t('settings.languageHelp')}</p>
      <p className="mt-2 max-w-2xl text-sm text-muted-foreground">{t('settings.interfaceNote')}</p>

      <div className="relative mt-6 max-w-md">
        <Search
          aria-hidden="true"
          className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
        />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t('settings.search')}
          aria-label={t('settings.search')}
          className="h-10 w-full rounded-md border border-border bg-card pl-9 pr-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
      </div>

      <fieldset className="mt-4 max-w-md overflow-hidden rounded-lg border border-border bg-card">
        <legend className="sr-only">{t('settings.language')}</legend>
        {matches.length === 0 ? (
          <p className="p-6 text-sm text-muted-foreground">{t('settings.noMatch', { query })}</p>
        ) : (
          <div className="max-h-[60vh] overflow-y-auto">
            {translated.length > 0 && (
              <ul className="border-b border-border">{translated.map(renderOption)}</ul>
            )}
            {others.length > 0 && (
              <>
                <p className="px-4 pt-3 pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {t('settings.allLanguages')}
                </p>
                <ul>{others.map(renderOption)}</ul>
              </>
            )}
          </div>
        )}
      </fieldset>
    </div>
  );
}
