import type { DataSourceType } from "@/types/design";

export const API_BASE_URL: string =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export const WS_BASE_URL: string = API_BASE_URL.replace(/^http/, "ws");

export const APP_ENVIRONMENT: string =
  process.env.NEXT_PUBLIC_ENVIRONMENT ?? "development";

// --- Design/approval display ---

export const APPROVAL_ROLE_LABELS: Record<string, string> = {
  engineer: "Engineer",
  architect: "Architect",
  cfo: "CFO",
  security: "Security",
  ops: "Ops",
};

export const ARCHITECTURE_LAYERS = ["ingestion", "processing", "storage", "serving"] as const;

export const LAYER_LABELS: Record<string, string> = {
  ingestion: "Ingestion",
  processing: "Processing",
  storage: "Storage",
  serving: "Serving",
};

// Default phase timeline used when the backend roadmap doesn't include
// explicit start_week/duration_weeks (see lib/design-adapters.ts).
export const DEFAULT_PHASE_TIMELINE: { start_week: number; duration_weeks: number }[] = [
  { start_week: 1, duration_weeks: 2 }, // Infrastructure
  { start_week: 3, duration_weeks: 2 }, // Connectors
  { start_week: 5, duration_weeks: 1 }, // Testing
  { start_week: 6, duration_weeks: 1 }, // Cutover
];

// Chart palette (see the dataviz skill for the full system; this is a
// compact subset sized for this app's charts).
export const CHART_COLORS = {
  categorical: ["#2563eb", "#16a34a", "#d97706", "#dc2626", "#7c3aed", "#0891b2"],
  status: {
    selected: "#16a34a",
    alternative: "#d97706",
    pruned: "#dc2626",
  },
  guardrail: {
    PASS: "#16a34a",
    FLAG: "#d97706",
    ESCALATE: "#dc2626",
    STOP: "#7f1d1d",
  },
} as const;

// --- File upload constraints ---

export const SUPPORTED_FILE_EXTENSIONS = [
  ".pdf",
  ".pptx",
  ".xlsx",
  ".html",
  ".htm",
  ".txt",
  ".csv",
] as const;

export const SUPPORTED_MIME_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "text/html",
  "text/plain",
  "text/csv",
] as const;

export const MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024; // 500MB per file
export const MAX_TOTAL_SIZE_BYTES = 2 * 1024 * 1024 * 1024; // 2GB total

// --- Dropdown / select options ---

export const DATA_SOURCE_TYPE_OPTIONS: { value: DataSourceType; label: string }[] = [
  { value: "DB", label: "Database" },
  { value: "API", label: "API" },
  { value: "File", label: "File" },
  { value: "Messaging", label: "Messaging" },
];

export const DATA_FRESHNESS_OPTIONS = [
  { value: "real-time", label: "Real-time" },
  { value: "near-real-time", label: "Near real-time (< 5 min)" },
  { value: "15min", label: "15 minutes" },
  { value: "hourly", label: "Hourly" },
  { value: "daily", label: "Daily" },
] as const;

export const TEAM_SKILLS_OPTIONS = [
  "Python",
  "SQL",
  "Java",
  "Apache Airflow",
  "Apache Spark",
  "Apache Kafka",
  "Dataflow / Beam",
  "BigQuery",
  "Terraform",
  "Kubernetes",
  "GCP",
  "AWS",
  "Azure",
] as const;

export const DATA_TYPE_OPTIONS = [
  "PII",
  "PHI",
  "PCI",
  "Financial",
  "Confidential",
  "Public",
] as const;

export const REGULATION_OPTIONS = [
  "GDPR",
  "HIPAA",
  "SOC2",
  "CCPA",
  "PCI-DSS",
  "ISO27001",
] as const;

export const DATA_RESIDENCY_OPTIONS = [
  { value: "none", label: "No restriction" },
  { value: "us", label: "United States" },
  { value: "eu", label: "European Union" },
  { value: "uk", label: "United Kingdom" },
  { value: "apac", label: "Asia-Pacific" },
  { value: "canada", label: "Canada" },
] as const;

export const ENCRYPTION_OPTIONS = [
  { value: "default", label: "Default (Google-managed)" },
  { value: "cmk", label: "CMK (Customer-Managed Key)" },
  { value: "cmek", label: "CMEK (Customer-Managed Encryption Key)" },
] as const;

export const MIGRATION_APPROACH_OPTIONS = [
  { value: "lift-and-shift", label: "Lift-and-shift" },
  { value: "redesign", label: "Redesign" },
  { value: "hybrid", label: "Hybrid" },
] as const;

export const STAKEHOLDER_PRIORITY_OPTIONS = [
  "Cost efficiency",
  "Speed to market",
  "Reliability",
  "Scalability",
  "Security",
  "Compliance",
  "Maintainability",
  "Performance",
] as const;

export const CURRENCY_OPTIONS = ["USD", "EUR", "GBP"] as const;
