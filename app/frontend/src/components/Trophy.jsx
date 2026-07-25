import { Trophy as TrophyIcon } from "lucide-react";

const RANK_STYLES = {
  legend: { bg: "bg-pulse/15", text: "text-pulse", label: "Legend" },
  gold: { bg: "bg-pulse/15", text: "text-pulse", label: "Gold" },
  silver: { bg: "bg-paper/10", text: "text-paper", label: "Silver" },
  bronze: { bg: "bg-rasp/15", text: "text-rasp", label: "Bronze" },
  unranked: { bg: "bg-line/40", text: "text-muted", label: "Unranked" },
};

export function RankBadge({ rank = "unranked" }) {
  const style = RANK_STYLES[rank?.toLowerCase()] || RANK_STYLES.unranked;
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold ${style.bg} ${style.text}`}>
      <TrophyIcon size={12} />
      {style.label}
    </span>
  );
}

export function TrophyShelf({ trophies }) {
  if (!trophies?.length) {
    return <p className="text-sm text-muted px-5">No trophies earned yet — start reacting to tracks.</p>;
  }
  return (
    <div className="rail flex gap-3 overflow-x-auto px-5 pb-1 snap-x snap-mandatory">
      {trophies.map((t) => (
        <div key={t.id} className="snap-start shrink-0 w-24 card p-3 flex flex-col items-center gap-2">
          <div className="w-10 h-10 rounded-full bg-pulse/15 flex items-center justify-center">
            <TrophyIcon size={18} className="text-pulse" />
          </div>
          <p className="text-[11px] text-center text-paper leading-tight">{t.label}</p>
        </div>
      ))}
    </div>
  );
}
