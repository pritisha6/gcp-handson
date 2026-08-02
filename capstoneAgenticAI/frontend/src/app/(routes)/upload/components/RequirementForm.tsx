"use client";

import type { ReactNode } from "react";
import { Controller, useFieldArray, type UseFormReturn } from "react-hook-form";
import { Plus, Trash2 } from "lucide-react";
import { z } from "zod";

import { CheckboxGroup } from "@/components/shared/CheckboxGroup";
import { FormSection } from "@/components/shared/FormSection";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  DATA_FRESHNESS_OPTIONS,
  DATA_RESIDENCY_OPTIONS,
  DATA_SOURCE_TYPE_OPTIONS,
  DATA_TYPE_OPTIONS,
  ENCRYPTION_OPTIONS,
  MIGRATION_APPROACH_OPTIONS,
  REGULATION_OPTIONS,
  STAKEHOLDER_PRIORITY_OPTIONS,
  TEAM_SKILLS_OPTIONS,
} from "@/lib/constants";

// --- Validation schema ---

export const dataSourceSchema = z.object({
  name: z.string().min(1, "Name is required"),
  type: z.enum(["DB", "API", "File", "Messaging"]),
  size_gb: z.number({ invalid_type_error: "Enter a size" }).min(0, "Must be 0 or greater"),
  throughput_records_sec: z
    .number({ invalid_type_error: "Enter a throughput value" })
    .min(0, "Must be 0 or greater"),
});

export const requirementFormSchema = z.object({
  project_name: z.string().min(1, "Project name is required"),
  data_sources: z.array(dataSourceSchema).min(1, "Add at least one data source"),
  performance: z.object({
    latency_sla_minutes: z.number({ invalid_type_error: "Required" }).min(0),
    peak_throughput_msgs_sec: z.number({ invalid_type_error: "Required" }).min(0),
    data_freshness: z.string().min(1, "Select data freshness"),
    p95_latency_minutes: z.number({ invalid_type_error: "Required" }).min(0),
  }),
  budget: z.object({
    monthly_cap_usd: z.number({ invalid_type_error: "Required" }).min(0),
    currency: z.string().min(3).max(3),
  }),
  project_deadline: z.string().optional(),
  team: z.object({
    size: z.number({ invalid_type_error: "Required" }).int().min(1, "Must be at least 1"),
    skills: z.array(z.string()).default([]),
  }),
  compliance: z.object({
    data_types: z.array(z.string()).default([]),
    regulations: z.array(z.string()).default([]),
    data_residency: z.string().min(1, "Select a data residency option"),
    encryption: z.enum(["default", "cmk", "cmek"]),
  }),
  current_system: z.string().optional(),
  migration_approach: z.enum(["lift-and-shift", "redesign", "hybrid"]),
  known_constraints: z.string().optional(),
  stakeholder_priorities: z.array(z.string()).default([]),
});

export type RequirementFormValues = z.infer<typeof requirementFormSchema>;

export const defaultRequirementFormValues: RequirementFormValues = {
  project_name: "",
  data_sources: [{ name: "", type: "DB", size_gb: 0, throughput_records_sec: 0 }],
  performance: {
    latency_sla_minutes: 0,
    peak_throughput_msgs_sec: 0,
    data_freshness: "",
    p95_latency_minutes: 0,
  },
  budget: { monthly_cap_usd: 0, currency: "USD" },
  project_deadline: "",
  team: { size: 1, skills: [] },
  compliance: { data_types: [], regulations: [], data_residency: "", encryption: "default" },
  current_system: "",
  migration_approach: "lift-and-shift",
  known_constraints: "",
  stakeholder_priorities: [],
};

function FieldError({ children }: { children?: ReactNode }) {
  if (!children) return null;
  return (
    <p role="alert" className="mt-1 text-sm text-destructive">
      {children}
    </p>
  );
}

export interface RequirementFormProps {
  form: UseFormReturn<RequirementFormValues>;
}

export function RequirementForm({ form }: RequirementFormProps) {
  const {
    register,
    control,
    formState: { errors },
  } = form;
  const { fields, append, remove } = useFieldArray({ control, name: "data_sources" });

  return (
    <div className="flex flex-col gap-6">
      <FormSection title="Project">
        <div>
          <Label htmlFor="project_name">Project name</Label>
          <Input
            id="project_name"
            placeholder="e.g. Customer 360 Pipeline"
            aria-invalid={!!errors.project_name}
            {...register("project_name")}
          />
          <FieldError>{errors.project_name?.message}</FieldError>
        </div>
      </FormSection>

      <FormSection
        title="Data Sources"
        description="Upstream systems that will feed this ETL pipeline."
      >
        <div className="flex flex-col gap-4">
          {fields.map((field, index) => (
            <div
              key={field.id}
              className="grid gap-3 rounded-md border p-3 sm:grid-cols-2 lg:grid-cols-[1fr_140px_120px_160px_auto] lg:items-end"
            >
              <div>
                <Label htmlFor={`data_sources.${index}.name`}>Name</Label>
                <Input
                  id={`data_sources.${index}.name`}
                  aria-invalid={!!errors.data_sources?.[index]?.name}
                  {...register(`data_sources.${index}.name` as const)}
                />
                <FieldError>{errors.data_sources?.[index]?.name?.message}</FieldError>
              </div>

              <div>
                <Label htmlFor={`data_sources.${index}.type`}>Type</Label>
                <Controller
                  control={control}
                  name={`data_sources.${index}.type` as const}
                  render={({ field: f }) => (
                    <Select value={f.value} onValueChange={f.onChange}>
                      <SelectTrigger id={`data_sources.${index}.type`}>
                        <SelectValue placeholder="Type" />
                      </SelectTrigger>
                      <SelectContent>
                        {DATA_SOURCE_TYPE_OPTIONS.map((opt) => (
                          <SelectItem key={opt.value} value={opt.value}>
                            {opt.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
              </div>

              <div>
                <Label htmlFor={`data_sources.${index}.size_gb`}>Size (GB)</Label>
                <Input
                  id={`data_sources.${index}.size_gb`}
                  type="number"
                  step="any"
                  min={0}
                  aria-invalid={!!errors.data_sources?.[index]?.size_gb}
                  {...register(`data_sources.${index}.size_gb` as const, { valueAsNumber: true })}
                />
                <FieldError>{errors.data_sources?.[index]?.size_gb?.message}</FieldError>
              </div>

              <div>
                <Label htmlFor={`data_sources.${index}.throughput_records_sec`}>
                  Throughput (records/sec)
                </Label>
                <Input
                  id={`data_sources.${index}.throughput_records_sec`}
                  type="number"
                  step="any"
                  min={0}
                  aria-invalid={!!errors.data_sources?.[index]?.throughput_records_sec}
                  {...register(`data_sources.${index}.throughput_records_sec` as const, {
                    valueAsNumber: true,
                  })}
                />
                <FieldError>{errors.data_sources?.[index]?.throughput_records_sec?.message}</FieldError>
              </div>

              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => remove(index)}
                disabled={fields.length === 1}
                aria-label={`Remove data source ${index + 1}`}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
          <FieldError>{errors.data_sources?.root?.message ?? errors.data_sources?.message}</FieldError>
          <Button
            type="button"
            variant="outline"
            className="self-start"
            onClick={() =>
              append({ name: "", type: "DB", size_gb: 0, throughput_records_sec: 0 })
            }
          >
            <Plus className="h-4 w-4" />
            Add data source
          </Button>
        </div>
      </FormSection>

      <FormSection title="Performance" description="Latency and throughput SLAs.">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="performance.latency_sla_minutes">Latency SLA (minutes)</Label>
            <Input
              id="performance.latency_sla_minutes"
              type="number"
              step="any"
              min={0}
              aria-invalid={!!errors.performance?.latency_sla_minutes}
              {...register("performance.latency_sla_minutes", { valueAsNumber: true })}
            />
            <FieldError>{errors.performance?.latency_sla_minutes?.message}</FieldError>
          </div>
          <div>
            <Label htmlFor="performance.peak_throughput_msgs_sec">Peak throughput (msgs/sec)</Label>
            <Input
              id="performance.peak_throughput_msgs_sec"
              type="number"
              step="any"
              min={0}
              aria-invalid={!!errors.performance?.peak_throughput_msgs_sec}
              {...register("performance.peak_throughput_msgs_sec", { valueAsNumber: true })}
            />
            <FieldError>{errors.performance?.peak_throughput_msgs_sec?.message}</FieldError>
          </div>
          <div>
            <Label htmlFor="performance.data_freshness">Data freshness</Label>
            <Controller
              control={control}
              name="performance.data_freshness"
              render={({ field }) => (
                <Select value={field.value || undefined} onValueChange={field.onChange}>
                  <SelectTrigger id="performance.data_freshness">
                    <SelectValue placeholder="Select freshness" />
                  </SelectTrigger>
                  <SelectContent>
                    {DATA_FRESHNESS_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
            <FieldError>{errors.performance?.data_freshness?.message}</FieldError>
          </div>
          <div>
            <Label htmlFor="performance.p95_latency_minutes">P95 latency (minutes)</Label>
            <Input
              id="performance.p95_latency_minutes"
              type="number"
              step="any"
              min={0}
              aria-invalid={!!errors.performance?.p95_latency_minutes}
              {...register("performance.p95_latency_minutes", { valueAsNumber: true })}
            />
            <FieldError>{errors.performance?.p95_latency_minutes?.message}</FieldError>
          </div>
        </div>
      </FormSection>

      <FormSection title="Business Constraints" description="Budget, timeline, and team.">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="budget.monthly_cap_usd">Budget cap ($/month)</Label>
            <Input
              id="budget.monthly_cap_usd"
              type="number"
              step="any"
              min={0}
              aria-invalid={!!errors.budget?.monthly_cap_usd}
              {...register("budget.monthly_cap_usd", { valueAsNumber: true })}
            />
            <FieldError>{errors.budget?.monthly_cap_usd?.message}</FieldError>
          </div>
          <div>
            <Label htmlFor="project_deadline">Project deadline</Label>
            <Input id="project_deadline" type="date" {...register("project_deadline")} />
          </div>
          <div>
            <Label htmlFor="team.size">Team size</Label>
            <Input
              id="team.size"
              type="number"
              min={1}
              step={1}
              aria-invalid={!!errors.team?.size}
              {...register("team.size", { valueAsNumber: true })}
            />
            <FieldError>{errors.team?.size?.message}</FieldError>
          </div>
        </div>
        <Controller
          control={control}
          name="team.skills"
          render={({ field }) => (
            <CheckboxGroup
              legend="Team skills"
              options={TEAM_SKILLS_OPTIONS}
              value={field.value}
              onChange={field.onChange}
              columns={3}
            />
          )}
        />
      </FormSection>

      <FormSection title="Compliance & Security">
        <Controller
          control={control}
          name="compliance.data_types"
          render={({ field }) => (
            <CheckboxGroup
              legend="Data types"
              options={DATA_TYPE_OPTIONS}
              value={field.value}
              onChange={field.onChange}
              columns={3}
            />
          )}
        />
        <Controller
          control={control}
          name="compliance.regulations"
          render={({ field }) => (
            <CheckboxGroup
              legend="Regulations"
              options={REGULATION_OPTIONS}
              value={field.value}
              onChange={field.onChange}
              columns={3}
            />
          )}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="compliance.data_residency">Data residency</Label>
            <Controller
              control={control}
              name="compliance.data_residency"
              render={({ field }) => (
                <Select value={field.value || undefined} onValueChange={field.onChange}>
                  <SelectTrigger id="compliance.data_residency">
                    <SelectValue placeholder="Select region" />
                  </SelectTrigger>
                  <SelectContent>
                    {DATA_RESIDENCY_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
            <FieldError>{errors.compliance?.data_residency?.message}</FieldError>
          </div>
          <div>
            <Label>Encryption</Label>
            <Controller
              control={control}
              name="compliance.encryption"
              render={({ field }) => (
                <RadioGroup value={field.value} onValueChange={field.onChange} className="mt-2">
                  {ENCRYPTION_OPTIONS.map((opt) => (
                    <div key={opt.value} className="flex items-center gap-2">
                      <RadioGroupItem value={opt.value} id={`encryption-${opt.value}`} />
                      <Label htmlFor={`encryption-${opt.value}`} className="font-normal">
                        {opt.label}
                      </Label>
                    </div>
                  ))}
                </RadioGroup>
              )}
            />
          </div>
        </div>
      </FormSection>

      <FormSection title="Additional Context">
        <div>
          <Label htmlFor="current_system">Current system</Label>
          <Textarea
            id="current_system"
            placeholder="Describe the existing system, if any..."
            {...register("current_system")}
          />
        </div>
        <div>
          <Label>Migration approach</Label>
          <Controller
            control={control}
            name="migration_approach"
            render={({ field }) => (
              <RadioGroup value={field.value} onValueChange={field.onChange} className="mt-2">
                {MIGRATION_APPROACH_OPTIONS.map((opt) => (
                  <div key={opt.value} className="flex items-center gap-2">
                    <RadioGroupItem value={opt.value} id={`migration-${opt.value}`} />
                    <Label htmlFor={`migration-${opt.value}`} className="font-normal">
                      {opt.label}
                    </Label>
                  </div>
                ))}
              </RadioGroup>
            )}
          />
        </div>
        <div>
          <Label htmlFor="known_constraints">Known constraints</Label>
          <Textarea
            id="known_constraints"
            placeholder="Any known technical or organizational constraints..."
            {...register("known_constraints")}
          />
        </div>
        <Controller
          control={control}
          name="stakeholder_priorities"
          render={({ field }) => (
            <CheckboxGroup
              legend="Stakeholder priorities"
              options={STAKEHOLDER_PRIORITY_OPTIONS}
              value={field.value}
              onChange={field.onChange}
              columns={2}
            />
          )}
        />
      </FormSection>
    </div>
  );
}
