import React, { useState } from 'react';
import { motion } from 'motion/react';
import {
  Github,
  BookOpen,
  Mail,
  Copy,
  Check,
  Send,
  Sparkles,
  Heart,
  Code2,
  ExternalLink
} from 'lucide-react';
import { OFFICIAL_LINKS } from '../data/mockData';
import { audioSynth } from '../utils/audioSynth';

export const ContributionSection: React.FC = () => {
  const [copied, setCopied] = useState(false);

  const copyEmail = () => {
    navigator.clipboard.writeText(OFFICIAL_LINKS.adminEmail);
    setCopied(true);
    audioSynth.playInteractionFeedback('like');
    setTimeout(() => setCopied(false), 2500);
  };

  return (
    <section id="contribution" className="py-20 bg-slate-950 relative overflow-hidden">
      {/* Background Soft Glow */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[350px] bg-purple-500/10 blur-[150px] rounded-full pointer-events-none" />

      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
        <div className="bg-gradient-to-b from-slate-900 to-slate-950 rounded-3xl p-8 sm:p-12 border border-slate-800 shadow-2xl text-center space-y-6 relative overflow-hidden">
          {/* Top Badge */}
          <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-400 text-xs font-semibold">
            <Heart className="w-3.5 h-3.5 fill-purple-400" />
            <span>Open Source & Community</span>
          </div>

          <h2 className="text-3xl sm:text-5xl font-extrabold text-white tracking-tight">
            Contribute to <span className="text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 via-teal-300 to-cyan-400">SUT Music</span>
          </h2>

          <p className="text-base sm:text-lg text-slate-300 max-w-2xl mx-auto leading-relaxed">
            We are happy to have you here! Whether you want to improve recommendation models, add music features, or refine the Telegram Mini App interface, contributions are warmly welcomed.
          </p>

          {/* Contact Box & Email Copy */}
          <div className="max-w-md mx-auto bg-slate-950/80 p-4 rounded-2xl border border-slate-800 space-y-3">
            <p className="text-xs text-slate-400 font-medium">To propose an idea or submit a contribution, email the admin developer:</p>

            <div className="flex items-center justify-between p-2.5 rounded-xl bg-slate-900 border border-slate-700/80">
              <div className="flex items-center gap-2 text-xs font-mono text-emerald-400 font-semibold truncate">
                <Mail className="w-4 h-4 text-purple-400 flex-shrink-0" />
                <span className="truncate">{OFFICIAL_LINKS.adminEmail}</span>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={copyEmail}
                  className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 font-medium transition-colors flex items-center gap-1"
                  title="Copy email to clipboard"
                >
                  {copied ? (
                    <>
                      <Check className="w-3.5 h-3.5 text-emerald-400" />
                      <span className="text-emerald-400">Copied</span>
                    </>
                  ) : (
                    <>
                      <Copy className="w-3.5 h-3.5 text-slate-400" />
                      <span>Copy</span>
                    </>
                  )}
                </button>

                <a
                  href={`mailto:${OFFICIAL_LINKS.adminEmail}?subject=Contribution%20to%20SUT%20Music%20Bot`}
                  className="px-3 py-1 rounded-lg bg-purple-500 hover:bg-purple-400 text-xs text-slate-950 font-bold transition-colors"
                >
                  Email
                </a>
              </div>
            </div>
          </div>

          {/* Resource Link Badges */}
          <div className="pt-6 border-t border-slate-800/80 flex flex-wrap items-center justify-center gap-4 text-xs font-semibold">
            <a
              href={OFFICIAL_LINKS.githubRepo}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-slate-200 border border-slate-800 hover:border-slate-700 transition-all shadow-md"
            >
              <Github className="w-4 h-4 text-white" />
              <span>GitHub Repository</span>
              <ExternalLink className="w-3.5 h-3.5 text-slate-400" />
            </a>

            <a
              href={OFFICIAL_LINKS.notebooksDoc}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-emerald-400 border border-slate-800 hover:border-emerald-500/30 transition-all shadow-md"
            >
              <BookOpen className="w-4 h-4 text-emerald-400" />
              <span>Full Notebooks Documentation</span>
              <ExternalLink className="w-3.5 h-3.5 text-emerald-400/70" />
            </a>
          </div>
        </div>
      </div>
    </section>
  );
};
