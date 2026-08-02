"use client";

import { forwardRef, useCallback, useEffect, useId, useImperativeHandle, useRef, useState } from "react";
import { Download, Image as ImageIcon, Minus, Plus, RotateCcw, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { LoadingSpinner } from "@/components/shared/LoadingSpinner";
import { buildArchitectureMermaid } from "@/lib/mermaid-builder";
import { cn } from "@/lib/utils";
import type { Design } from "@/types/design";

export interface ArchitectureDiagramProps {
  design: Design;
}

/** Imperative handle so a parent page can trigger export without duplicating the logic. */
export interface ArchitectureDiagramHandle {
  downloadPng: () => Promise<void>;
  downloadSvg: () => void;
}

const MIN_SCALE = 0.4;
const MAX_SCALE = 3;

/** Adds native SVG <title> tooltips to each rendered node, keyed off its id/label text. */
function annotateNodeTooltips(svg: SVGSVGElement): void {
  const nodes = svg.querySelectorAll<SVGGElement>(".node");
  nodes.forEach((node) => {
    if (node.querySelector("title")) return;
    const labelText = node.querySelector(".nodeLabel")?.textContent?.replace(/\s+/g, " ").trim();
    if (!labelText) return;
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = labelText;
    node.appendChild(title);
  });
}

async function svgElementToPngDataUrl(svg: SVGSVGElement): Promise<string> {
  const serialized = new XMLSerializer().serializeToString(svg);
  const svgBlob = new Blob([serialized], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(svgBlob);

  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new window.Image();
      img.onload = () => resolve(img);
      img.onerror = reject;
      img.src = url;
    });

    const bbox = svg.getBoundingClientRect();
    const scaleFactor = 2; // export at 2x for crispness
    const canvas = document.createElement("canvas");
    canvas.width = (bbox.width || image.width) * scaleFactor;
    canvas.height = (bbox.height || image.height) * scaleFactor;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas is not supported in this browser.");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/png");
  } finally {
    URL.revokeObjectURL(url);
  }
}

function downloadDataUrl(dataUrl: string, filename: string): void {
  const link = document.createElement("a");
  link.href = dataUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

export const ArchitectureDiagram = forwardRef<ArchitectureDiagramHandle, ArchitectureDiagramProps>(function ArchitectureDiagram(
  { design },
  ref
) {
  const diagramId = useId().replace(/:/g, "");
  const containerRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [transform, setTransform] = useState({ scale: 1, x: 0, y: 0 });
  const dragState = useRef<{ startX: number; startY: number; originX: number; originY: number } | null>(null);

  const { definition, complianceNotes, isEmpty } = buildArchitectureMermaid(design);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      setStatus("loading");
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "strict", flowchart: { htmlLabels: false } });
        const { svg, bindFunctions } = await mermaid.render(`mermaid-${diagramId}`, definition);
        if (cancelled || !containerRef.current) return;

        containerRef.current.innerHTML = svg;
        bindFunctions?.(containerRef.current);

        const svgEl = containerRef.current.querySelector("svg");
        if (svgEl) {
          svgEl.removeAttribute("height");
          svgEl.style.maxWidth = "none";
          annotateNodeTooltips(svgEl);
        }
        setStatus("ready");
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error("Failed to render architecture diagram", err);
        if (!cancelled) setStatus("error");
      }
    }

    render();
    return () => {
      cancelled = true;
    };
  }, [definition, diagramId]);

  const zoomBy = useCallback((factor: number) => {
    setTransform((prev) => ({ ...prev, scale: Math.min(MAX_SCALE, Math.max(MIN_SCALE, prev.scale * factor)) }));
  }, []);

  const resetView = useCallback(() => setTransform({ scale: 1, x: 0, y: 0 }), []);

  const handleWheel = useCallback((event: React.WheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    const factor = event.deltaY < 0 ? 1.1 : 0.9;
    setTransform((prev) => ({ ...prev, scale: Math.min(MAX_SCALE, Math.max(MIN_SCALE, prev.scale * factor)) }));
  }, []);

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      dragState.current = { startX: event.clientX, startY: event.clientY, originX: transform.x, originY: transform.y };
      (event.target as HTMLElement).setPointerCapture(event.pointerId);
    },
    [transform.x, transform.y]
  );

  const handlePointerMove = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!dragState.current) return;
    const dx = event.clientX - dragState.current.startX;
    const dy = event.clientY - dragState.current.startY;
    setTransform((prev) => ({ ...prev, x: dragState.current!.originX + dx, y: dragState.current!.originY + dy }));
  }, []);

  const handlePointerUp = useCallback(() => {
    dragState.current = null;
  }, []);

  const handleDownloadSvg = useCallback(() => {
    const svgEl = containerRef.current?.querySelector("svg");
    if (!svgEl) return;
    const serialized = new XMLSerializer().serializeToString(svgEl);
    const blob = new Blob([serialized], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    downloadDataUrl(url, `${design.project_name.replace(/\s+/g, "-").toLowerCase()}-architecture.svg`);
    URL.revokeObjectURL(url);
  }, [design.project_name]);

  const handleDownloadPng = useCallback(async () => {
    const svgEl = containerRef.current?.querySelector("svg");
    if (!svgEl) return;
    try {
      const dataUrl = await svgElementToPngDataUrl(svgEl as SVGSVGElement);
      downloadDataUrl(dataUrl, `${design.project_name.replace(/\s+/g, "-").toLowerCase()}-architecture.png`);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("Failed to export diagram as PNG", err);
    }
  }, [design.project_name]);

  useImperativeHandle(ref, () => ({ downloadPng: handleDownloadPng, downloadSvg: handleDownloadSvg }), [
    handleDownloadPng,
    handleDownloadSvg,
  ]);

  return (
    <Card className="print:break-inside-avoid">
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle>Architecture Diagram</CardTitle>
          <CardDescription>Sources &rarr; ingestion &rarr; processing &rarr; storage &rarr; serving</CardDescription>
        </div>
        <div className="flex flex-wrap gap-2 print:hidden">
          <Button variant="outline" size="sm" onClick={() => zoomBy(1.2)} aria-label="Zoom in">
            <Plus className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" onClick={() => zoomBy(0.8)} aria-label="Zoom out">
            <Minus className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" onClick={resetView} aria-label="Reset zoom and pan">
            <RotateCcw className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" onClick={handleDownloadSvg} disabled={status !== "ready"}>
            <Download className="h-4 w-4" />
            SVG
          </Button>
          <Button variant="outline" size="sm" onClick={handleDownloadPng} disabled={status !== "ready"}>
            <ImageIcon className="h-4 w-4" />
            PNG
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {isEmpty && (
          <p className="text-sm text-muted-foreground">
            No architecture has been selected yet; the diagram will appear once generation completes.
          </p>
        )}
        {status === "error" && (
          <p role="alert" className="text-sm text-destructive">
            The architecture diagram could not be rendered.
          </p>
        )}
        <div
          ref={viewportRef}
          className={cn(
            "relative h-[420px] w-full overflow-hidden rounded-md border bg-white",
            status === "ready" ? "cursor-grab active:cursor-grabbing" : ""
          )}
          onWheel={handleWheel}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerLeave={handlePointerUp}
        >
          {status === "loading" && (
            <div className="absolute inset-0 flex items-center justify-center">
              <LoadingSpinner label="Rendering diagram..." />
            </div>
          )}
          <div
            ref={containerRef}
            className="absolute left-0 top-0 origin-top-left [&_svg]:h-auto [&_svg]:w-auto"
            style={{ transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})` }}
          />
        </div>
        {complianceNotes.length > 0 && (
          <ul className="mt-3 flex flex-col gap-1 text-xs text-muted-foreground">
            {complianceNotes.map((note) => (
              <li key={note} className="flex items-center gap-1.5">
                <ShieldCheck className="h-3 w-3" aria-hidden="true" />
                {note}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
});
