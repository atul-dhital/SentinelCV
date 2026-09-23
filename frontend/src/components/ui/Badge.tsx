import React from 'react';
import { cn } from '@/lib/utils';

type BadgeProps = React.HTMLAttributes<HTMLSpanElement> & {
  variant?: 'default' | 'secondary' | 'destructive' | 'outline' | 'success';
};

export function Badge({ className = '', variant = 'default', ...props }: BadgeProps) {
  const variants = {
    default: 'bg-brand-500/10 text-brand-400 border-brand-500/20',
    secondary: 'bg-white/5 text-gray-400 border-white/10',
    destructive: 'bg-red-500/10 text-red-500 border-red-500/20',
    outline: 'bg-transparent text-gray-500 border-white/10',
    success: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  };

  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-3 py-0.5 text-[10px] font-black uppercase tracking-widest transition-colors',
        variants[variant],
        className
      )}
      {...props}
    />
  );
}
