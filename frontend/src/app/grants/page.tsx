"use client";

import { useState, useEffect, useCallback } from "react";
import { getGrants, getStats, runScraper, Grant, GrantListResponse, Stats } from "@/lib/api";
import Sidebar from "@/components/Sidebar";
import StatsWidget from "@/components/StatsWidget";
import FilterBar from "@/components/FilterBar";
import GrantCard from "@/components/GrantCard";
import { ChevronLeft, ChevronRight, RefreshCw, TrendingUp, Search } from "lucide-react";

const PAGE_SIZE = 9;

export default function GrantsPage() {
  const [grants, setGrants] = useState<Grant[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [scraping, setScraping] = useState(false);
  const [scrapeResult, setScrapeResult] = useState<string | null>(null);
  const [filters, setFilters] = useState<{ status?: string; search?: string; country?: string; category?: string }>({});

  const fetchGrants = useCallback(async () => {
    setLoading(true);
    try {
      const [data, statsData] = await Promise.all([
        getGrants({ ...filters, page, size: PAGE_SIZE }),
        getStats(),
      ]);
      setGrants(data.items);
      setTotal(data.total);
      setStats(statsData);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [filters, page]);

  useEffect(() => { fetchGrants(); }, [fetchGrants]);

  const handleFilterChange = (newFilters: typeof filters) => {
    setFilters(newFilters);
    setPage(1);
  };

  const handleScrape = async () => {
    setScraping(true);
    setScrapeResult(null);
    try {
      const result = await runScraper();
      const summary = result.summary as Record<string, number> | null;
      const added = summary ? Object.values(summary).reduce((a: number, b) => a + (b as number), 0) : "?";
      setScrapeResult(`✅ Готово — добавлено грантов: ${added}`);
      await fetchGrants();
    } catch {
      setScrapeResult("❌ Ошибка запуска. Проверьте логи.");
    } finally {
      setScraping(false);
    }
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="flex min-h-screen" style={{ background: "var(--bg-primary)" }}>
      <Sidebar />

      {/* Main content */}
      <main className="flex-1 ml-60 p-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold gradient-text flex items-center gap-2">
              <TrendingUp size={24} />
              Grant Dashboard
            </h1>
            <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
              {total} grants found
            </p>
          </div>
          <div className="flex items-center gap-2">
            {scrapeResult && (
              <span className="text-xs" style={{ color: scrapeResult.startsWith("✅") ? "#22c55e" : "#ef4444" }}>
                {scrapeResult}
              </span>
            )}
            <button onClick={handleScrape} disabled={scraping || loading}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-all disabled:opacity-50"
              style={{ border: "1px solid var(--border)", color: "var(--text-secondary)" }}
              title="Запустить парсинг всех источников грантов">
              <Search size={15} className={scraping ? "animate-pulse" : ""} />
              {scraping ? "Поиск…" : "Найти гранты"}
            </button>
            <button onClick={fetchGrants} disabled={loading}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-all"
              style={{ border: "1px solid var(--border)", color: "var(--text-secondary)" }}>
              <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
              Обновить
            </button>
          </div>
        </div>

        {/* Stats */}
        <StatsWidget stats={stats} loading={loading && !stats} />

        {/* Filters */}
        <FilterBar onFilterChange={handleFilterChange} />

        {/* Grant Grid */}
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="glass-card p-5 animate-pulse">
                <div className="h-4 rounded mb-3" style={{ background: "var(--border)", width: "60%" }} />
                <div className="h-6 rounded mb-4" style={{ background: "var(--border)" }} />
                <div className="h-3 rounded mb-2" style={{ background: "var(--border)", width: "80%" }} />
                <div className="h-3 rounded" style={{ background: "var(--border)", width: "50%" }} />
              </div>
            ))}
          </div>
        ) : grants.length === 0 ? (
          <div className="text-center py-24">
            <p className="text-4xl mb-4">🔍</p>
            <p className="text-lg font-medium" style={{ color: "var(--text-secondary)" }}>No grants found</p>
            <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>Try adjusting your filters</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {grants.map((grant) => (
              <GrantCard key={grant.id} grant={grant} onReviewed={fetchGrants} onDeleted={fetchGrants} />
            ))}
          </div>
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-3 mt-8">
            <button
              id="prev-page"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm disabled:opacity-40 transition-all"
              style={{ border: "1px solid var(--border)", color: "var(--text-secondary)" }}>
              <ChevronLeft size={16} /> Prev
            </button>
            <span className="text-sm" style={{ color: "var(--text-muted)" }}>
              Page <b style={{ color: "var(--text-primary)" }}>{page}</b> of {totalPages}
            </span>
            <button
              id="next-page"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm disabled:opacity-40 transition-all"
              style={{ border: "1px solid var(--border)", color: "var(--text-secondary)" }}>
              Next <ChevronRight size={16} />
            </button>
          </div>
        )}
      </main>
    </div>
  );
}
