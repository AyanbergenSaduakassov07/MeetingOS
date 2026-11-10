import { useTranslation } from 'react-i18next';
import { SUPPORTED_LANGUAGES } from '@/i18n';
import { cn } from '@/lib/utils';

/**
 * EN/RU/KZ pill. All languages always visible — a segmented control shows
 * the alternatives without a click, which a dropdown cannot, and at three
 * options a menu costs more interaction than it saves.
 *
 * Persistence is handled by i18next's language detector (localStorage under
 * `meetingos:lang`), so changing the language here survives a reload without
 * this component owning any storage code.
 */
export function LanguageToggle({ className }: { className?: string }) {
  const { i18n, t } = useTranslation();
  const active = i18n.resolvedLanguage ?? 'en';

  return (
    <fieldset
      className={cn(
        'inline-flex items-center gap-0.5 rounded-full border border-border bg-secondary p-0.5',
        className,
      )}
    >
      <legend className="sr-only">{t('nav.languageSwitch')}</legend>
      {SUPPORTED_LANGUAGES.map((language) => {
        const selected = active === language.code;
        return (
          <button
            key={language.code}
            type="button"
            lang={language.code}
            aria-pressed={selected}
            title={language.name}
            onClick={() => void i18n.changeLanguage(language.code)}
            className={cn(
              'min-h-11 min-w-11 rounded-full px-3 text-xs font-semibold tracking-wide transition-colors duration-150',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
              selected
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {language.label}
          </button>
        );
      })}
    </fieldset>
  );
}
