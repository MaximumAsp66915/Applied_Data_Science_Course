import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Play,
  Pause,
  ThumbsUp,
  ThumbsDown,
  Download,
  History,
  Sparkles,
  Mic2,
  Radio,
  Trophy,
  UserCheck,
  RotateCcw,
  Volume2,
  VolumeX,
  ExternalLink,
  ChevronRight,
  Heart,
  Send,
  Music,
  CheckCircle2,
  Sliders,
  Share2
} from 'lucide-react';
import { DEMO_PAGES, MOCK_TRACKS, OFFICIAL_LINKS } from '../data/mockData';
import { DemoPageId, Track } from '../types';
import { audioSynth } from '../utils/audioSynth';

export const MiniAppSimulator: React.FC = () => {
  const [currentPageIndex, setCurrentPageIndex] = useState<number>(0);
  const [isAutoPlaying, setIsAutoPlaying] = useState<boolean>(true);
  const [isPlayingAudio, setIsPlayingAudio] = useState<boolean>(false);
  const [currentTrack, setCurrentTrack] = useState<Track>(MOCK_TRACKS[0]);
  const [trackProgress, setTrackProgress] = useState<number>(35); // 0-100%
  const [tracksState, setTracksState] = useState<Track[]>(MOCK_TRACKS);
  const [showHistoryDrawer, setShowHistoryDrawer] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [isMuted, setIsMuted] = useState<boolean>(false);

  const autoPlayTimerRef = useRef<number | null>(null);

  const activePage = DEMO_PAGES[currentPageIndex];

  // Auto-play cycling effect
  useEffect(() => {
    if (isAutoPlaying) {
      autoPlayTimerRef.current = window.setInterval(() => {
        setCurrentPageIndex((prev) => (prev + 1) % DEMO_PAGES.length);
      }, 4500);
    } else {
      if (autoPlayTimerRef.current) clearInterval(autoPlayTimerRef.current);
    }

    return () => {
      if (autoPlayTimerRef.current) clearInterval(autoPlayTimerRef.current);
    };
  }, [isAutoPlaying]);

  // Handle page change manually
  const selectPage = (index: number) => {
    setCurrentPageIndex(index);
    setIsAutoPlaying(false);
    audioSynth.playInteractionFeedback('switch');
  };

  // Toast helper
  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  };

  // Toggle audio play
  const togglePlayAudio = () => {
    if (isPlayingAudio) {
      setIsPlayingAudio(false);
      audioSynth.stopDemo();
    } else {
      setIsPlayingAudio(true);
      if (!isMuted) {
        audioSynth.playMelodicDemo(
          (progress) => setTrackProgress(progress),
          () => setIsPlayingAudio(false)
        );
      }
    }
  };

  // Handle like track
  const handleLike = (trackId: string) => {
    setTracksState((prev) =>
      prev.map((t) => {
        if (t.id === trackId) {
          const isLiked = !t.isLiked;
          const matchScore = isLiked ? Math.min(100, (t.matchScore || 90) + 4) : Math.max(70, (t.matchScore || 90) - 4);
          return {
            ...t,
            isLiked,
            isDisliked: false,
            matchScore,
            likesCount: isLiked ? t.likesCount + 1 : t.likesCount - 1,
          };
        }
        return t;
      })
    );
    audioSynth.playInteractionFeedback('like');
    showToast('❤️ Feedback saved! Recommendation matrix updated.');
  };

  // Handle dislike track
  const handleDislike = (trackId: string) => {
    setTracksState((prev) =>
      prev.map((t) => {
        if (t.id === trackId) {
          const isDisliked = !t.isDisliked;
          const matchScore = isDisliked ? Math.max(60, (t.matchScore || 90) - 15) : Math.min(99, (t.matchScore || 90) + 5);
          return {
            ...t,
            isDisliked,
            isLiked: false,
            matchScore,
          };
        }
        return t;
      })
    );
    audioSynth.playInteractionFeedback('dislike');
    showToast('👎 Feedback saved! Shifted recommendation vectors away from genre.');
  };

  // Handle track download
  const handleDownload = (track: Track) => {
    audioSynth.playInteractionFeedback('download');
    showToast(`⏬ Downloading "${track.title}" from @SUTMusic_Bot...`);
  };

  // Handle progress bar drag/click seeking
  const handleSeek = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const newProgress = Math.max(0, Math.min(100, (clickX / rect.width) * 100));
    setTrackProgress(newProgress);
    audioSynth.playInteractionFeedback('click');
  };

  const getPageIcon = (iconName: string) => {
    switch (iconName) {
      case 'Sparkles':
        return <Sparkles className="w-4 h-4" />;
      case 'Mic2':
        return <Mic2 className="w-4 h-4" />;
      case 'Radio':
        return <Radio className="w-4 h-4" />;
      case 'Trophy':
        return <Trophy className="w-4 h-4" />;
      case 'UserCheck':
        return <UserCheck className="w-4 h-4" />;
      default:
        return <Music className="w-4 h-4" />;
    }
  };

  return (
    <section id="demo-simulator" className="py-20 bg-slate-950 relative overflow-hidden">
      {/* Background Glow */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[500px] bg-emerald-500/10 blur-[160px] rounded-full pointer-events-none" />

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
        {/* Section Header */}
        <div className="text-center max-w-3xl mx-auto mb-12">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold mb-3">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Interactive Auto-Play Demo</span>
          </div>
          <h2 className="text-3xl sm:text-5xl font-extrabold text-white tracking-tight">
            Explore the <span className="text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 via-teal-300 to-cyan-400">Telegram Web App</span>
          </h2>
          <p className="mt-3 text-slate-400 text-sm sm:text-base">
            Auto-playing live preview of SUT Music Bot features. Click tabs to switch pages or interact with music controls.
          </p>
        </div>

        {/* Control Bar (Auto-play Toggle, Page Selectors) */}
        <div className="flex flex-wrap items-center justify-between gap-4 mb-8 bg-slate-900/80 p-3 rounded-2xl border border-slate-800">
          <div className="flex items-center gap-2 overflow-x-auto pb-1 sm:pb-0 scrollbar-none w-full sm:w-auto">
            {DEMO_PAGES.map((page, idx) => {
              const isActive = currentPageIndex === idx;
              return (
                <button
                  key={page.id}
                  onClick={() => selectPage(idx)}
                  className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all whitespace-nowrap ${
                    isActive
                      ? 'bg-emerald-500 text-slate-950 shadow-md shadow-emerald-500/20 font-bold'
                      : 'bg-slate-800/80 text-slate-300 hover:bg-slate-800 hover:text-white'
                  }`}
                >
                  {getPageIcon(page.iconName)}
                  <span>{page.title}</span>
                </button>
              );
            })}
          </div>

          <div className="flex items-center gap-3 ml-auto">
            <button
              onClick={() => setIsAutoPlaying(!isAutoPlaying)}
              className={`flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-semibold border transition-all ${
                isAutoPlaying
                  ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                  : 'bg-slate-800 text-slate-400 border-slate-700'
              }`}
            >
              {isAutoPlaying ? (
                <>
                  <Pause className="w-3.5 h-3.5 fill-emerald-400 text-emerald-400" />
                  <span>Pause Auto Cycle</span>
                </>
              ) : (
                <>
                  <Play className="w-3.5 h-3.5 fill-emerald-400 text-emerald-400" />
                  <span>Resume Auto Cycle</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Main Grid: Phone Frame Mockup (Left/Center) + Page Info & Engine Details (Right) */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-center">
          {/* Phone Frame Container */}
          <div className="lg:col-span-7 flex justify-center">
            <div className="relative w-full max-w-[380px] bg-slate-950 rounded-[42px] border-[8px] border-slate-800/90 shadow-2xl shadow-emerald-500/10 p-3 overflow-hidden">
              {/* Phone Speaker Notch */}
              <div className="absolute top-0 left-1/2 -translate-x-1/2 w-32 h-5 bg-slate-800 rounded-b-2xl z-40 flex items-center justify-center">
                <div className="w-10 h-1 bg-slate-700 rounded-full" />
              </div>

              {/* Telegram Mini App Screen Canvas */}
              <div className="bg-slate-900 rounded-[30px] pt-7 pb-4 px-3.5 min-h-[580px] flex flex-col justify-between relative overflow-hidden border border-slate-800">
                {/* Telegram App Header */}
                <div className="flex items-center justify-between pb-3 border-b border-slate-800/80 mb-3">
                  <div className="flex items-center gap-2">
                    <div className="w-7 h-7 rounded-full bg-gradient-to-br from-emerald-400 to-teal-500 flex items-center justify-center text-slate-950 font-black text-xs">
                      SUT
                    </div>
                    <div>
                      <h4 className="text-xs font-bold text-white leading-tight">SUT Music</h4>
                      <p className="text-[10px] text-emerald-400">Telegram Mini App</p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setShowHistoryDrawer(!showHistoryDrawer)}
                      className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
                      title="Listening History"
                    >
                      <History className="w-3.5 h-3.5" />
                    </button>

                    <a
                      href={OFFICIAL_LINKS.webApp}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="p-1.5 rounded-lg bg-emerald-500/20 text-emerald-400"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                  </div>
                </div>

                {/* Animated Page Content Screen */}
                <div className="flex-1 overflow-y-auto pr-0.5 space-y-3 relative">
                  <AnimatePresence mode="wait">
                    <motion.div
                      key={activePage.id}
                      initial={{ opacity: 0, x: 20 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: -20 }}
                      transition={{ duration: 0.35 }}
                      className="space-y-3"
                    >
                      {/* Page Engine Banner */}
                      <div className="bg-slate-800/80 rounded-xl p-2.5 border border-slate-700/60 flex items-center justify-between">
                        <div>
                          <span className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400">
                            {activePage.badge}
                          </span>
                          <h3 className="text-sm font-bold text-white mt-1">{activePage.title}</h3>
                        </div>
                        <div className="w-8 h-8 rounded-lg bg-emerald-500/10 flex items-center justify-center text-emerald-400">
                          {getPageIcon(activePage.iconName)}
                        </div>
                      </div>

                      {/* Screen Specific Renderings */}
                      {activePage.id === 'suggest' && (
                        <div className="space-y-2.5">
                          <p className="text-[11px] text-slate-400">AI Matches based on collaborative vectors:</p>
                          {tracksState.slice(0, 3).map((track) => (
                            <div
                              key={track.id}
                              onClick={() => setCurrentTrack(track)}
                              className={`p-2.5 rounded-xl border transition-all cursor-pointer ${
                                currentTrack.id === track.id
                                  ? 'bg-slate-800 border-emerald-500/50 shadow-sm'
                                  : 'bg-slate-800/40 border-slate-800 hover:bg-slate-800/70'
                              }`}
                            >
                              <div className="flex items-center gap-2.5">
                                <img
                                  src={track.albumCover}
                                  alt={track.title}
                                  className="w-10 h-10 rounded-lg object-cover"
                                />
                                <div className="flex-1 min-w-0">
                                  <h5 className="text-xs font-semibold text-white truncate">{track.title}</h5>
                                  <p className="text-[10px] text-slate-400 truncate">{track.artist}</p>
                                </div>
                                <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full">
                                  {track.matchScore}% Match
                                </span>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}

                      {activePage.id === 'artist' && (
                        <div className="space-y-2.5">
                          <div className="p-3 bg-gradient-to-r from-purple-900/40 to-slate-800 rounded-xl border border-purple-500/20">
                            <span className="text-[10px] text-purple-300 font-medium">artist-related Fallback</span>
                            <h4 className="text-xs font-bold text-white mt-0.5">Homayoun Shajarian</h4>
                            <p className="text-[10px] text-slate-300 mt-1">
                              Fallback system active: Exploring co-occurrence artist network.
                            </p>
                          </div>
                          <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Top Discography:</p>
                          {tracksState.filter(t => t.artist.includes('Shajarian')).map((track) => (
                            <div key={track.id} className="p-2 bg-slate-800/50 rounded-lg flex items-center justify-between">
                              <span className="text-xs text-white truncate">{track.title}</span>
                              <button
                                onClick={() => handleDownload(track)}
                                className="p-1 rounded bg-slate-700 hover:bg-emerald-500 hover:text-slate-950 text-slate-200 transition-colors"
                              >
                                <Download className="w-3 h-3" />
                              </button>
                            </div>
                          ))}
                        </div>
                      )}

                      {activePage.id === 'latest' && (
                        <div className="space-y-2.5">
                          <p className="text-[11px] text-slate-400">Newly indexed Persian audio releases:</p>
                          {tracksState.slice(0, 3).map((track) => (
                            <div key={track.id} className="p-2.5 bg-slate-800/60 rounded-xl border border-cyan-500/20 space-y-2">
                              <div className="flex items-center justify-between">
                                <div>
                                  <h5 className="text-xs font-bold text-white">{track.title}</h5>
                                  <p className="text-[10px] text-slate-400">{track.artist}</p>
                                </div>
                                <span className="text-[9px] bg-cyan-500/20 text-cyan-300 px-1.5 py-0.5 rounded">NEW</span>
                              </div>

                              {/* Waveform graphic */}
                              <div className="h-4 flex items-center gap-0.5">
                                {[40, 70, 30, 90, 60, 80, 20, 100, 50, 80, 30, 90, 60].map((h, i) => (
                                  <div
                                    key={i}
                                    className="flex-1 bg-cyan-500/60 rounded-full transition-all duration-300"
                                    style={{ height: `${h}%` }}
                                  />
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}

                      {activePage.id === 'rank' && (
                        <div className="space-y-2">
                          <p className="text-[11px] text-slate-400">Bot Chart Leaderboard (top-tracks):</p>
                          {tracksState.map((track, idx) => (
                            <div key={track.id} className="p-2 bg-slate-800/50 rounded-xl flex items-center gap-2.5">
                              <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-extrabold ${
                                idx === 0 ? 'bg-amber-400 text-slate-950' : idx === 1 ? 'bg-slate-300 text-slate-950' : 'bg-slate-700 text-slate-300'
                              }`}>
                                {idx + 1}
                              </span>
                              <div className="flex-1 min-w-0">
                                <h5 className="text-xs font-semibold text-white truncate">{track.title}</h5>
                                <p className="text-[10px] text-slate-400 truncate">{track.playsCount.toLocaleString()} plays</p>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}

                      {activePage.id === 'profile' && (
                        <div className="space-y-2.5">
                          <div className="p-2.5 bg-pink-500/10 border border-pink-500/20 rounded-xl space-y-1">
                            <div className="flex items-center gap-1.5 text-xs font-bold text-pink-400">
                              <Heart className="w-3.5 h-3.5 fill-pink-400" />
                              <span>based on liked tracks</span>
                            </div>
                            <p className="text-[10px] text-slate-300">k-NN Centroid affinity matches calculated from your upvotes.</p>
                          </div>

                          <div className="p-2.5 bg-blue-500/10 border border-blue-500/20 rounded-xl space-y-1">
                            <div className="flex items-center gap-1.5 text-xs font-bold text-blue-400">
                              <Send className="w-3.5 h-3.5" />
                              <span>based on sent tracks</span>
                            </div>
                            <p className="text-[10px] text-slate-300">Contextual vector search based on MP3 files sent to chat.</p>
                          </div>
                        </div>
                      )}
                    </motion.div>
                  </AnimatePresence>

                  {/* History Drawer Pop-up overlay inside phone */}
                  {showHistoryDrawer && (
                    <motion.div
                      initial={{ opacity: 0, y: 50 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: 50 }}
                      className="absolute inset-0 bg-slate-950/95 p-3 rounded-2xl z-30 flex flex-col justify-between border border-slate-800"
                    >
                      <div>
                        <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                          <h4 className="text-xs font-bold text-white flex items-center gap-1.5">
                            <History className="w-3.5 h-3.5 text-emerald-400" />
                            <span>Previous Songs Listened</span>
                          </h4>
                          <button
                            onClick={() => setShowHistoryDrawer(false)}
                            className="text-[10px] text-slate-400 hover:text-white"
                          >
                            Close
                          </button>
                        </div>
                        <div className="mt-2 space-y-2">
                          {tracksState.slice(0, 3).map((track, i) => (
                            <div key={i} className="p-2 bg-slate-900 rounded-lg flex items-center justify-between">
                              <div>
                                <p className="text-xs text-white font-medium">{track.title}</p>
                                <p className="text-[9px] text-slate-400">{track.artist} • 12m ago</p>
                              </div>
                              <button
                                onClick={() => {
                                  setCurrentTrack(track);
                                  setShowHistoryDrawer(false);
                                  togglePlayAudio();
                                }}
                                className="p-1 rounded bg-emerald-500/20 text-emerald-400 text-[10px]"
                              >
                                Play Again
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                      <p className="text-[9px] text-slate-500 text-center">Synced with @SUTMusic_Bot account</p>
                    </motion.div>
                  )}
                </div>

                {/* Persistent Player Widget inside Phone */}
                <div className="mt-3 bg-slate-950/90 rounded-2xl p-2.5 border border-slate-800 shadow-xl space-y-2">
                  <div className="flex items-center gap-2">
                    <img
                      src={currentTrack.albumCover}
                      alt={currentTrack.title}
                      className="w-9 h-9 rounded-lg object-cover"
                    />
                    <div className="flex-1 min-w-0">
                      <h5 className="text-xs font-bold text-white truncate">{currentTrack.title}</h5>
                      <p className="text-[10px] text-slate-400 truncate">{currentTrack.artist}</p>
                    </div>

                    {/* Play/Pause Button */}
                    <button
                      onClick={togglePlayAudio}
                      className="w-8 h-8 rounded-full bg-emerald-500 flex items-center justify-center text-slate-950 shadow-md hover:scale-105 transition-transform"
                    >
                      {isPlayingAudio ? (
                        <Pause className="w-4 h-4 fill-slate-950 text-slate-950" />
                      ) : (
                        <Play className="w-4 h-4 fill-slate-950 text-slate-950 ml-0.5" />
                      )}
                    </button>
                  </div>

                  {/* Interactive Progress Bar (Seekable!) */}
                  <div className="space-y-1">
                    <div
                      onClick={handleSeek}
                      className="h-1.5 w-full bg-slate-800 rounded-full cursor-pointer relative overflow-hidden group"
                      title="Click or drag to seek track position"
                    >
                      <div
                        className="h-full bg-gradient-to-r from-emerald-500 to-teal-400 rounded-full transition-all"
                        style={{ width: `${trackProgress}%` }}
                      />
                    </div>
                    <div className="flex justify-between text-[9px] text-slate-500 font-mono">
                      <span>{Math.floor((trackProgress / 100) * 215 / 60)}:{(Math.floor((trackProgress / 100) * 215) % 60).toString().padStart(2, '0')}</span>
                      <span>3:35</span>
                    </div>
                  </div>

                  {/* Like / Dislike / Download Action Bar */}
                  <div className="flex items-center justify-between pt-1 border-t border-slate-800/80">
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleLike(currentTrack.id)}
                        className={`p-1.5 rounded-lg text-xs flex items-center gap-1 transition-all ${
                          currentTrack.isLiked
                            ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                            : 'bg-slate-900 text-slate-400 hover:text-white'
                        }`}
                        title="Like track (updates recommendation vector)"
                      >
                        <ThumbsUp className="w-3 h-3" />
                        <span className="text-[10px]">{currentTrack.likesCount}</span>
                      </button>

                      <button
                        onClick={() => handleDislike(currentTrack.id)}
                        className={`p-1.5 rounded-lg text-xs transition-all ${
                          currentTrack.isDisliked
                            ? 'bg-rose-500/20 text-rose-400 border border-rose-500/40'
                            : 'bg-slate-900 text-slate-400 hover:text-white'
                        }`}
                        title="Dislike track"
                      >
                        <ThumbsDown className="w-3 h-3" />
                      </button>
                    </div>

                    <button
                      onClick={() => handleDownload(currentTrack)}
                      className="p-1.5 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 text-[10px] font-semibold flex items-center gap-1 border border-emerald-500/20"
                    >
                      <Download className="w-3 h-3" />
                      <span>Download MP3</span>
                    </button>
                  </div>
                </div>
              </div>

              {/* Toast Notification inside phone */}
              {toastMessage && (
                <motion.div
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 20 }}
                  className="absolute bottom-16 left-6 right-6 bg-slate-900/95 border border-emerald-500/40 text-emerald-300 text-[11px] p-2.5 rounded-xl shadow-2xl backdrop-blur-md z-50 text-center font-medium"
                >
                  {toastMessage}
                </motion.div>
              )}
            </div>
          </div>

          {/* Right Column: Engine Details & Feature Cards */}
          <div className="lg:col-span-5 space-y-6">
            <div className="bg-slate-900/90 rounded-3xl p-6 border border-slate-800 shadow-xl relative overflow-hidden">
              <div className="absolute top-0 right-0 w-32 h-32 bg-emerald-500/10 blur-2xl pointer-events-none" />

              <div className="flex items-center gap-2 mb-3">
                <span className="text-xs font-mono font-bold px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  {activePage.badge}
                </span>
                <span className="text-xs text-slate-400">Sub-system Engine</span>
              </div>

              <h3 className="text-2xl font-bold text-white mb-2">{activePage.engineName}</h3>
              <p className="text-sm text-slate-300 leading-relaxed mb-6">{activePage.description}</p>

              {/* Engine Spec Highlights */}
              <div className="space-y-3 pt-4 border-t border-slate-800">
                <div className="flex items-start gap-3">
                  <div className="p-2 rounded-xl bg-emerald-500/10 text-emerald-400 mt-0.5">
                    <Sliders className="w-4 h-4" />
                  </div>
                  <div>
                    <h5 className="text-xs font-bold text-white">Dynamic Feedback Loop</h5>
                    <p className="text-xs text-slate-400">Likes and dislikes recalculate your user centroid in real time.</p>
                  </div>
                </div>

                <div className="flex items-start gap-3">
                  <div className="p-2 rounded-xl bg-teal-500/10 text-teal-400 mt-0.5">
                    <CheckCircle2 className="w-4 h-4" />
                  </div>
                  <div>
                    <h5 className="text-xs font-bold text-white">High Precision Filtering</h5>
                    <p className="text-xs text-slate-400">Blends explicit user ratings with implicit skip metrics.</p>
                  </div>
                </div>
              </div>

              <div className="mt-6 pt-4 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
                <span>Page route: <strong className="text-emerald-400 font-mono">/{activePage.id}</strong></span>
                <a
                  href={OFFICIAL_LINKS.webApp}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-emerald-400 font-bold hover:underline flex items-center gap-1"
                >
                  Try live on Telegram
                  <ChevronRight className="w-3.5 h-3.5" />
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};
