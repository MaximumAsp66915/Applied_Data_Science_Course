import React from 'react';
import { motion } from 'motion/react';
import { Download, History, SlidersHorizontal, ThumbsUp, Sparkles, Send, Music2, Zap } from 'lucide-react';
import { OFFICIAL_LINKS } from '../data/mockData';

export const KeyFeaturesGrid: React.FC = () => {
  const features = [
    {
      icon: <Download className="w-6 h-6 text-emerald-400" />,
      title: 'Direct MP3 Track Downloads',
      description: 'One-click audio downloading directly inside Telegram chat without external redirect links or file limit hurdles.',
      badge: 'Telegram Bot Integration',
      color: 'from-emerald-500/10 to-teal-500/5',
      borderColor: 'border-emerald-500/20',
    },
    {
      icon: <History className="w-6 h-6 text-cyan-400" />,
      title: 'Previous Songs Listening History',
      description: 'Review full stream history, re-listen to recently discovered tracks, and keep track of your daily audio journey.',
      badge: 'Personalized Vault',
      color: 'from-cyan-500/10 to-blue-500/5',
      borderColor: 'border-cyan-500/20',
    },
    {
      icon: <SlidersHorizontal className="w-6 h-6 text-purple-400" />,
      title: 'Interactive Seekable Progress Bar',
      description: 'Scrub and play songs from wherever you like on the track. Smooth response with real-time waveform visualization.',
      badge: 'Interactive Audio Player',
      color: 'from-purple-500/10 to-pink-500/5',
      borderColor: 'border-purple-500/20',
    },
    {
      icon: <ThumbsUp className="w-6 h-6 text-pink-400" />,
      title: 'Feedback Loops (Likes & Dislikes)',
      description: 'Every upvote or downvote instantly recalibrates recommendation weights in real-time k-NN vector space.',
      badge: 'Real-time AI Adaptation',
      color: 'from-pink-500/10 to-rose-500/5',
      borderColor: 'border-pink-500/20',
    },
  ];

  return (
    <section id="features" className="py-20 bg-slate-950 relative overflow-hidden">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
        <div className="text-center max-w-3xl mx-auto mb-14">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold mb-3">
            <Zap className="w-3.5 h-3.5" />
            <span>Bot Capabilities</span>
          </div>
          <h2 className="text-3xl sm:text-5xl font-extrabold text-white tracking-tight">
            Designed for <span className="text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 via-teal-300 to-cyan-400">Seamless Music Streaming</span>
          </h2>
          <p className="mt-3 text-slate-400 text-sm sm:text-base">
            Packed with modern interactive features built for Telegram Mini App users.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {features.map((feat, idx) => (
            <motion.div
              key={idx}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: idx * 0.1 }}
              className={`p-6 rounded-3xl bg-gradient-to-br ${feat.color} bg-slate-900/80 border ${feat.borderColor} shadow-xl hover:-translate-y-1 transition-all group`}
            >
              <div className="flex items-center justify-between mb-4">
                <div className="p-3 rounded-2xl bg-slate-800/80 group-hover:scale-110 transition-transform">
                  {feat.icon}
                </div>
                <span className="text-xs font-mono font-semibold px-2.5 py-1 rounded-full bg-slate-800 text-slate-300 border border-slate-700">
                  {feat.badge}
                </span>
              </div>
              <h3 className="text-xl font-bold text-white mb-2">{feat.title}</h3>
              <p className="text-sm text-slate-300 leading-relaxed">{feat.description}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
};
