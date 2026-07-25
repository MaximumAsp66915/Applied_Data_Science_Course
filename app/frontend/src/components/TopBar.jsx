import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { useUser } from "../context/UserContext";
import { Avatar } from "./UserCard";

export default function TopBar({ onSearchClick }) {
  const navigate = useNavigate();
  const { profile, loading } = useUser();

  return (
    <header className="sticky top-0 z-20 bg-ink/85 backdrop-blur-md px-5 pt-4 pb-3 flex items-center gap-3">
      <div className="flex-1">
        <p className="eyebrow">SUT Music</p>
        <h1 className="font-display text-xl text-paper -mt-0.5">
          {loading ? "Tuning in…" : `Hey, ${firstNameOf(profile)}`}
        </h1>
      </div>

      <button
        onClick={onSearchClick}
        aria-label="Search"
        className="w-10 h-10 rounded-full bg-surface border border-line/60 flex items-center justify-center tap"
      >
        <Search size={18} className="text-muted" />
      </button>

      {/* Dynamic profile button: shows the Telegram photo when we have one,
          otherwise a null/guest avatar. Never left blank or broken. */}
      <button
        onClick={() => navigate(profile?.isGuest ? "/profile" : `/user/${profile?.user_id}`)}
        aria-label="Your profile"
        className="tap"
      >
        <Avatar url={profile?.profile_photo} size={40} />
      </button>
    </header>
  );
}

function firstNameOf(profile) {
  if (!profile) return "";
  if (profile.isGuest) return "there";
  return profile.first_name || profile.username || "there";
}
