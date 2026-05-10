"use client";

import { Stats } from "@/lib/api";
import { Clock, CheckCircle2, XCircle, Package } from "lucide-react";

const statCards = [
  { key: "total",    label: "Total Grants",    icon: Package,      color: "#60a5fa", bg: "rgba(96,165,250,0.1)"  },
  { key: "pending",  label: "Pending Review",  icon: Clock,        color: "#f59e0b", bg: "rgba(245,158,11,0.1)"  },
  { key: "approved", label: "Approved",        icon: CheckCircle2, color: "#22c55e", bg: "rgba(34,197,94,0.1)"   },
  { key: "rejected", label: "Rejected",        icon: XCircle,      color: "#ef4444", bg: "rgba(239,68,68,0.1)"   },
];

interface StatsWidgetProps {
  stats: Stats | null;
  loading?: boolean;
}

export default function StatsWidget({ stats, loading }: StatsWidgetProps) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
      {statCards.map(({ key, label, icon: Icon, color, bg }) => (
        <div key={key} className="glass-card p-4 animate-fade-in-up"
          style={{ transition: "transform 0.2s" }}
          onMouseEnter={(e) => (e.currentTarget.style.transform = "translateY(-2px)")}
          onMouseLeave={(e) => (e.currentTarget.style.transform = "translateY(0)")}>
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-medium" style={{ color: "var(--text-muted)" }}>{label}</p>
            <div className="p-2 rounded-lg" style={{ background: bg }}>
              <Icon size={16} style={{ color }} />
            </div>
          </div>
          {loading ? (
            <div className="h-7 w-12 rounded animate-pulse" style={{ background: "var(--border)" }} />
          ) : (
            <p className="text-2xl font-bold" style={{ color }}>
              {stats?.[key as keyof Stats] ?? 0}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
