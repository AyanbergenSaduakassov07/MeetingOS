import { Check } from 'lucide-react';
import * as React from 'react';
import { cn } from '@/lib/utils';

export interface CheckboxProps {
  checked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  disabled?: boolean;
  className?: string;
  id?: string;
}

/**
 * Same interface as the Voicebox original; native control underneath.
 *
 * The original was a `<button role="checkbox">`. A real `<input type="checkbox">`
 * gets form participation, the platform's own focus and announcement behaviour,
 * and works with `<label for>` for free. The visible box stays 16px, while the
 * input is stretched to a 44px hit area so the touch target meets the minimum
 * without changing the layout around it.
 */
const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ checked = false, onCheckedChange, disabled = false, className, id, ...props }, ref) => {
    return (
      <span className={cn('relative inline-flex size-4 shrink-0', className)}>
        <input
          type="checkbox"
          ref={ref}
          id={id}
          checked={checked}
          disabled={disabled}
          onChange={(event) => onCheckedChange?.(event.target.checked)}
          className={cn(
            'peer absolute -inset-3.5 z-10 m-0 cursor-pointer opacity-0',
            disabled && 'cursor-not-allowed',
          )}
          {...props}
        />
        <span
          aria-hidden="true"
          className={cn(
            'pointer-events-none flex size-4 items-center justify-center rounded border-2 transition-colors duration-150',
            'peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-background',
            checked ? 'border-accent bg-accent' : 'border-muted-foreground/30',
            disabled && 'opacity-50',
          )}
        >
          {checked && <Check className="size-3 text-accent-foreground" />}
        </span>
      </span>
    );
  },
);
Checkbox.displayName = 'Checkbox';

export { Checkbox };
