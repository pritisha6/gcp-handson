"use client";

import { useRef, useState, type DragEvent } from "react";
import { AlertCircle, CheckCircle2, FileText, UploadCloud, X } from "lucide-react";

import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import type { UploadableFile } from "@/hooks/useFileUpload";
import {
  MAX_FILE_SIZE_BYTES,
  MAX_TOTAL_SIZE_BYTES,
  SUPPORTED_FILE_EXTENSIONS,
} from "@/lib/constants";
import { cn, formatBytes } from "@/lib/utils";

export interface FileUploaderProps {
  files: UploadableFile[];
  onAddFiles: (files: FileList | File[]) => void;
  onRemoveFile: (id: string) => void;
  totalSize: number;
}

export function FileUploader({ files, onAddFiles, onRemoveFile, totalSize }: FileUploaderProps) {
  const [isDragActive, setIsDragActive] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragActive(false);
    if (event.dataTransfer.files.length > 0) {
      onAddFiles(event.dataTransfer.files);
    }
  };

  const openBrowser = () => inputRef.current?.click();

  return (
    <div className="flex flex-col gap-4">
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload files by dragging and dropping, or press Enter to browse"
        onClick={openBrowser}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openBrowser();
          }
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragActive(true);
        }}
        onDragLeave={() => setIsDragActive(false)}
        onDrop={handleDrop}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          isDragActive ? "border-primary bg-accent" : "border-input hover:bg-accent/50"
        )}
      >
        <UploadCloud className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
        <p className="text-sm font-medium">Drag and drop files here, or click to browse</p>
        <p className="text-xs text-muted-foreground">
          Supported: {SUPPORTED_FILE_EXTENSIONS.join(", ")} &middot; up to{" "}
          {formatBytes(MAX_FILE_SIZE_BYTES)} per file &middot; {formatBytes(MAX_TOTAL_SIZE_BYTES)} total
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={SUPPORTED_FILE_EXTENSIONS.join(",")}
          className="sr-only"
          onChange={(event) => {
            if (event.target.files && event.target.files.length > 0) {
              onAddFiles(event.target.files);
            }
            event.target.value = "";
          }}
        />
      </div>

      {files.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {files.length} file{files.length === 1 ? "" : "s"} selected
            </span>
            <span>
              {formatBytes(totalSize)} / {formatBytes(MAX_TOTAL_SIZE_BYTES)}
            </span>
          </div>
          <ul className="flex flex-col gap-2">
            {files.map((f) => (
              <li
                key={f.id}
                className={cn(
                  "flex items-center gap-3 rounded-md border px-3 py-2",
                  f.status === "error" && "border-destructive/50 bg-destructive/5"
                )}
              >
                <FileText className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-sm font-medium" title={f.file.name}>
                      {f.file.name}
                    </p>
                    <span className="shrink-0 text-xs text-muted-foreground">
                      {formatBytes(f.file.size)}
                    </span>
                  </div>
                  {f.status === "uploading" && (
                    <Progress value={f.progress} className="mt-1.5 h-1.5" aria-label={`${f.file.name} upload progress`} />
                  )}
                  {f.status === "error" && f.error && (
                    <p role="alert" className="mt-1 flex items-center gap-1 text-xs text-destructive">
                      <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
                      {f.error}
                    </p>
                  )}
                </div>
                {f.status === "success" && (
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                )}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 shrink-0"
                  disabled={f.status === "uploading"}
                  onClick={() => onRemoveFile(f.id)}
                  aria-label={`Remove ${f.file.name}`}
                >
                  <X className="h-4 w-4" />
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
