"use client";

import { useId } from "react";

import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

export interface CheckboxGroupProps {
  legend: string;
  options: readonly string[];
  value: string[];
  onChange: (value: string[]) => void;
  columns?: 1 | 2 | 3;
  error?: string;
  description?: string;
}

/** Accessible multiselect built from a fieldset of checkboxes. */
export function CheckboxGroup({
  legend,
  options,
  value,
  onChange,
  columns = 2,
  error,
  description,
}: CheckboxGroupProps) {
  const groupId = useId();

  const toggle = (option: string, checked: boolean) => {
    if (checked) {
      onChange([...value, option]);
    } else {
      onChange(value.filter((v) => v !== option));
    }
  };

  const gridCols = columns === 3 ? "sm:grid-cols-3" : columns === 2 ? "sm:grid-cols-2" : "";

  return (
    <fieldset aria-describedby={error ? `${groupId}-error` : undefined}>
      <legend className="text-sm font-medium">{legend}</legend>
      {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
      <div className={cn("mt-2 grid grid-cols-1 gap-x-4 gap-y-2", gridCols)}>
        {options.map((option) => {
          const optionId = `${groupId}-${option}`;
          const checked = value.includes(option);
          return (
            <div key={option} className="flex items-center gap-2">
              <Checkbox
                id={optionId}
                checked={checked}
                onCheckedChange={(state) => toggle(option, state === true)}
              />
              <Label htmlFor={optionId} className="cursor-pointer font-normal">
                {option}
              </Label>
            </div>
          );
        })}
      </div>
      {error && (
        <p id={`${groupId}-error`} role="alert" className="mt-1.5 text-sm text-destructive">
          {error}
        </p>
      )}
    </fieldset>
  );
}
