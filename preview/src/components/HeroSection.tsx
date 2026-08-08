import React, { useState } from 'react';
import { motion } from 'motion/react';
import {
  Send,
  ExternalLink,
  Github,
  BookOpen,
  Mail,
  Sparkles,
  Play,
  Copy,
  Check,
  Zap,
  Music,
  Bot
} from 'lucide-react';
import { OFFICIAL_LINKS } from '../data/mockData';
import { audioSynth } from '../utils/audioSynth';

export const HeroSection: React.FC = () => {
  const [copiedEmail, setCopiedEmail] = useState(false);

  const copyEmail = () => {
    navigator.clipboard.writeText(OFFICIAL_LINKS.adminEmail);
    setCopiedEmail(true);
    audioSynth.playInteractionFeedback('click');
    setTimeout(() => setCopiedEmail(false), 2000);
  };

  const scrollToDemo = () => {
    audioSynth.playInteractionFeedback('switch');
    document.getElementById('demo-simulator')?.scrollIntoView({ behavior: 'smooth' });
  };

  return (
    <section className="relative min-h-[92vh] pt-28 pb-16 flex items-center justify-center overflow-hidden bg-slate-950">
      {/* Background Glowing Music Grid & Audio Waves */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_80%_80%_at_50%_-20%,rgba(16,185,129,0.18),rgba(255,255,255,0))]" />
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-[600px] h-[300px] bg-emerald-500/10 blur-[130px] rounded-full pointer-events-none" />
      <div className="absolute bottom-10 right-10 w-[400px] h-[400px] bg-cyan-500/10 blur-[140px] rounded-full pointer-events-none" />

      {/* Subtle Grid Pattern Overlay */}
      <div
        className="absolute inset-0 opacity-[0.03] pointer-events-none"
        style={{
          backgroundImage: `radial-gradient(circle at 1px 1px, white 1px, transparent 0)`,
          backgroundSize: '32px 32px',
        }}
      />

      <div className="relative max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 text-center z-10">
        {/* Course & Bot Badge */}
        <motion.div
          initial={{ opacity: 0, y: -15 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/25 text-emerald-400 text-xs font-semibold tracking-wide mb-6 shadow-inner shadow-emerald-500/10"
        >
          <Sparkles className="w-3.5 h-3.5 text-emerald-400 animate-pulse" />
          <span>Applied Data Science Course • Sharif Music AI Engine</span>
        </motion.div>

        {/* Title */}
        <motion.h1
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.1 }}
          className="text-4xl sm:text-6xl md:text-7xl font-extrabold text-white tracking-tight leading-[1.1] max-w-4xl mx-auto"
        >
          SUT Music <span className="text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 via-teal-300 to-cyan-400">Bot & Web App</span>
        </motion.h1>

        {/* Minimal Description */}
        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.2 }}
          className="mt-5 text-lg sm:text-xl text-slate-300 max-w-2xl mx-auto font-normal leading-relaxed"
        >
          Smart Persian & global music discovery powered by graph neural vectors, implicit feedback loops, and seamless Telegram Mini App streaming.
        </motion.p>

        {/* Action Buttons Bar */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.3 }}
          className="mt-8 flex flex-wrap items-center justify-center gap-3.5"
        >
          {/* Web App Start */}
          <a
            href={OFFICIAL_LINKS.webApp}
            target="_blank"
            rel="noopener noreferrer"
            className="group flex items-center gap-2.5 px-6 py-3.5 rounded-2xl bg-gradient-to-r from-emerald-500 via-teal-500 to-cyan-500 text-slate-950 font-bold text-sm shadow-xl shadow-emerald-500/25 hover:shadow-emerald-500/40 hover:scale-[1.02] active:scale-[0.98] transition-all"
          >
            <Zap className="w-4 h-4 text-slate-950 fill-slate-950" />
            <span>Launch Web App</span>
            <ExternalLink className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
          </a>

          {/* Telegram Bot Direct */}
          <a
            href={OFFICIAL_LINKS.telegramBot}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-5 py-3.5 rounded-2xl bg-slate-900 hover:bg-slate-800 text-slate-200 border border-slate-700/80 hover:border-emerald-500/50 font-semibold text-sm transition-all shadow-md"
          >
            <Bot className="w-4 h-4 text-sky-400" />
            <span>{OFFICIAL_LINKS.telegramBotName}</span>
          </a>

          {/* Telegram Community Group */}
          <a
            href={OFFICIAL_LINKS.telegramGroup}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-5 py-3.5 rounded-2xl bg-slate-900 hover:bg-slate-800 text-slate-200 border border-slate-700/80 hover:border-sky-500/50 font-semibold text-sm transition-all shadow-md"
          >
            <Send className="w-4 h-4 text-sky-400" />
            <span>{OFFICIAL_LINKS.telegramGroupName}</span>
          </a>

          {/* Interactive Demo Scroll Trigger */}
          <button
            onClick={scrollToDemo}
            className="flex items-center gap-2 px-5 py-3.5 rounded-2xl bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 font-semibold text-sm transition-all"
          >
            <Play className="w-4 h-4 fill-emerald-400 text-emerald-400" />
            <span>Watch Live Auto Demo</span>
          </button>
        </motion.div>

        {/* Quick Resource Pills (GitHub, Notebooks, Admin Email) */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.4 }}
          className="mt-10 pt-8 border-t border-slate-800/80 max-w-3xl mx-auto flex flex-wrap items-center justify-center gap-4 text-xs font-medium text-slate-400"
        >
          {/* GitHub Repo */}
          <a
            href={OFFICIAL_LINKS.githubRepo}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900/90 border border-slate-800 hover:border-slate-600 hover:text-white transition-all"
          >
            <Github className="w-3.5 h-3.5 text-slate-300" />
            <span>GitHub Repository</span>
          </a>

          {/* Documentation Notebooks */}
          <a
            href={OFFICIAL_LINKS.notebooksDoc}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900/90 border border-slate-800 hover:border-slate-600 hover:text-white transition-all"
          >
            <BookOpen className="w-3.5 h-3.5 text-emerald-400" />
            <span>Project Notebooks Doc</span>
          </a>

          {/* Admin Email */}
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900/90 border border-slate-800 text-slate-300">
            <Mail className="w-3.5 h-3.5 text-purple-400" />
            <span className="font-mono">{OFFICIAL_LINKS.adminEmail}</span>
            <button
              onClick={copyEmail}
              className="p-1 hover:text-white transition-colors"
              title="Copy developer email"
            >
              {copiedEmail ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3 text-slate-400" />}
            </button>
          </div>
        </motion.div>
      </div>
    </section>
  );
};
