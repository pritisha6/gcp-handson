"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto flex max-w-md flex-col gap-4 py-16">
      <Card className="border-destructive/50">
        <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
          <AlertTriangle className="h-10 w-10 text-destructive" aria-hidden="true" />
          <h1 className="text-lg font-semibold">Something went wrong</h1>
          <p className="text-sm text-muted-foreground">
            An unexpected error occurred while rendering this page. You can try again below.
          </p>
          <Button onClick={reset} className="mt-2">
            Try again
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
