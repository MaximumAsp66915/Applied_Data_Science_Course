import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Sparkles } from "lucide-react";
import { api } from "../lib/api";
import { usePlayer } from "../context/PlayerContext";
import { Cover } from "../components/TrackCard";

export default function Suggest() {
  const navigate = useNavigate();
  const { playTrack } = usePlayer();
  const [loading, setLoading] = useState(false);
  const [suggestion, setSuggestion] = useState(null);
  const [error, setError] = useState(false);

  const fetchSuggestion = async () => {
    setLoading(true);
    setError(false);
    try {
      // Hits the recommendation engine (owned by the ML/suggestion team) via
      // our backend's thin proxy endpoint. See API_REFERENCE.md.
      const { data } = await api.getSuggestion();
      setSuggestion(data);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  const playIt = () => {
    if (!suggestion) return;
    playTrack(suggestion, "suggestion");
    navigate(`/song/${suggestion.id}`);
  };

  return (
    <div className="min-h-screen flex flex-col px-6 pt-4 pb-10">
      <div className="flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="w-9 h-9 rounded-full bg-surface flex items-center justify-center tap" aria-label="Back">
          <ArrowLeft size={16} className="text-muted" />
        </button>
        <h1 className="font-display text-lg text-paper">Suggest me a song</h1>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center text-center">
        {!suggestion && !loading && (
          <>
            <div className="w-16 h-16 rounded-full bg-brand/15 flex items-center justify-center mb-5">
              <Sparkles size={26} className="text-brand-glow" />
            </div>
            <h2 className="font-display text-2xl text-paper max-w-[16ch]">
              Based on your reactions and who you sound like
            </h2>
            <p className="text-sm text-muted mt-2 max-w-xs">
              We'll pick something the group loved that matches your taste.
            </p>
            {error && <p className="text-sm text-rasp mt-4">Couldn't get a suggestion — try again.</p>}
            <button onClick={fetchSuggestion} className="mt-7 bg-brand text-white font-semibold text-sm px-6 py-3 rounded-xl2 tap">
              Suggest a track
            </button>
          </>
        )}

        {loading && <p className="text-sm text-muted mt-8">Finding something you'll like…</p>}

        {suggestion && !loading && (
          <div className="w-full max-w-xs animate-floatUp">
            <div className="aspect-square w-full">
              <Cover url={suggestion.cover_url} size="100%" rounded="rounded-xl2" />
            </div>
            <h2 className="font-display text-xl text-paper mt-5">{suggestion.title || "Untitled track"}</h2>
            <p className="text-sm text-muted mt-1">{suggestion.performer || "Unknown artist"}</p>
            {suggestion.reason && (
              <p className="text-xs text-brand-glow mt-2 bg-brand/10 rounded-full inline-block px-3 py-1">
                {suggestion.reason}
              </p>
            )}
            <div className="mt-6 flex gap-2.5">
              <button onClick={playIt} className="flex-1 bg-brand text-white font-semibold text-sm py-3 rounded-xl2 tap">
                Play it
              </button>
              <button onClick={fetchSuggestion} className="flex-1 bg-raised text-paper font-semibold text-sm py-3 rounded-xl2 border border-line/60 tap">
                Try another
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
