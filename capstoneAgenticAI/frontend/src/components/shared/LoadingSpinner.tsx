import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

export interface LoadingSpinnerProps {
  className?: string;
  size?: "sm" | "md" | "lg";
  label?: string;
}

const SIZE_CLASSES: Record<NonNullable<LoadingSpinnerProps["size"]>, string> = {
  sm: "h-4 w-4",
  md: "h-6 w-6",
  lg: "h-10 w-10",
};

/** Accessible loading indicator; announces itself to screen readers via role="status". */
export function LoadingSpinner({ className, size = "md", label = "Loading..." }: LoadingSpinnerProps) {
  return (
    <div role="status" className={cn("inline-flex items-center gap-2 text-muted-foreground", className)}>
      <Loader2 className={cn("animate-spin", SIZE_CLASSES[size])} aria-hidden="true" />
      <span className="text-sm">{label}</span>
    </div>
  );
}
