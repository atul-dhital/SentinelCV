import React from 'react';
import { cn } from '@/lib/utils';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'outline';
    size?: 'sm' | 'md' | 'lg';
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', ...props }, ref) => {
    const variants = {
        primary: "bg-brand-600 hover:bg-brand-500 text-white shadow-xl shadow-brand-600/20",
        secondary: "bg-white/5 hover:bg-white/10 text-white border border-white/10",
        ghost: "bg-transparent hover:bg-white/5 text-gray-400 hover:text-white",
      danger: "bg-red-500/10 hover:bg-red-500/20 text-red-500 border border-red-500/20",
      outline: "bg-transparent hover:bg-white/5 text-gray-300 border border-white/10"
    };

    const sizes = {
        sm: "h-9 px-4 text-xs",
        md: "h-11 px-6 text-sm",
        lg: "h-14 px-8 text-sm"
    };

    return (
      <button
        className={cn(
          "inline-flex items-center justify-center rounded-2xl font-bold transition-all disabled:opacity-50 disabled:cursor-not-allowed active:scale-95",
          variants[variant],
          sizes[size],
          className
        )}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button };
