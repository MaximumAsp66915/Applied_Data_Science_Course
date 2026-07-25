import { Routes, Route } from "react-router-dom";
import Home from "./pages/Home";
import Profile from "./pages/Profile";
import SongPage from "./pages/SongPage";
import ArtistPage from "./pages/ArtistPage";
import Ranks from "./pages/Ranks";
import Suggest from "./pages/Suggest";
import MiniPlayer from "./components/MiniPlayer";

export default function App() {
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
    </div>
  );
}
