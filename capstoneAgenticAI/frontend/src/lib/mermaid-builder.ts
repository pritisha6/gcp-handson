/**
 * Builds a richer Mermaid flowchart (service names + costs, volume-labeled
 * edges, compliance highlighting) from a Design's structured data, rather
 * than rendering the backend's minimal `architecture_diagram` string
 * (which is just `"A" --> "B"` with no costs/volumes/compliance info).
 */
import { ARCHITECTURE_LAYERS } from "@/lib/constants";
import { normalizeCostAnalysis, normalizeDecisionMatrix } from "@/lib/design-adapters";
import type { Design } from "@/types/design";

export interface MermaidBuildResult {
  definition: string;
  complianceNotes: string[];
  isEmpty: boolean;
}

function sanitizeId(label: string, index: number): string {
  const cleaned = label.replace(/[^a-zA-Z0-9]/g, "");
  return `n${index}_${cleaned || "node"}`.slice(0, 40);
}

function formatCost(amount: number | undefined, currency: string): string | null {
  if (amount === undefined || Number.isNaN(amount)) return null;
  const symbol = currency === "USD" ? "$" : `${currency} `;
  return amount >= 1000 ? `${symbol}${(amount / 1000).toFixed(1)}K/mo` : `${symbol}${amount.toFixed(0)}/mo`;
}

function formatVolume(sizeGb: number): string {
  return sizeGb >= 1000 ? `${(sizeGb / 1000).toFixed(1)}TB` : `${sizeGb.toFixed(0)}GB`;
}

export function buildArchitectureMermaid(design: Design): MermaidBuildResult {
  const decisionMatrix = normalizeDecisionMatrix(design.output?.decision_matrix);
  const costAnalysis = normalizeCostAnalysis(
    design.output?.cost_analysis ?? null,
    design.requirements.budget.monthly_cap_usd
  );
  const path = decisionMatrix.selectedPath;

  if (path.length === 0) {
    return {
      definition: 'flowchart LR\n    Empty["No architecture selected yet"]',
      complianceNotes: [],
      isEmpty: true,
    };
  }

  const lines: string[] = ["flowchart LR"];
  const sources = design.requirements.data_sources;
  const totalSizeGb = sources.reduce((sum, s) => sum + s.size_gb, 0);

  const sourceIds = sources.map((source, i) => {
    const id = sanitizeId(source.name, i);
    lines.push(`    ${id}["${source.name}<br/>${formatVolume(source.size_gb)}"]`);
    return id;
  });

  const layerIds = path.map((service, i) => {
    const layerKey = ARCHITECTURE_LAYERS[i] ?? `layer_${i}`;
    const cost = formatCost(costAnalysis.breakdown.find((b) => b.component === layerKey)?.amount, costAnalysis.currency);
    const id = sanitizeId(service, sources.length + i);
    lines.push(`    ${id}["${service}${cost ? `<br/>${cost}` : ""}"]`);
    return id;
  });

  const sinkId = "sink_analytics";
  lines.push(`    ${sinkId}(["Analytics / Consumers"])`);

  sourceIds.forEach((id) => {
    lines.push(`    ${id} -->|"${formatVolume(totalSizeGb)}"| ${layerIds[0]}`);
  });

  const throughput = design.requirements.performance.peak_throughput_msgs_sec;
  const throughputLabel = throughput > 0 ? `~${throughput.toLocaleString()} msgs/sec` : "";
  for (let i = 0; i < layerIds.length - 1; i++) {
    lines.push(
      throughputLabel
        ? `    ${layerIds[i]} -->|"${throughputLabel}"| ${layerIds[i + 1]}`
        : `    ${layerIds[i]} --> ${layerIds[i + 1]}`
    );
  }
  lines.push(`    ${layerIds[layerIds.length - 1]} --> ${sinkId}`);

  const complianceNotes: string[] = [];
  if (design.requirements.compliance.encryption) {
    lines.push("    classDef encrypted stroke:#16a34a,stroke-width:3px;");
    layerIds.forEach((id) => lines.push(`    class ${id} encrypted;`));
    complianceNotes.push("Green border = encryption at rest/in transit enabled");
  }
  if (design.requirements.compliance.regulations.length > 0) {
    complianceNotes.push(`Regulations in scope: ${design.requirements.compliance.regulations.join(", ")}`);
  }
  if (design.requirements.compliance.data_residency) {
    complianceNotes.push(`Data residency: ${design.requirements.compliance.data_residency}`);
  }

  return { definition: lines.join("\n"), complianceNotes, isEmpty: false };
}
