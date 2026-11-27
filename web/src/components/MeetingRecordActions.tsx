import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { MoreHorizontal } from 'lucide-react';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ApiError, api, type MeetingDetail } from '@/lib/api';
import { Button } from './ui/button';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from './ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from './ui/dropdown-menu';
import { Input } from './ui/input';
import { toast } from './ui/use-toast';

const ACTIONS = {
  rename: 'record.rename',
  link: 'record.linkDocument',
  delete: 'common.delete',
} as const;
type Action = keyof typeof ACTIONS;

function RecordActionForm({
  action,
  meeting,
  onClose,
}: {
  action: Action;
  meeting: MeetingDetail;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const cache = useQueryClient();
  const [value, setValue] = useState(action === 'rename' ? meeting.title : '');
  const documents = useQuery({
    queryKey: ['documents'],
    queryFn: api.listDocuments,
    enabled: action === 'link',
  });

  const save = useMutation({
    mutationFn: async () => {
      if (action === 'rename') {
        const updated = await api.renameMeeting(meeting.id, value.trim());
        cache.setQueryData(['meeting', meeting.id], updated);
      } else if (action === 'link') {
        await api.linkDocument(value, meeting.id);
      } else {
        await api.deleteMeeting(meeting.id);
      }
    },
    onSuccess: () => {
      if (action !== 'link') void cache.invalidateQueries({ queryKey: ['meetings'] });
      if (action === 'link') {
        void cache.invalidateQueries({ queryKey: ['documents'] });
        toast({ title: t('record.documentLinked') });
      }
      onClose();
      if (action === 'delete') navigate('/meetings', { replace: true });
    },
  });

  const errorKey =
    save.error instanceof ApiError && save.error.status === 501
      ? 'record.actionUnavailable'
      : 'record.actionFailed';
  const canSubmit = action === 'delete' ? value === meeting.title : Boolean(value.trim());
  return (
    <form
      className="grid gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (canSubmit && !save.isPending) save.mutate();
      }}
    >
      {action === 'link' ? (
        <label className="grid gap-2 text-sm">
          {t('record.document')}
          <select
            value={value}
            onChange={(event) => setValue(event.target.value)}
            className="w-full rounded-md border border-input bg-card p-2"
          >
            <option value="">{t('record.chooseDocument')}</option>
            {documents.data?.map((document) => (
              <option key={document.id} value={document.id}>
                {document.title}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <label htmlFor="record-action-value" className="grid gap-2 text-sm">
          {t(action === 'delete' ? 'record.confirmTitle' : 'record.meetingTitle')}
          <Input
            id="record-action-value"
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        </label>
      )}
      {action === 'link' && (
        <output className="text-sm text-muted-foreground">
          {documents.isPending
            ? t('common.loading')
            : documents.isError
              ? t('record.documentsFailed')
              : documents.data?.length === 0 && t('record.noDocuments')}
        </output>
      )}
      {save.isError && (
        <p role="alert" className="text-sm text-destructive">
          {t(errorKey)}
        </p>
      )}
      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="outline"
          className="rounded-md"
          onClick={onClose}
          disabled={save.isPending}
        >
          {t('common.cancel')}
        </Button>
        <Button
          type="submit"
          variant={action === 'delete' ? 'destructive' : 'default'}
          className="rounded-md"
          disabled={!canSubmit || save.isPending}
        >
          {t(action === 'rename' ? 'common.save' : ACTIONS[action])}
        </Button>
      </div>
    </form>
  );
}

export function MeetingRecordActions({ meeting }: { meeting: MeetingDetail }) {
  const { t } = useTranslation();
  const [action, setAction] = useState<Action | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            ref={trigger}
            type="button"
            variant="outline"
            size="icon"
            className="size-9 rounded-md"
            aria-label={t('record.more')}
          >
            <MoreHorizontal aria-hidden="true" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {(['rename', 'link', 'delete'] as const).map((item) => (
            <DropdownMenuItem
              key={item}
              onSelect={() => setAction(item)}
              className={item === 'delete' ? 'text-destructive' : undefined}
            >
              {t(ACTIONS[item])}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      <Dialog
        open={action !== null}
        onOpenChange={(open) => {
          if (!open) setAction(null);
        }}
      >
        {action && (
          <DialogContent
            className="rounded-lg"
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              trigger.current?.focus();
            }}
            aria-describedby={action === 'delete' ? 'record-delete-detail' : undefined}
          >
            <DialogTitle>{t(ACTIONS[action])}</DialogTitle>
            {action === 'delete' && (
              <DialogDescription id="record-delete-detail">
                {t('record.deleteDetail', { title: meeting.title })}
              </DialogDescription>
            )}
            <RecordActionForm action={action} meeting={meeting} onClose={() => setAction(null)} />
          </DialogContent>
        )}
      </Dialog>
    </>
  );
}
