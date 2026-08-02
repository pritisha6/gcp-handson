import type { ReactNode } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export interface FormSectionProps {
  title: string;
  description?: string;
  children: ReactNode;
}

/** Consistent card wrapper used for each section of the requirements form. */
export function FormSection({ title, description, children }: FormSectionProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent className="flex flex-col gap-5">{children}</CardContent>
    </Card>
  );
}
