import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { Requirement } from "@/types/design";

export interface PreviewRequirementsProps {
  projectName: string;
  requirement: Requirement;
}

/** Read-only summary + raw JSON of the requirements about to be submitted. */
export function PreviewRequirements({ projectName, requirement }: PreviewRequirementsProps) {
  const payload = { project_name: projectName, requirements: requirement };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Preview</CardTitle>
        <CardDescription>Review the requirements before starting design generation.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-muted-foreground">Project</dt>
            <dd className="font-medium">{projectName || "—"}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Data sources</dt>
            <dd className="font-medium">{requirement.data_sources.length}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Team size</dt>
            <dd className="font-medium">{requirement.team.size}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Budget cap</dt>
            <dd className="font-medium">
              {requirement.budget.monthly_cap_usd.toLocaleString()} {requirement.budget.currency}/mo
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Latency SLA</dt>
            <dd className="font-medium">{requirement.performance.latency_sla_minutes} min</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Encryption</dt>
            <dd className="font-medium">{requirement.compliance.encryption ? "Enabled" : "Default"}</dd>
          </div>
        </dl>

        {requirement.compliance.regulations.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {requirement.compliance.regulations.map((reg) => (
              <Badge key={reg} variant="secondary">
                {reg}
              </Badge>
            ))}
          </div>
        )}

        <div>
          <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Raw JSON
          </p>
          <pre className="max-h-96 overflow-auto rounded-md bg-muted p-3 text-xs">
            <code>{JSON.stringify(payload, null, 2)}</code>
          </pre>
        </div>
      </CardContent>
    </Card>
  );
}
