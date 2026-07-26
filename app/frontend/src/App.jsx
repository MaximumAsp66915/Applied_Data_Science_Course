import { useEffect } from "react";
import { Routes, Route, useNavigate } from "react-router-dom";
import Home from "./pages/Home";
import Profile from "./pages/Profile";
import SongPage from "./pages/SongPage";
import ArtistPage from "./pages/ArtistPage";
import Ranks from "./pages/Ranks";
import Suggest from "./pages/Suggest";
import MiniPlayer from "./components/MiniPlayer";
import { ToastHost } from "./components/Toast";
import { getStartParam } from "./lib/telegram";

// Matches the "track_{id}" start_param the download caption's deep link
// sends (see webapp/routers/tracks.py's _build_share_caption) so opening
// that link takes the user straight to the song page instead of just the
// app's home screen.
const START_PARAM_TRACK = /^track_(\d+)$/;

export default function App() {
  const navigate = useNavigate();

  // Runs once on launch: if the Mini App was opened via a
  // ?startapp=track_{id} deep link, jump straight to that song's page.
  useEffect(() => {
    const startParam = getStartParam();
    const match = startParam && START_PARAM_TRACK.exec(startParam);
    if (match) navigate(`/song/${match[1]}`, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="max-w-md mx-auto min-h-screen relative">
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/user/:userId" element={<Profile />} />
        <Route path="/song/:trackId" element={<SongPage />} />
        <Route path="/artist/:artistId" element={<ArtistPage />} />
        <Route path="/ranks" element={<Ranks />} />
        <Route path="/suggest" element={<Suggest />} />
      </Routes>
      <MiniPlayer />
      <ToastHost />
    </div>
  );
}
