import { useNavigate } from "react-router-dom";
import { User } from "lucide-react";

export function Avatar({ url, size = 44 }) {
  return (
    <div
      className="rounded-full bg-raised border border-line/60 overflow-hidden flex items-center justify-center shrink-0"
      style={{ width: size, height: size }}
    >
      {url ? (
        <img src={url} alt="" className="w-full h-full object-cover" />
      ) : (
        <User className="text-muted" size={size * 0.5} />
      )}
    </div>
  );
}

export function UserRow({ person, rank, metric, metricLabel }) {
  const navigate = useNavigate();
  const name = [person.first_name, person.last_name].filter(Boolean).join(" ") || person.username || "Unknown";
  return (
    <button
      onClick={() => navigate(`/user/${person.user_id}`)}
      className="w-full flex items-center gap-3 px-4 py-3 hover:bg-raised/60 rounded-xl2 tap text-left"
    >
      {rank && <span className="w-5 shrink-0 font-mono text-sm text-muted text-center">{rank}</span>}
      <Avatar url={person.profile_photo} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-paper">{name}</p>
        {person.username && <p className="truncate text-xs text-muted">@{person.username}</p>}
      </div>
      {metric != null && (
        <div className="text-right shrink-0">
          <p className="font-mono text-sm text-brand-glow">{metric}</p>
          {metricLabel && <p className="text-[10px] text-muted">{metricLabel}</p>}
        </div>
      )}
    </button>
  );
}
