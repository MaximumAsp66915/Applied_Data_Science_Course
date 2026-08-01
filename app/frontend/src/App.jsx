import { useEffect, useRef } from "react";
import { Routes, Route, useNavigate, useLocation, useNavigationType } from "react-router-dom";
import Home from "./pages/Home";
import Profile from "./pages/Profile";
import SongPage from "./pages/SongPage";
import ArtistPage from "./pages/ArtistPage";
import Ranks from "./pages/Ranks";
import Suggest from "./pages/Suggest";
import MiniPlayer from "./components/MiniPlayer";
import { ToastHost } from "./components/Toast";
import { getStartParam, showBackButton, hideBackButton } from "./lib/telegram";

// Matches the "track_{id}" start_param the download caption's deep link
// sends (see webapp/routers/tracks.py's _build_share_caption) so opening
// that link takes the user straight to the song page instead of just the
// app's home screen.
const START_PARAM_TRACK = /^track_(\d+)$/;

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const navigationType = useNavigationType();

  // Runs once on launch: if the Mini App was opened via a
  // ?startapp=track_{id} deep link, jump straight to that song's page.
  useEffect(() => {
    const startParam = getStartParam();
    const match = startParam && START_PARAM_TRACK.exec(startParam);
    if (match) navigate(`/song/${match[1]}`, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Universal back button: Telegram's own BackButton doubles as the
  // handler for the phone's hardware/system back button while it's shown
  // (that's what stops the OS back gesture from just minimizing the Mini
  // App). Depth tracks whether we actually have somewhere in-app to go
  // back to -- PUSH means we navigated forward from within the app (safe
  // to pop), POP means we already went back (so pop again), REPLACE
  // (e.g. the deep-link redirect above) doesn't count as depth. Landing
  // straight on a page with no in-app history (shared link, refresh)
  // sends the back button Home instead of trying to pop nothing.
  const depthRef = useRef(0);
  useEffect(() => {
    if (navigationType === "PUSH") depthRef.current += 1;
    else if (navigationType === "POP") depthRef.current = Math.max(0, depthRef.current - 1);
  }, [location, navigationType]);

  useEffect(() => {
    if (location.pathname === "/") {
      hideBackButton();
      return undefined;
    }
    return showBackButton(() => {
      if (depthRef.current > 0) navigate(-1);
      else navigate("/");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

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
