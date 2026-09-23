import React from 'react';
import { cn } from '@/lib/utils';

type DivProps = React.HTMLAttributes<HTMLDivElement>;

export function Card({ className = '', ...props }: DivProps) {
  return <div className={cn("glass-card overflow-hidden", className)} {...props} />;
}

export function CardHeader({ className = '', ...props }: DivProps) {
  return <div className={cn("px-8 py-6 border-b border-white/5 bg-white/[0.02]", className)} {...props} />;
}

export function CardTitle({ className = '', ...props }: DivProps) {
  return <h3 className={cn("text-xl font-black text-white tracking-tight", className)} {...props} />;
}

export function CardDescription({ className = '', ...props }: DivProps) {
  return <p className={cn("text-sm text-gray-400", className)} {...props} />;
}

export function CardContent({ className = '', ...props }: DivProps) {
  return <div className={cn("p-8", className)} {...props} />;
}
