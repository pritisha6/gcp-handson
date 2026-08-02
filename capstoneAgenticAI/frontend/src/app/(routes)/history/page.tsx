"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, Copy, Download, ExternalLink, FileDown, ThumbsUp, Trash2 } from "lucide-react";

import { AlertsWidget } from "@/components/analytics/AlertsWidget";
import { MetricsDashboard } from "@/components/analytics/MetricsDashboard";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/hooks/useApi";
import { useApprovalRates } from "@/hooks/useApprovalRates";
import { apiClient } from "@/lib/api";
import { extractCompliancePct, extractCoveragePct } from "@/lib/design-adapters";
import type { Design, DesignStatus } from "@/types/design";

interface HistoryRow {
  design: Design;
  coveragePct: number | null;
  compliancePct: number | null;
  approvalRatePct: number | null;
  totalCostUsd: number | null;
}

function exportDesignJson(design: Design): void {
  const blob = new Blob([JSON.stringify(design, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${design.project_name.replace(/\s+/g, "-").toLowerCase()}.json`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function formatPct(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)}%`;
}

function csvCell(value: string | number | null): string {
  if (value === null) return "";
  const str = String(value);
  return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
}

function exportRowsAsCsv(rows: HistoryRow[]): void {
  const headers = ["Date", "Project", "Status", "Coverage %", "Approval Rate %", "Cost USD/mo", "Compliance %"];
  const lines = [
    headers.join(","),
    ...rows.map((row) =>
      [
        csvCell(new Date(row.design.created_at).toISOString().slice(0, 10)),
        csvCell(row.design.project_name),
        csvCell(row.design.status),
        csvCell(row.coveragePct),
        csvCell(row.approvalRatePct),
        csvCell(row.totalCostUsd),
        csvCell(row.compliancePct),
      ].join(",")
    ),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `design-history-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export default function HistoryPage() {
  const { data, loading, error, execute } = useApi(() => apiClient.listDesigns({ limit: 100 }));
  const { data: metrics, execute: fetchMetrics } = useApi(() => apiClient.getMetrics());
  const { data: alerts, execute: fetchAlerts } = useApi(() => apiClient.getAlerts());
  const { execute: cloneDesign } = useApi((design: Design) =>
    apiClient.createDesign({ project_name: `${design.project_name} (Copy)`, requirements: design.requirements })
  );
  const { execute: deleteDesignApi } = useApi((id: string) => apiClient.deleteDesign(id));

  const [statusFilter, setStatusFilter] = useState<DesignStatus | "all">("all");
  const [minCostUsd, setMinCostUsd] = useState("");
  const [maxCostUsd, setMaxCostUsd] = useState("");
  const [minCoveragePct, setMinCoveragePct] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "date", desc: true }]);
  const [cloningId, setCloningId] = useState<string | null>(null);

  useEffect(() => {
    execute().catch(() => {});
    fetchMetrics().catch(() => {});
    fetchAlerts().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const designs = useMemo(() => data?.items ?? [], [data]);
  const approvalRates = useApprovalRates(useMemo(() => designs.map((d) => d.id), [designs]));

  const rows: HistoryRow[] = useMemo(
    () =>
      designs.map((design) => ({
        design,
        coveragePct: extractCoveragePct(design.validation_results),
        compliancePct: extractCompliancePct(design.validation_results),
        approvalRatePct: approvalRates.get(design.id) ?? null,
        totalCostUsd: design.output?.cost_analysis?.total_usd ?? null,
      })),
    [designs, approvalRates]
  );

  const filteredRows = useMemo(() => {
    return rows.filter(({ design, coveragePct, totalCostUsd }) => {
      if (statusFilter !== "all" && design.status !== statusFilter) return false;
      if (dateFrom && new Date(design.created_at) < new Date(dateFrom)) return false;
      if (dateTo && new Date(design.created_at) > new Date(dateTo)) return false;
      if (minCostUsd && (totalCostUsd === null || totalCostUsd < Number(minCostUsd))) return false;
      if (maxCostUsd && (totalCostUsd === null || totalCostUsd > Number(maxCostUsd))) return false;
      if (minCoveragePct && (coveragePct === null || coveragePct < Number(minCoveragePct))) return false;
      return true;
    });
  }, [rows, statusFilter, dateFrom, dateTo, minCostUsd, maxCostUsd, minCoveragePct]);

  async function handleClone(design: Design) {
    setCloningId(design.id);
    try {
      await cloneDesign(design);
      await execute();
    } catch {
      // error surfaced via useApi's own error state on next render attempt
    } finally {
      setCloningId(null);
    }
  }

  async function handleDelete(design: Design) {
    if (typeof window !== "undefined" && !window.confirm(`Delete "${design.project_name}"?`)) return;
    try {
      await deleteDesignApi(design.id);
      await execute();
    } catch {
      // no-op: transient errors are fine to retry manually
    }
  }

  const columns = useMemo<ColumnDef<HistoryRow>[]>(
    () => [
      {
        id: "date",
        header: "Date",
        accessorFn: (row) => row.design.created_at,
        cell: ({ getValue }) => new Date(getValue<string>()).toLocaleDateString(),
      },
      {
        id: "project",
        header: "Project",
        accessorFn: (row) => row.design.project_name,
        cell: ({ row }) => (
          <Link href={`/design/${row.original.design.id}`} className="font-medium hover:underline">
            {row.original.design.project_name}
          </Link>
        ),
      },
      {
        id: "status",
        header: "Status",
        accessorFn: (row) => row.design.status,
        cell: ({ getValue }) => (
          <Badge variant="secondary" className="capitalize">
            {getValue<string>().replace("_", " ")}
          </Badge>
        ),
      },
      {
        id: "coverage",
        header: "Coverage",
        accessorFn: (row) => row.coveragePct ?? -1,
        cell: ({ row }) => formatPct(row.original.coveragePct),
      },
      {
        id: "approval",
        header: "Approval Rate",
        accessorFn: (row) => row.approvalRatePct ?? -1,
        cell: ({ row }) => formatPct(row.original.approvalRatePct),
      },
      {
        id: "cost",
        header: "Cost",
        accessorFn: (row) => row.totalCostUsd ?? -1,
        cell: ({ row }) =>
          row.original.totalCostUsd !== null ? `$${row.original.totalCostUsd.toLocaleString()}/mo` : "—",
      },
      {
        id: "compliance",
        header: "Compliance",
        accessorFn: (row) => row.compliancePct ?? -1,
        cell: ({ row }) => formatPct(row.original.compliancePct),
      },
      {
        id: "actions",
        header: "Actions",
        enableSorting: false,
        cell: ({ row }) => {
          const design = row.original.design;
          return (
            <div className="flex items-center gap-1">
              <Button asChild variant="ghost" size="icon" className="h-8 w-8" aria-label="View design">
                <Link href={`/design/${design.id}`}>
                  <ExternalLink className="h-4 w-4" />
                </Link>
              </Button>
              <Button asChild variant="ghost" size="icon" className="h-8 w-8" aria-label="Approve design">
                <Link href={`/approval?designId=${design.id}`}>
                  <ThumbsUp className="h-4 w-4" />
                </Link>
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                aria-label="Export design as JSON"
                onClick={() => exportDesignJson(design)}
              >
                <Download className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                aria-label="Clone design"
                disabled={cloningId === design.id}
                onClick={() => handleClone(design)}
              >
                <Copy className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-destructive hover:text-destructive"
                aria-label="Delete design"
                onClick={() => handleDelete(design)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          );
        },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [cloningId]
  );

  const table = useReactTable({
    data: filteredRows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 10 } },
  });

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Design History</h1>
        <p className="mt-1 text-sm text-muted-foreground">Every design generated, with filters, sorting, and quick actions.</p>
      </div>

      <AlertsWidget alerts={alerts ?? []} />

      <MetricsDashboard metrics={metrics ?? null} />

      <div>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold">All designs</h2>
          <Button variant="outline" size="sm" onClick={() => exportRowsAsCsv(filteredRows)} disabled={filteredRows.length === 0}>
            <FileDown className="h-4 w-4" />
            Export filtered results (CSV)
          </Button>
        </div>

        <div className="mb-4 grid grid-cols-2 gap-3 rounded-md border p-4 sm:grid-cols-3 lg:grid-cols-6">
          <div>
            <Label htmlFor="filter-status">Status</Label>
            <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as DesignStatus | "all")}>
              <SelectTrigger id="filter-status" className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All</SelectItem>
                <SelectItem value="pending">Pending</SelectItem>
                <SelectItem value="in_progress">In progress</SelectItem>
                <SelectItem value="completed">Completed</SelectItem>
                <SelectItem value="failed">Failed</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label htmlFor="filter-date-from">From</Label>
            <Input id="filter-date-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="mt-1" />
          </div>
          <div>
            <Label htmlFor="filter-date-to">To</Label>
            <Input id="filter-date-to" type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="mt-1" />
          </div>
          <div>
            <Label htmlFor="filter-min-cost">Min cost ($)</Label>
            <Input id="filter-min-cost" type="number" min={0} value={minCostUsd} onChange={(e) => setMinCostUsd(e.target.value)} className="mt-1" />
          </div>
          <div>
            <Label htmlFor="filter-max-cost">Max cost ($)</Label>
            <Input id="filter-max-cost" type="number" min={0} value={maxCostUsd} onChange={(e) => setMaxCostUsd(e.target.value)} className="mt-1" />
          </div>
          <div>
            <Label htmlFor="filter-min-coverage">Min coverage (%)</Label>
            <Input
              id="filter-min-coverage"
              type="number"
              min={0}
              max={100}
              value={minCoveragePct}
              onChange={(e) => setMinCoveragePct(e.target.value)}
              className="mt-1"
            />
          </div>
        </div>

        {loading && (
          <div className="flex justify-center py-16">
            <LoadingSpinner label="Loading designs..." />
          </div>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        {!loading && !error && (
          <>
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => {
                      const canSort = header.column.getCanSort();
                      const sortState = header.column.getIsSorted();
                      return (
                        <TableHead
                          key={header.id}
                          className={canSort ? "cursor-pointer select-none" : undefined}
                          onClick={header.column.getToggleSortingHandler()}
                        >
                          <span className="flex items-center gap-1">
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {canSort &&
                              (sortState === "asc" ? (
                                <ArrowUp className="h-3 w-3" />
                              ) : sortState === "desc" ? (
                                <ArrowDown className="h-3 w-3" />
                              ) : (
                                <ArrowUpDown className="h-3 w-3 opacity-40" />
                              ))}
                          </span>
                        </TableHead>
                      );
                    })}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {table.getRowModel().rows.map((row) => (
                  <TableRow key={row.id}>
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                    ))}
                  </TableRow>
                ))}
                {filteredRows.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={columns.length} className="text-center text-muted-foreground">
                      No designs match these filters.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>

            <div className="mt-4 flex items-center justify-between text-sm">
              <span className="text-muted-foreground">
                Page {table.getState().pagination.pageIndex + 1} of {Math.max(1, table.getPageCount())}
              </span>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>
                  Previous
                </Button>
                <Button variant="outline" size="sm" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>
                  Next
                </Button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
