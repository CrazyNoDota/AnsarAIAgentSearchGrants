"use client";

import { useState, useEffect } from "react";
import { getRecommendations, Grant } from "@/lib/api";
import Sidebar from "@/components/Sidebar";
import GrantCard from "@/components/GrantCard";
import { Zap, Loader2, Sparkles } from "lucide-react";

const PRESET_QUERIES = [
  "AI startup funding Europe",
  "Research grants university",
  "Education technology innovation",
  "Green energy sustainability",
  "Healthcare medical research",
  "Social entrepreneurship NGO",
];

export default function RecommendationsPage() {
  const [query, setQuery] = useState("grants for organizations");
  const [results, setResults] = useState<Grant[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchRecs = async (q: string) => {
    setLoading(true);
    try {
      const data = await getRecommendations(q, 12);
      setResults(data);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchRecs(query); }, []);

  return (
    <div className="flex min-h-screen" style={{ background: "var(--bg-primary)" }}>
      <Sidebar />
      <main className="flex-1 ml-60 p-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="p-2 rounded-xl" style={{ background: "linear-gradient(135deg, rgba(124,58,237,0.2), rgba(59,130,246,0.2))" }}>
            <Zap size={22} style={{ color: "#a78bfa" }} />
          </div>
          <h1 className="text-2xl font-bold gradient-text">AI Recommendations</h1>
        </div>
        <p className="text-sm mb-8 ml-12" style={{ color: "var(--text-muted)" }}>
          Grants ranked by your team's approval history and preferences
        </p>

        {/* Query input */}
        <div className="glass-card p-5 mb-6">
          <p className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-muted)" }}>
            What are you looking for?
          </p>
          <div className="flex gap-3 mb-4">
            <input
              id="recommend-input"
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && fetchRecs(query)}
              className="input-field flex-1"
              placeholder="Describe the type of grant..."
            />
            <button
              id="get-recommendations"
              onClick={() => fetchRecs(query)}
              disabled={loading}
              className="btn-primary flex items-center gap-2 px-5">
              {loading ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
              Get Recommendations
            </button>
          </div>

          {/* Preset queries */}
          <div className="flex flex-wrap gap-2">
            {PRESET_QUERIES.map((q) => (
              <button
                key={q}
                onClick={() => { setQuery(q); fetchRecs(q); }}
                className="text-xs px-3 py-1.5 rounded-full transition-all"
                style={{
                  background: "var(--bg-primary)",
                  border: "1px solid var(--border)",
                  color: "var(--text-secondary)",
                }}>
                {q}
              </button>
            ))}
          </div>
        </div>

        {/* Results */}
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="glass-card p-5 animate-pulse">
                <div className="h-4 rounded mb-3" style={{ background: "var(--border)", width: "60%" }} />
                <div className="h-6 rounded mb-4" style={{ background: "var(--border)" }} />
                <div className="h-3 rounded" style={{ background: "var(--border)", width: "80%" }} />
              </div>
            ))}
          </div>
        ) : results.length === 0 ? (
          <div className="text-center py-20">
            <p className="text-4xl mb-4">🤖</p>
            <p style={{ color: "var(--text-secondary)" }}>No recommendations yet.</p>
            <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
              Approve some grants first so the AI can learn your preferences.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {results.map((grant, i) => (
              <div key={grant.id} className="relative">
                {i < 3 && (
                  <div className="absolute -top-2 -right-2 z-10 text-xs font-bold px-2 py-0.5 rounded-full"
                    style={{ background: "linear-gradient(135deg, #7c3aed, #3b82f6)", color: "white" }}>
                    #{i + 1}
                  </div>
                )}
                <GrantCard grant={grant} showActions={grant.status === "pending"} />
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
