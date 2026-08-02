"use client";

import { useMemo } from "react";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2, Loader2 } from "lucide-react";

import { FileUploader } from "@/app/(routes)/upload/components/FileUploader";
import { PreviewRequirements } from "@/app/(routes)/upload/components/PreviewRequirements";
import {
  defaultRequirementFormValues,
  requirementFormSchema,
  RequirementForm,
  type RequirementFormValues,
} from "@/app/(routes)/upload/components/RequirementForm";
import { FormSection } from "@/components/shared/FormSection";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiClient } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { useFileUpload } from "@/hooks/useFileUpload";
import type { CreateDesignRequest, Requirement } from "@/types/design";

function buildContext(values: RequirementFormValues): string | undefined {
  const parts: string[] = [];
  if (values.current_system) parts.push(`Current system: ${values.current_system}`);
  parts.push(`Migration approach: ${values.migration_approach}`);
  if (values.project_deadline) parts.push(`Project deadline: ${values.project_deadline}`);
  if (values.known_constraints) parts.push(`Known constraints: ${values.known_constraints}`);
  if (values.stakeholder_priorities.length > 0) {
    parts.push(`Stakeholder priorities: ${values.stakeholder_priorities.join(", ")}`);
  }
  return parts.length > 0 ? parts.join("\n") : undefined;
}

function toRequirement(values: RequirementFormValues): Requirement {
  return {
    data_sources: values.data_sources,
    performance: values.performance,
    budget: values.budget,
    team: values.team,
    compliance: {
      data_types: values.compliance.data_types,
      regulations: values.compliance.regulations,
      data_residency:
        values.compliance.data_residency === "none" ? null : values.compliance.data_residency,
      encryption: values.compliance.encryption !== "default",
    },
    context: buildContext(values),
  };
}

export default function UploadPage() {
  const form = useForm<RequirementFormValues>({
    resolver: zodResolver(requirementFormSchema),
    defaultValues: defaultRequirementFormValues,
    mode: "onBlur",
  });

  const fileUpload = useFileUpload();

  const {
    execute: createDesign,
    loading: isSubmitting,
    error: submitError,
    data: createdDesign,
    reset: resetSubmission,
  } = useApi((request: CreateDesignRequest) => apiClient.createDesign(request));

  const watchedValues = useWatch({ control: form.control }) as RequirementFormValues;
  const previewRequirement = useMemo(() => toRequirement(watchedValues), [watchedValues]);

  const onSubmit = form.handleSubmit(async (values) => {
    if (fileUpload.files.length > 0) {
      await Promise.all(
        fileUpload.files
          .filter((f) => f.status === "idle")
          .map(async (f) => {
            try {
              await apiClient.uploadFile(f.file, (pct) => fileUpload.updateFileProgress(f.id, pct));
              fileUpload.markFileStatus(f.id, "success");
            } catch {
              fileUpload.markFileStatus(f.id, "error", "Upload failed; continuing without this file.");
            }
          })
      );
    }

    const requirement = toRequirement(values);
    try {
      await createDesign({ project_name: values.project_name, requirements: requirement });
      form.reset(defaultRequirementFormValues);
      fileUpload.resetFiles();
    } catch {
      // error state is already surfaced via useApi's `error`
    }
  });

  const startAnother = () => {
    resetSubmission();
    form.reset(defaultRequirementFormValues);
    fileUpload.resetFiles();
  };

  if (createdDesign) {
    return (
      <div className="mx-auto flex max-w-2xl flex-col gap-4">
        <Card className="border-success/50 bg-success/5">
          <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
            <CheckCircle2 className="h-10 w-10 text-success" aria-hidden="true" />
            <h1 className="text-xl font-semibold">Design generation started</h1>
            <p className="text-sm text-muted-foreground">
              &ldquo;{createdDesign.project_name}&rdquo; was submitted successfully. Design generation
              typically takes 15-20 minutes.
            </p>
            <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-left text-sm">
              <dt className="text-muted-foreground">Design ID</dt>
              <dd className="font-mono">{createdDesign.id}</dd>
              <dt className="text-muted-foreground">Status</dt>
              <dd className="capitalize">{createdDesign.status.replace("_", " ")}</dd>
            </dl>
            <Button className="mt-4" onClick={startAnother}>
              Start another design
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Upload ETL Design Requirements</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Upload supporting documents and/or fill out the requirements form below, then submit to
          start design generation.
        </p>
      </div>

      <form onSubmit={onSubmit} className="flex flex-col gap-6" noValidate>
        <FormSection
          title="Source Documents"
          description="Optional: upload existing architecture docs, data dictionaries, or specs (PDF, PPTX, XLSX, HTML, TXT, CSV)."
        >
          <FileUploader
            files={fileUpload.files}
            onAddFiles={fileUpload.addFiles}
            onRemoveFile={fileUpload.removeFile}
            totalSize={fileUpload.totalSize}
          />
        </FormSection>

        <RequirementForm form={form} />

        <PreviewRequirements
          projectName={watchedValues.project_name ?? ""}
          requirement={previewRequirement}
        />

        {submitError && (
          <p role="alert" className="text-sm text-destructive">
            {submitError}
          </p>
        )}

        <div className="flex items-center gap-3">
          <Button type="submit" disabled={isSubmitting} size="lg">
            {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
            {isSubmitting ? "Submitting..." : "Generate design"}
          </Button>
        </div>
      </form>
    </div>
  );
}
