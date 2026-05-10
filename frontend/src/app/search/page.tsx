"use client";

import { useState } from "react";
import { getGrants, getRecommendations, Grant } from "@/lib/api";
import Sidebar from "@/components/Sidebar";
import GrantCard from "@/components/GrantCard";
import { Search, Zap, Loader2 } from "lucide-react";

type Mode = "search" | "recommend";

export default function SearchPage() {
  const [mode, setMode] = useState<Mode>("search");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Grant[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  const handleSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setSearched(false);

    try {
      if (mode === "search") {
        const data = await getGrants({ search: query, size: 12 });
        setResults(data.items);
      } else {
        const data = await getRecommendations(query, 12);
        setResults(data);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
      setSearched(true);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSearch();
  };

  return (
    <div className="flex min-h-screen" style={{ background: "var(--bg-primary)" }}>
      <Sidebar />
      <main className="flex-1 ml-60 p-8">
        <div className="max-w-4xl mx-auto">
          <h1 className="text-2xl font-bold gradient-text mb-2">Grant Search</h1>
          <p className="text-sm mb-8" style={{ color: "var(--text-muted)" }}>
            Search all grants or use AI recommendations based on your preferences
          </p>

          {/* Mode toggle */}
          <div className="glass-card p-1 inline-flex rounded-xl mb-6" style={{ gap: 4 }}>
            <button
              id="mode-search"
              onClick={() => setMode("search")}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${mode === "search" ? "text-white" : ""}`}
              style={mode === "search" ? { background: "var(--accent)" } : { color: "var(--text-secondary)" }}>
              <Search size={15} /> Keyword Search
            </button>
            <button
              id="mode-recommend"
              onClick={() => setMode("recommend")}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${mode === "recommend" ? "text-white" : ""}`}
              style={mode === "recommend" ? { background: "linear-gradient(135deg, #7c3aed, #3b82f6)" } : { color: "var(--text-secondary)" }}>
              <Zap size={15} /> AI Recommend
            </button>
          </div>

          {/* Search input */}
          <div className="glass-card p-4 mb-6">
            <div className="flex gap-3">
              <div className="relative flex-1">
                {mode === "search"
                  ? <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: "var(--text-muted)" }} />
                  : <Zap size={16} className="absolute left-3 top-1/2 -translate-y-1/2" style={{ color: "#a78bfa" }} />
                }
                <input
                  id="search-input"
                  type="text"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={handleKeyDown}
                  className="input-field pl-9"
                  placeholder={
                    mode === "search"
                      ? "Search by title, organization, description..."
                      : "Describe what you need: 'AI grants for education startups in Europe'"
                  }
                />
              </div>
              <button
                id="search-submit"
                onClick={handleSearch}
                disabled={loading || !query.trim()}
                className="btn-primary flex items-center gap-2 px-6 disabled:opacity-50">
                {loading ? <Loader2 size={16} className="animate-spin" /> : mode === "search" ? <Search size={16} /> : <Zap size={16} />}
                {mode === "search" ? "Search" : "Find"}
              </button>
            </div>

            {mode === "recommend" && (
              <p className="text-xs mt-3" style={{ color: "var(--text-muted)" }}>
                💡 AI recommendations learn from your team's approval history to prioritize the most relevant grants.
              </p>
            )}
          </div>

          {/* Results */}
          {searched && (
            <div>
              <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>
                {results.length > 0
                  ? `Found ${results.length} result${results.length !== 1 ? "s" : ""} for "${query}"`
                  : `No results found for "${query}"`}
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {results.map((grant) => (
                  <GrantCard key={grant.id} grant={grant} showActions={grant.status === "pending"} />
                ))}
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
