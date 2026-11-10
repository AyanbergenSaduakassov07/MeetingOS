import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';

// Whisper codes the server accepts; names are endonyms so they need no translation.
const SPOKEN_LANGUAGES = [
  ['en', 'English'],
  ['ru', 'Русский'],
  ['kk', 'Қазақша'],
  ['uz', 'Oʻzbekcha'],
  ['ky', 'Кыргызча'],
  ['tr', 'Türkçe'],
  ['uk', 'Українська'],
  ['de', 'Deutsch'],
  ['fr', 'Français'],
  ['es', 'Español'],
  ['zh', '中文'],
  ['ar', 'العربية'],
] as const;
const AUTO = 'auto';

interface ConsentDialogProps {
  file: File | null;
  onCancel: () => void;
  /** `language` is a Whisper code, or null to auto-detect. */
  onConfirm: (file: File, note: string, language: string | null) => void;
}

/** The server refuses uploads without consent; this is where the user gives it. */
export function ConsentDialog({ file, onCancel, onConfirm }: ConsentDialogProps) {
  const { t } = useTranslation();
  const [agreed, setAgreed] = useState(false);
  const [note, setNote] = useState('');
  const [language, setLanguage] = useState<string>(AUTO);

  const reset = () => {
    setAgreed(false);
    setNote('');
    setLanguage(AUTO);
  };

  const close = () => {
    reset();
    onCancel();
  };

  return (
    <Dialog open={file !== null} onOpenChange={(open) => !open && close()}>
      <DialogContent data-testid="consent-dialog">
        <DialogHeader>
          <DialogTitle>{t('consent.title')}</DialogTitle>
          <DialogDescription>
            {t('consent.description', { name: file?.name ?? '' })}
          </DialogDescription>
        </DialogHeader>

        <div className="flex items-start gap-3">
          <Checkbox
            id="consent-agree"
            checked={agreed}
            onCheckedChange={setAgreed}
            className="mt-0.5"
          />
          <Label htmlFor="consent-agree" className="leading-snug">
            {t('consent.checkbox')}
          </Label>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="upload-language">{t('consent.languageLabel')}</Label>
          <Select value={language} onValueChange={setLanguage}>
            <SelectTrigger id="upload-language" data-testid="upload-language">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={AUTO}>{t('consent.languageAuto')}</SelectItem>
              {SPOKEN_LANGUAGES.map(([code, name]) => (
                <SelectItem key={code} value={code}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">{t('consent.languageHint')}</p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="consent-note">{t('consent.noteLabel')}</Label>
          <Textarea
            id="consent-note"
            maxLength={500}
            value={note}
            placeholder={t('consent.notePlaceholder')}
            onChange={(event) => setNote(event.target.value)}
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={close}>
            {t('common.cancel')}
          </Button>
          <Button
            data-testid="consent-confirm"
            disabled={!agreed}
            onClick={() => {
              if (!file) return;
              onConfirm(file, note, language === AUTO ? null : language);
              reset();
            }}
          >
            {t('consent.confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
