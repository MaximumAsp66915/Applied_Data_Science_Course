import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Users, Music2, Mic2 } from "lucide-react";
import { api } from "../lib/api";
import TrackCard from "../components/TrackCard";
import { ArtistRow } from "../components/ArtistCard";
import { UserRow } from "../components/UserCard";
import EmptyState from "../components/EmptyState";

const TABS = [
  { key: "users", label: "People", icon: Users },
  { key: "tracks", label: "Tracks", icon: Music2 },
  { key: "artists", label: "Artists", icon: Mic2 },
];

export default function Ranks() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const scope = params.get("scope") || "users";
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      const { data } = await api.getRanks(scope);
      if (!cancelled) {
        setData(data.items ?? []);
        setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [scope]);

  return (
    <div className="pb-16">
      <header className="sticky top-0 z-20 bg-ink/85 backdrop-blur-md px-5 pt-4 pb-3 flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="w-9 h-9 rounded-full bg-surface flex items-center justify-center tap" aria-label="Back">
          <ArrowLeft size={16} className="text-muted" />
        </button>
        <h1 className="font-display text-lg text-paper">Ranks</h1>
      </header>

      <div className="rail flex gap-2 overflow-x-auto px-5 pb-1 mt-1 snap-x snap-mandatory">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setParams({ scope: key })}
            className={`snap-start shrink-0 flex items-center gap-1.5 px-3.5 py-2 rounded-full text-sm font-medium tap ${
              scope === key ? "bg-brand text-white" : "bg-surface text-muted border border-line/60"
            }`}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>

      <p className="px-5 mt-4 mb-2 eyebrow">Top 10 · most liked</p>

      <div className="flex flex-col">
        {!loading && data?.length === 0 && (
          <EmptyState title="No rankings yet" hint="Once the group starts reacting, the leaderboard fills in here." />
        )}
        {scope === "users" &&
          data?.map((u, i) => <UserRow key={u.user_id} person={u} rank={i + 1} metric={u.total_received_likes} metricLabel="likes" />)}
        {scope === "tracks" && data?.map((t, i) => <TrackCard key={t.id} track={t} variant="row" rank={i + 1} />)}
        {scope === "artists" && data?.map((a, i) => <ArtistRow key={a.id} artist={a} rank={i + 1} />)}
      </div>
    </div>
  );
}
