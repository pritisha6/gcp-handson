"use client";

import { useState } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useApi } from "@/hooks/useApi";
import { apiClient } from "@/lib/api";
import { APPROVAL_ROLE_LABELS } from "@/lib/constants";
import { APPROVAL_ROLES, type Approval, type ApprovalDecisionValue, type ApprovalRole, type Design } from "@/types/design";

export interface ApprovalFormProps {
  design: Design;
  onSubmitted?: (approval: Approval) => void;
}

type ModalMode = "conditions" | "revision" | null;

/**
 * No authentication system exists yet in this app, so the approving
 * stakeholder identifies themselves via this role selector as a stand-in
 * until real auth is wired up (see lib/api.ts submitApproval for the
 * expected request contract).
 */
export function ApprovalForm({ design, onSubmitted }: ApprovalFormProps) {
  const [role, setRole] = useState<ApprovalRole>("engineer");
  const [comment, setComment] = useState("");
  const [modalMode, setModalMode] = useState<ModalMode>(null);
  const [modalComment, setModalComment] = useState("");
  const [modalError, setModalError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const { execute, loading, error } = useApi(
    (payload: { role: ApprovalRole; decision: ApprovalDecisionValue; comment?: string }) =>
      apiClient.submitApproval(design.id, payload)
  );

  const submit = async (decision: ApprovalDecisionValue, submittedComment?: string) => {
    setSubmitted(false);
    try {
      const result = await execute({ role, decision, comment: submittedComment || undefined });
      setSubmitted(true);
      setModalMode(null);
      setModalComment("");
      setComment("");
      onSubmitted?.(result);
    } catch {
      // error is already surfaced via useApi's `error`
    }
  };

  const handleModalSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (modalMode === "revision" && !modalComment.trim()) {
      setModalError("Please describe what needs to change.");
      return;
    }
    setModalError(null);
    submit(modalMode === "revision" ? "rejected" : "approved", modalComment);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Submit your decision</CardTitle>
        <CardDescription>{design.project_name}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div>
          <Label htmlFor={`approver-role-${design.id}`}>I am approving as</Label>
          <Select value={role} onValueChange={(v) => setRole(v as ApprovalRole)}>
            <SelectTrigger id={`approver-role-${design.id}`} className="mt-1 w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {APPROVAL_ROLES.map((r) => (
                <SelectItem key={r} value={r}>
                  {APPROVAL_ROLE_LABELS[r]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label htmlFor={`approval-comment-${design.id}`}>Comments (optional)</Label>
          <Textarea
            id={`approval-comment-${design.id}`}
            rows={3}
            placeholder="Any notes for the record..."
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
        </div>

        <div className="flex flex-wrap gap-2">
          <Button onClick={() => submit("approved", comment)} disabled={loading}>
            {loading && <Loader2 className="h-4 w-4 animate-spin" />}
            Approve
          </Button>
          <Button variant="outline" onClick={() => setModalMode("conditions")} disabled={loading}>
            Approve with Conditions
          </Button>
          <Button variant="secondary" onClick={() => setModalMode("revision")} disabled={loading}>
            Needs Revision
          </Button>
        </div>

        {submitted && (
          <p role="status" className="flex items-center gap-1.5 text-sm text-success">
            <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
            Your decision was recorded.
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </CardContent>

      <Dialog
        open={modalMode !== null}
        onOpenChange={(open) => {
          if (!open) {
            setModalMode(null);
            setModalComment("");
            setModalError(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{modalMode === "revision" ? "Request revision" : "Approve with conditions"}</DialogTitle>
            <DialogDescription>
              {modalMode === "revision"
                ? "Describe what needs to change before this design can be approved."
                : "Note any conditions attached to this approval."}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleModalSubmit} className="flex flex-col gap-3">
            <div>
              <Label htmlFor="modal-comment">Comments {modalMode === "revision" ? "(required)" : "(optional)"}</Label>
              <Textarea
                id="modal-comment"
                rows={4}
                value={modalComment}
                onChange={(e) => setModalComment(e.target.value)}
                aria-invalid={!!modalError}
              />
              {modalError && (
                <p role="alert" className="mt-1 text-sm text-destructive">
                  {modalError}
                </p>
              )}
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setModalMode(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={loading}>
                {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                {modalMode === "revision" ? "Submit revision request" : "Approve with conditions"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
