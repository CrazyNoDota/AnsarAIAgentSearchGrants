"use client";

import { Grant, reviewGrant, deleteGrant } from "@/lib/api";
import { ExternalLink, CheckCircle2, XCircle, Calendar, Building2, Globe, Tag, Trash2 } from "lucide-react";
import { useState } from "react";

interface GrantCardProps {
  grant: Grant;
  onReviewed?: () => void;
  onDeleted?: () => void;
  showActions?: boolean;
}

function DeadlineBadge({ deadline }: { deadline?: string }) {
  if (!deadline) return <span style={{ color: "var(--text-muted)" }}>No deadline</span>;

  const d = new Date(deadline);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const daysLeft = Math.ceil((d.getTime() - today.getTime()) / (1000 * 86400));

  let color = "#22c55e";
  let label = `${daysLeft}d left`;
  if (daysLeft < 0) { color = "#475569"; label = "Expired"; }
  else if (daysLeft <= 3) { color = "#ef4444"; label = `${daysLeft}d left ⚠️`; }
  else if (daysLeft <= 7) { color = "#f59e0b"; label = `${daysLeft}d left`; }

  return (
    <span style={{ color }}>
      {deadline.slice(0, 10)} ({label})
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`badge badge-${status}`}>{status}</span>;
}

export default function GrantCard({ grant, onReviewed, onDeleted, showActions = true }: GrantCardProps) {
  const [loading, setLoading] = useState<"approve" | "reject" | "delete" | null>(null);
  const [done, setDone] = useState<null | "approved" | "rejected" | "deleted">(null);
  const [error, setError] = useState<string | null>(null);

  const handleReview = async (decision: "approved" | "rejected") => {
    setLoading(decision === "approved" ? "approve" : "reject");
    setError(null);
    try {
      await reviewGrant(grant.id, decision);
      setDone(decision);
      onReviewed?.();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      setError(`Failed to submit decision: ${msg}`);
    } finally {
      setLoading(null);
    }
  };

  const handleDelete = async () => {
    if (typeof window !== "undefined") {
      const ok = window.confirm(
        `Delete this grant permanently?\n\n"${grant.title}"\n\nThis cannot be undone.`
      );
      if (!ok) return;
    }
    setLoading("delete");
    setError(null);
    try {
      await deleteGrant(grant.id);
      setDone("deleted");
      onDeleted?.();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Unknown error";
      setError(`Failed to delete: ${msg}`);
    } finally {
      setLoading(null);
    }
  };

  const scoreStars = Math.min(5, Math.max(0, Math.round(grant.ai_score / 10)));

  return (
    <div className="glass-card p-5 animate-fade-in-up"
      style={{ transition: "transform 0.2s, box-shadow 0.2s" }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = "translateY(-2px)";
        e.currentTarget.style.boxShadow = "0 8px 32px rgba(0,0,0,0.3)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = "translateY(0)";
        e.currentTarget.style.boxShadow = "none";
      }}>

      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <StatusBadge status={grant.status} />
            {grant.ai_score > 0 && (
              <span className="text-xs" style={{ color: "#f59e0b" }}>
                {"⭐".repeat(scoreStars)}
                <span className="ml-1 opacity-60">({grant.ai_score.toFixed(1)})</span>
              </span>
            )}
          </div>
          <h3 className="font-semibold text-base leading-tight line-clamp-2"
            style={{ color: "var(--text-primary)" }}>
            {grant.title}
          </h3>
        </div>
        <a href={grant.source_url} target="_blank" rel="noopener noreferrer"
          className="flex-shrink-0 p-2 rounded-lg transition-colors"
          style={{ color: "var(--text-muted)" }}
          title="Open original grant">
          <ExternalLink size={16} />
        </a>
      </div>

      {/* Meta */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 mb-3 text-xs" style={{ color: "var(--text-secondary)" }}>
        {grant.organization && (
          <div className="flex items-center gap-1.5">
            <Building2 size={13} style={{ color: "var(--text-muted)", flexShrink: 0 }} />
            <span className="truncate">{grant.organization}</span>
          </div>
        )}
        {grant.country && (
          <div className="flex items-center gap-1.5">
            <Globe size={13} style={{ color: "var(--text-muted)", flexShrink: 0 }} />
            <span className="truncate">{grant.country}</span>
          </div>
        )}
        {grant.category && (
          <div className="flex items-center gap-1.5">
            <Tag size={13} style={{ color: "var(--text-muted)", flexShrink: 0 }} />
            <span className="truncate">{grant.category}</span>
          </div>
        )}
        <div className="flex items-center gap-1.5">
          <Calendar size={13} style={{ color: "var(--text-muted)", flexShrink: 0 }} />
          <DeadlineBadge deadline={grant.deadline} />
        </div>
      </div>

      {/* Description */}
      {grant.description && (
        <p className="text-xs line-clamp-2 mb-3" style={{ color: "var(--text-muted)" }}>
          {grant.description}
        </p>
      )}

      {/* Actions */}
      {!done && (
        <div className="flex gap-2 pt-3 border-t" style={{ borderColor: "var(--border)" }}>
          {showActions && grant.status === "pending" && (
            <>
              <button
                id={`approve-grant-${grant.id}`}
                onClick={() => handleReview("approved")}
                disabled={!!loading}
                className="btn-success flex items-center gap-1.5 flex-1 justify-center">
                {loading === "approve" ? (
                  <div className="w-3 h-3 border border-green-500 border-t-transparent rounded-full animate-spin" />
                ) : <CheckCircle2 size={14} />}
                Approve
              </button>
              <button
                id={`reject-grant-${grant.id}`}
                onClick={() => handleReview("rejected")}
                disabled={!!loading}
                className="btn-danger flex items-center gap-1.5 flex-1 justify-center">
                {loading === "reject" ? (
                  <div className="w-3 h-3 border border-red-500 border-t-transparent rounded-full animate-spin" />
                ) : <XCircle size={14} />}
                Reject
              </button>
            </>
          )}
          <button
            id={`delete-grant-${grant.id}`}
            onClick={handleDelete}
            disabled={!!loading}
            title="Delete this grant"
            className="flex items-center justify-center px-3 py-2 rounded-lg text-xs transition-all"
            style={{
              border: "1px solid var(--border)",
              color: "var(--text-muted)",
              background: "transparent",
            }}>
            {loading === "delete" ? (
              <div className="w-3 h-3 border border-current border-t-transparent rounded-full animate-spin" />
            ) : <Trash2 size={14} />}
          </button>
        </div>
      )}

      {done === "approved" && (
        <div className="pt-3 border-t text-xs text-center font-medium" style={{ borderColor: "var(--border)", color: "#22c55e" }}>
          ✅ Approved — saved successfully
        </div>
      )}
      {done === "rejected" && (
        <div className="pt-3 border-t text-xs text-center font-medium" style={{ borderColor: "var(--border)", color: "#ef4444" }}>
          ❌ Rejected — saved successfully
        </div>
      )}
      {done === "deleted" && (
        <div className="pt-3 border-t text-xs text-center font-medium" style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}>
          🗑 Deleted
        </div>
      )}
      {error && (
        <div className="pt-3 border-t text-xs" style={{ borderColor: "var(--border)", color: "#ef4444" }}>
          ⚠️ {error}
        </div>
      )}
    </div>
  );
}
