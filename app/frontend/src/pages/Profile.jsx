import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ThumbsUp, ThumbsDown, Music2, Lock, Globe } from "lucide-react";
import { api } from "../lib/api";
import { useUser } from "../context/UserContext";
import { Avatar } from "../components/UserCard";
import { RankBadge, TrophyShelf } from "../components/Trophy";
import RollableRail from "../components/RollableRail";
import TrackCard from "../components/TrackCard";
import { UserRow } from "../components/UserCard";
import { ArtistRailCard } from "../components/ArtistCard";
import EmptyState from "../components/EmptyState";

export default function Profile() {
  const { userId } = useParams();
  const navigate = useNavigate();
  const { profile: me } = useUser();

  const [person, setPerson] = useState(null);
  const [stats, setStats] = useState(null);
  const [relations, setRelations] = useState(null);
  const [tracks, setTracks] = useState([]);
  const [likedTracks, setLikedTracks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [visibilitySaving, setVisibilitySaving] = useState(false);

  const isSelf = !userId || (me && !me.isGuest && String(me.user_id) === String(userId));
  const isPrivateView = !isSelf && person?.is_private_view;
  const targetId = userId || me?.user_id;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setStats(null);
    setRelations(null);
    setTracks([]);
    setLikedTracks([]);
    (async () => {
      try {
        const targetId = userId || me?.user_id;
        if (!targetId) return; // guest with no id yet

        const userRes = await (isSelf ? api.getMe() : api.getUser(targetId));
        if (cancelled) return;
        setPerson(userRes.data);

        // A private profile viewed by someone other than its owner: the
        // backend already withheld everything but name/avatar, so don't
        // even ask for stats/relations/tracks -- they'd just 403.
        if (!isSelf && userRes.data.is_private_view) {
          return;
        }

        const [statsRes, relRes, tracksRes, likedTracksRes] = await Promise.all([
          api.getUserStats(targetId),
          api.getUserRelations(targetId),
          api.getUserTracks(targetId),
          api.getUserLikedTracks(targetId),
        ]);
        if (cancelled) return;
        setStats(statsRes.data);
        setRelations(relRes.data);
        setTracks(tracksRes.data.items ?? []);
        setLikedTracks(likedTracksRes.data.items ?? []);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [userId, me, isSelf]);

  const toggleVisibility = async () => {
    if (!person || visibilitySaving) return;
    const nextValue = !person.is_public;
    setVisibilitySaving(true);
    setPerson((p) => ({ ...p, is_public: nextValue })); // optimistic
    try {
      await api.setVisibility(nextValue);
    } catch {
      setPerson((p) => ({ ...p, is_public: !nextValue })); // revert on failure
    } finally {
      setVisibilitySaving(false);
    }
  };

  if (me?.isGuest && isSelf) {
    return (
      <div className="pb-16">
        <PageHeader onBack={() => navigate(-1)} title="Profile" />
        <EmptyState
          icon={Music2}
          title="Open this from Telegram"
          hint="We couldn't verify a Telegram account, so there's no profile to show yet."
        />
      </div>
    );
  }

  const name = person ? [person.first_name, person.last_name].filter(Boolean).join(" ") : "";

  return (
    <div className="pb-28">
      <PageHeader onBack={() => navigate(-1)} title={isSelf ? "Your profile" : name || "Profile"} />

      <section className="px-5 flex items-center gap-4 mt-2">
        <Avatar url={person?.profile_photo} size={64} />
        <div className="min-w-0">
          <h1 className="font-display text-xl text-paper truncate">{loading ? "…" : name || "Unknown listener"}</h1>
          {person?.username && <p className="text-sm text-muted truncate">@{person.username}</p>}
          {!isPrivateView && <div className="mt-1.5"><RankBadge rank={stats?.rank} /></div>}
        </div>
      </section>

      {isSelf && person && (
        <section className="px-5 mt-4">
          <button
            onClick={toggleVisibility}
            disabled={visibilitySaving}
            className="w-full card p-3 flex items-center gap-3 tap disabled:opacity-60 text-left"
          >
            {person.is_public ? (
              <Globe size={16} className="text-brand-glow shrink-0" />
            ) : (
              <Lock size={16} className="text-muted shrink-0" />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-paper">
                {person.is_public ? "Public profile" : "Private profile"}
              </p>
              <p className="text-xs text-muted">
                {person.is_public
                  ? "Anyone can open your profile from your name or avatar."
                  : "Only you can see your profile, stats, and community pulse."}
              </p>
            </div>
          </button>
        </section>
      )}

      {isPrivateView ? (
        <EmptyState
          icon={Lock}
          title="This profile is private"
          hint={`${name || "This listener"} has chosen to keep their stats and community pulse private.`}
        />
      ) : (
        <>
          {/* Score stat grid */}
          <section className="px-5 mt-5 grid grid-cols-3 gap-2">
            <Stat label="Score" value={stats?.score ?? "—"} />
            <Stat label="Tracks shared" value={stats?.total_uploaded_tracks ?? 0} />
            <Stat label="Reactions" value={stats?.total_reactions ?? 0} />
          </section>

          <section className="px-5 mt-2 grid grid-cols-2 gap-2">
            <Stat label="Likes received" value={stats?.total_received_likes ?? 0} icon={ThumbsUp} tone="text-pulse" />
            <Stat label="Dislikes received" value={stats?.total_received_dislikes ?? 0} icon={ThumbsDown} tone="text-rasp" />
          </section>

          <section className="mt-7 px-5">
            <p className="eyebrow mb-2">Trophies</p>
            <TrophyShelf trophies={stats?.trophies} />
          </section>

          <RollableRail
            eyebrow="Personal catalog"
            title="Songs shared, most popular first"
            empty={!loading && "Hasn't shared any songs yet."}
          >
            {tracks.map((t) => (
              <TrackCard key={t.id} track={t} context={`profile_sent:${targetId}`} />
            ))}
          </RollableRail>

          <RollableRail
            eyebrow="Taste breakdown"
            title="Artists liked most"
            empty={!loading && "No liked artists yet."}
          >
            {relations?.top_liked_artists?.map((a) => (
              <ArtistRailCard key={a.id} artist={a} />
            ))}
          </RollableRail>

          <RollableRail
            eyebrow="Taste breakdown"
            title="Liked tracks, most popular first"
            empty={!loading && "No liked tracks yet."}
          >
            {likedTracks.map((t) => (
              <TrackCard key={t.id} track={t} context={`profile_liked:${targetId}`} />
            ))}
          </RollableRail>

          {/* --- Statistics: relations to the rest of the group --- */}
          <section className="mt-8 px-5">
            <p className="eyebrow mb-1">Community pulse</p>
            <h2 className="font-display text-lg text-paper mb-3">How {isSelf ? "you" : "they"} connect with the group</h2>
          </section>

          <CommunityPulseLists relations={relations} />
        </>
      )}
    </div>
  );
}

function PageHeader({ onBack, title }) {
  return (
    <header className="sticky top-0 z-20 bg-ink/85 backdrop-blur-md px-5 pt-4 pb-3 flex items-center gap-3">
      <button onClick={onBack} className="w-9 h-9 rounded-full bg-surface flex items-center justify-center tap" aria-label="Back">
        <ArrowLeft size={16} className="text-muted" />
      </button>
      <h1 className="font-display text-lg text-paper">{title}</h1>
    </header>
  );
}

function Stat({ label, value, icon: Icon, tone = "text-paper" }) {
  return (
    <div className="card p-3">
      <div className={`flex items-center gap-1.5 font-mono text-lg ${tone}`}>
        {Icon && <Icon size={14} />}
        {value}
      </div>
      <p className="text-[11px] text-muted mt-0.5">{label}</p>
    </div>
  );
}

// Below 3 entries, a list isn't really telling anyone anything yet -- rather
// than showing four separate "not enough data" cards, whichever of the four
// relation lists are still this sparse get folded into one combined line.
const MIN_ENTRIES_TO_SHOW = 3;

function CommunityPulseLists({ relations }) {
  const candidates = [
    { key: "top_likers", title: "Got most likes from", metricLabel: "likes given" },
    { key: "top_dislikers", title: "Got most dislikes from", metricLabel: "dislikes given" },
    { key: "gave_most_likes_to", title: "Give the most likes to", metricLabel: "likes given" },
    { key: "gave_most_dislikes_to", title: "Give the most dislikes to", metricLabel: "dislikes given" },
  ];

  const populated = candidates.filter((c) => (relations?.[c.key]?.length ?? 0) >= MIN_ENTRIES_TO_SHOW);
  const sparse = candidates.filter((c) => (relations?.[c.key]?.length ?? 0) < MIN_ENTRIES_TO_SHOW);

  return (
    <>
      {populated.map((c) => (
        <RollableList key={c.key} title={c.title} people={relations[c.key]} metricLabel={c.metricLabel} />
      ))}

      {sparse.length > 0 && (
        <section className="mt-6">
          <div className="mx-5 card px-4 py-5 text-center text-sm text-muted">
            Not enough data yet for {sparse.length === candidates.length ? "the community pulse" : sparse.map((c) => c.title.toLowerCase()).join(", ")}.
          </div>
        </section>
      )}
    </>
  );
}

function RollableList({ title, people, metricLabel }) {
  return (
    <section className="mt-6">
      <p className="px-5 font-display text-base text-paper mb-2">{title}</p>
      <div className="flex flex-col">
        {people.map((p, i) => (
          <UserRow key={p.user_id} person={p} rank={i + 1} metric={p.metric} metricLabel={metricLabel} />
        ))}
      </div>
    </section>
  );
}
