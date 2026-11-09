import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { KeyRound, Loader2 } from 'lucide-react';
import { type FormEvent, type ReactNode, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ApiError, api, UNAUTHORIZED_EVENT } from '@/lib/api';

const SESSION_KEY = ['session'];

/**
 * Renders the app only once the server says this browser may see it.
 * Any 401 elsewhere (key rotated, cookie expired) re-checks the session,
 * which drops the user back here instead of leaving broken pages.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const session = useQuery({ queryKey: SESSION_KEY, queryFn: api.getSession, retry: false });

  useEffect(() => {
    const recheck = () => queryClient.invalidateQueries({ queryKey: SESSION_KEY });
    window.addEventListener(UNAUTHORIZED_EVENT, recheck);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, recheck);
  }, [queryClient]);

  if (session.isLoading) {
    return (
      <div className="flex h-dvh items-center justify-center bg-background">
        <Loader2 aria-hidden="true" className="size-6 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (session.data?.authenticated) return <>{children}</>;
  return <LoginScreen />;
}

function LoginScreen() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [key, setKey] = useState('');

  const login = useMutation({
    mutationFn: api.login,
    onSuccess: () => queryClient.invalidateQueries(),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (key.trim()) login.mutate(key.trim());
  };

  const error = login.error
    ? login.error instanceof ApiError && login.error.status === 401
      ? t('auth.wrongKey')
      : t('auth.unreachable')
    : null;

  return (
    <main className="flex h-dvh items-center justify-center bg-background px-4">
      <form
        onSubmit={submit}
        data-testid="login-form"
        className="w-full max-w-sm space-y-5 rounded-xl border border-border bg-card p-8 shadow-sm"
      >
        <div className="flex items-center gap-3">
          <img src="/favicon.svg" alt="" className="size-10" />
          <h1 className="font-display text-2xl font-black tracking-tight">{t('nav.brand')}</h1>
        </div>
        <p className="text-sm text-muted-foreground">{t('auth.prompt')}</p>

        <div className="space-y-1.5">
          <Label htmlFor="api-key">{t('auth.keyLabel')}</Label>
          <Input
            id="api-key"
            type="password"
            autoComplete="current-password"
            autoFocus
            value={key}
            onChange={(event) => setKey(event.target.value)}
          />
        </div>

        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        <Button type="submit" className="w-full" disabled={login.isPending || !key.trim()}>
          {login.isPending ? (
            <Loader2 aria-hidden="true" className="size-4 animate-spin" />
          ) : (
            <KeyRound aria-hidden="true" className="size-4" />
          )}
          {t('auth.signIn')}
        </Button>
      </form>
    </main>
  );
}
