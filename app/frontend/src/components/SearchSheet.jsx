import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Search, Music2, Mic2, Users } from "lucide-react";
import { api } from "../lib/api";
import TrackCard from "./TrackCard";
import { ArtistRow } from "./ArtistCard";
import { UserRow } from "./UserCard";
import EmptyState from "./EmptyState";

const SCOPES = [
  { key: "all", label: "Everything", icon: Search },
  { key: "tracks", label: "Songs", icon: Music2 },
  { key: "artists", label: "Artists", icon: Mic2 },
  { key: "users", label: "People", icon: Users },
];

export default function SearchSheet({ open, onClose }) {
  const [scope, setScope] = useState("all");
  const [q, setQ] = useState("");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) {
      setQ("");
      setResults(null);
      setScope("all");
    }
  }, [open]);

  useEffect(() => {
    if (!q.trim()) {
      setResults(null);
      return;
    }
    setLoading(true);
    const handle = setTimeout(async () => {
      try {
        const { data } = await api.search(q, scope);
        setResults(data);
      } finally {
        setLoading(false);
      }
    }, 300); // debounce
    return () => clearTimeout(handle);
  }, [q, scope]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-40 bg-ink flex flex-col"
        >
          <div className="px-5 pt-4 pb-3 flex items-center gap-3">
            <div className="flex-1 flex items-center gap-2 bg-surface border border-line/60 rounded-full px-4 py-2.5">
              <Search size={16} className="text-muted shrink-0" />
              <input
                autoFocus
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search songs, artists, people…"
                className="bg-transparent outline-none text-sm text-paper placeholder:text-muted flex-1"
              />
            </div>
            <button onClick={onClose} aria-label="Close search" className="w-9 h-9 rounded-full bg-surface flex items-center justify-center tap">
              <X size={16} className="text-muted" />
            </button>
          </div>

          {/* Rollable scope selector */}
          <div className="rail flex gap-2 overflow-x-auto px-5 pb-3 snap-x snap-mandatory">
            {SCOPES.map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setScope(key)}
                className={`snap-start shrink-0 flex items-center gap-1.5 px-3.5 py-2 rounded-full text-sm font-medium tap ${
                  scope === key ? "bg-brand text-white" : "bg-surface text-muted border border-line/60"
                }`}
              >
                <Icon size={14} />
                {label}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto pb-10">
            {!q.trim() && (
              <EmptyState icon={Search} title="Find your next favorite" hint="Search across everything the group has ever shared." />
            )}

            {q.trim() && loading && (
              <p className="text-center text-sm text-muted mt-8">Searching…</p>
            )}

            {q.trim() && !loading && results && (
              <div className="flex flex-col gap-6 mt-1">
                {(scope === "all" || scope === "tracks") && results.tracks?.length > 0 && (
                  <ResultGroup title="Songs">
                    {results.tracks.map((t) => (
                      <TrackCard key={t.id} track={t} variant="row" />
                    ))}
                  </ResultGroup>
                )}
                {(scope === "all" || scope === "artists") && results.artists?.length > 0 && (
                  <ResultGroup title="Artists">
                    {results.artists.map((a) => (
                      <ArtistRow key={a.id} artist={a} />
                    ))}
                  </ResultGroup>
                )}
                {(scope === "all" || scope === "users") && results.users?.length > 0 && (
                  <ResultGroup title="People">
                    {results.users.map((u) => (
                      <UserRow key={u.user_id} person={u} />
                    ))}
                  </ResultGroup>
                )}
                {!results.tracks?.length && !results.artists?.length && !results.users?.length && (
                  <EmptyState icon={Search} title="No matches" hint={`Nothing found for "${q}".`} />
                )}
              </div>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function ResultGroup({ title, children }) {
  return (
    <div>
      <p className="eyebrow px-5 mb-1">{title}</p>
      <div className="flex flex-col">{children}</div>
    </div>
  );
}
