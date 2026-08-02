"use client";

import { useCallback, useMemo, useState } from "react";

import {
  MAX_FILE_SIZE_BYTES,
  MAX_TOTAL_SIZE_BYTES,
  SUPPORTED_FILE_EXTENSIONS,
} from "@/lib/constants";
import { formatBytes } from "@/lib/utils";

export type UploadStatus = "idle" | "uploading" | "success" | "error";

export interface UploadableFile {
  id: string;
  file: File;
  status: UploadStatus;
  progress: number;
  error?: string;
}

function getExtension(filename: string): string {
  const idx = filename.lastIndexOf(".");
  return idx === -1 ? "" : filename.slice(idx).toLowerCase();
}

function validateFile(file: File, prospectiveTotal: number): string | null {
  const extension = getExtension(file.name);
  if (!SUPPORTED_FILE_EXTENSIONS.includes(extension as (typeof SUPPORTED_FILE_EXTENSIONS)[number])) {
    return `Unsupported file type "${extension || "unknown"}". Allowed: ${SUPPORTED_FILE_EXTENSIONS.join(", ")}`;
  }
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return `File exceeds the ${formatBytes(MAX_FILE_SIZE_BYTES)} per-file limit (${formatBytes(file.size)}).`;
  }
  if (prospectiveTotal > MAX_TOTAL_SIZE_BYTES) {
    return `Adding this file would exceed the ${formatBytes(MAX_TOTAL_SIZE_BYTES)} total upload limit.`;
  }
  return null;
}

function generateId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Manages client-side state for the multi-file drag-and-drop uploader. */
export function useFileUpload() {
  const [files, setFiles] = useState<UploadableFile[]>([]);

  const addFiles = useCallback((incoming: FileList | File[]) => {
    setFiles((prev) => {
      let runningTotal = prev.reduce((sum, f) => sum + f.file.size, 0);
      const additions: UploadableFile[] = Array.from(incoming).map((file) => {
        runningTotal += file.size;
        const error = validateFile(file, runningTotal);
        return {
          id: generateId(),
          file,
          status: error ? "error" : "idle",
          progress: 0,
          error: error ?? undefined,
        };
      });
      return [...prev, ...additions];
    });
  }, []);

  const removeFile = useCallback((id: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== id));
  }, []);

  const resetFiles = useCallback(() => {
    setFiles([]);
  }, []);

  const updateFileProgress = useCallback((id: string, progress: number) => {
    setFiles((prev) =>
      prev.map((f) => (f.id === id ? { ...f, progress, status: "uploading" } : f))
    );
  }, []);

  const markFileStatus = useCallback((id: string, status: UploadStatus, error?: string) => {
    setFiles((prev) =>
      prev.map((f) => (f.id === id ? { ...f, status, error, progress: status === "success" ? 100 : f.progress } : f))
    );
  }, []);

  const totalSize = useMemo(() => files.reduce((sum, f) => sum + f.file.size, 0), [files]);
  const hasErrors = useMemo(() => files.some((f) => f.status === "error"), [files]);
  const isValid = files.length > 0 && !hasErrors;

  return {
    files,
    setFiles,
    addFiles,
    removeFile,
    resetFiles,
    updateFileProgress,
    markFileStatus,
    totalSize,
    hasErrors,
    isValid,
  };
}
