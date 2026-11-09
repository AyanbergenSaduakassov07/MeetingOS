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
import { Textarea } from '@/components/ui/textarea';

interface ConsentDialogProps {
  file: File | null;
  onCancel: () => void;
  onConfirm: (file: File, note: string) => void;
}

/** The server refuses uploads without consent; this is where the user gives it. */
export function ConsentDialog({ file, onCancel, onConfirm }: ConsentDialogProps) {
  const { t } = useTranslation();
  const [agreed, setAgreed] = useState(false);
  const [note, setNote] = useState('');

  const close = () => {
    setAgreed(false);
    setNote('');
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
              onConfirm(file, note);
              setAgreed(false);
              setNote('');
            }}
          >
            {t('consent.confirm')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
