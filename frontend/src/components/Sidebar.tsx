"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Bot, LayoutDashboard, CheckCircle2, XCircle, Clock,
  Search, Zap, LogOut, ExternalLink, Settings
} from "lucide-react";
import { signOut } from "@/lib/auth";

const navItems = [
  { href: "/grants", label: "All Grants", icon: LayoutDashboard },
  { href: "/grants?status=pending", label: "Pending Review", icon: Clock },
  { href: "/grants?status=approved", label: "Approved", icon: CheckCircle2 },
  { href: "/grants?status=rejected", label: "Rejected", icon: XCircle },
  { href: "/search", label: "Search", icon: Search },
  { href: "/recommendations", label: "AI Recommend", icon: Zap },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside
      className="fixed left-0 top-0 h-full w-60 flex flex-col"
      style={{ background: "var(--bg-secondary)", borderRight: "1px solid var(--border)", zIndex: 50 }}>

      {/* Logo */}
      <div className="flex items-center gap-3 px-5 py-5 border-b" style={{ borderColor: "var(--border)" }}>
        <div className="flex items-center justify-center w-9 h-9 rounded-xl"
          style={{ background: "linear-gradient(135deg, #3b82f6, #7c3aed)" }}>
          <Bot size={20} color="white" />
        </div>
        <div>
          <p className="font-bold text-sm" style={{ color: "var(--text-primary)" }}>Grant Agent</p>
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>AI Dashboard</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        <p className="text-xs font-semibold uppercase tracking-wider px-3 mb-3"
          style={{ color: "var(--text-muted)" }}>Navigation</p>

        {navItems.map(({ href, label, icon: Icon }) => {
          const isActive = href === "/grants"
            ? pathname === "/grants" && !new URLSearchParams(typeof window !== "undefined" ? window.location.search : "").get("status")
            : pathname + (typeof window !== "undefined" ? window.location.search : "") === href ||
              pathname === href.split("?")[0];

          return (
            <Link key={href} href={href}
              className={`sidebar-link ${isActive ? "active" : ""}`}>
              <Icon size={17} />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="px-3 py-4 border-t space-y-1" style={{ borderColor: "var(--border)" }}>
        <a
          href={`${process.env.NEXT_PUBLIC_API_URL || ""}/docs`}
          target="_blank"
          rel="noopener noreferrer"
          className="sidebar-link"
        >
          <ExternalLink size={17} />
          API Docs
        </a>
        <button onClick={signOut} className="sidebar-link w-full text-left" style={{ color: "#ef4444" }}>
          <LogOut size={17} />
          Sign Out
        </button>
      </div>
    </aside>
  );
}
