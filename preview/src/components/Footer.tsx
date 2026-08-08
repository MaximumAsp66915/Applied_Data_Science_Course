import React from 'react';
import { Music2, Send, Github, BookOpen, ExternalLink, Heart } from 'lucide-react';
import { OFFICIAL_LINKS } from '../data/mockData';

export const Footer: React.FC = () => {
  return (
    <footer className="bg-slate-950 border-t border-slate-900 py-12 text-slate-400 text-xs">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col md:flex-row items-center justify-between gap-6">
          {/* Brand */}
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-emerald-500 to-teal-500 flex items-center justify-center text-slate-950">
              <Music2 className="w-4 h-4" />
            </div>
            <div>
              <h4 className="text-sm font-bold text-white">SUT Music Bot</h4>
              <p className="text-[11px] text-slate-500">Applied Data Science Course Project</p>
            </div>
          </div>

          {/* Links */}
          <div className="flex flex-wrap items-center justify-center gap-6 font-medium text-slate-300">
            <a
              href={OFFICIAL_LINKS.telegramGroup}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-emerald-400 transition-colors flex items-center gap-1.5"
            >
              <Send className="w-3.5 h-3.5 text-sky-400" />
              <span>SUT Music</span>
            </a>

            <a
              href={OFFICIAL_LINKS.telegramBot}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-emerald-400 transition-colors flex items-center gap-1.5"
            >
              <Send className="w-3.5 h-3.5 text-teal-400" />
              <span>@SUTMusic_Bot</span>
            </a>

            <a
              href={OFFICIAL_LINKS.webApp}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-emerald-400 transition-colors flex items-center gap-1.5"
            >
              <ExternalLink className="w-3.5 h-3.5 text-emerald-400" />
              <span>Web App</span>
            </a>

            <a
              href={OFFICIAL_LINKS.githubRepo}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-emerald-400 transition-colors flex items-center gap-1.5"
            >
              <Github className="w-3.5 h-3.5 text-slate-300" />
              <span>GitHub</span>
            </a>

            <a
              href={OFFICIAL_LINKS.notebooksDoc}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-emerald-400 transition-colors flex items-center gap-1.5"
            >
              <BookOpen className="w-3.5 h-3.5 text-emerald-400" />
              <span>Notebooks</span>
            </a>
          </div>

          {/* Copyright & Developer */}
          <div className="text-center md:text-right text-[11px] text-slate-500">
            <p>© {new Date().getFullYear()} SUT Music Recommender. All rights reserved.</p>
            <p className="mt-0.5">Admin: <span className="font-mono text-slate-400">{OFFICIAL_LINKS.adminEmail}</span></p>
          </div>
        </div>
      </div>
    </footer>
  );
};
