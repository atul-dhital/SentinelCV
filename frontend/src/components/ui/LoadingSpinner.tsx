import { cn } from "@/lib/utils";

interface LoadingSpinnerProps {
  size?: "xs" | "sm" | "md" | "lg" | "xl";
  className?: string;
  label?: string;
}

const sizeMap = {
  xs: "w-3 h-3 border",
  sm: "w-5 h-5 border-2",
  md: "w-8 h-8 border-2",
  lg: "w-12 h-12 border-[3px]",
  xl: "w-16 h-16 border-4",
};

export function LoadingSpinner({ size = "md", className, label = "Loading…" }: LoadingSpinnerProps) {
  return (
    <div
      role="status"
      aria-label={label}
      className={cn(
        "rounded-full border-white/15 border-t-brand-500 animate-spin",
        sizeMap[size],
        className
      )}
    />
  );
}

export function LoadingOverlay({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 w-full">
      <LoadingSpinner size="lg" />
      <p className="text-sm text-gray-500 animate-pulse">{label}</p>
    </div>
  );
}

export default LoadingSpinner;
