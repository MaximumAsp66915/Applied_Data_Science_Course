import React, { useState, useEffect } from 'react';
import { Music2, ExternalLink, Send, Github, Sparkles, Menu, X, Code2 } from 'lucide-react';
import { OFFICIAL_LINKS } from '../data/mockData';

export const Navbar: React.FC = () => {
  const [scrolled, setScrolled] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 20);
    };
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const scrollToSection = (id: string) => {
    setMobileMenuOpen(false);
    const element = document.getElementById(id);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth' });
    }
  };

  return (
    <nav
      className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
        scrolled
          ? 'bg-slate-950/85 backdrop-blur-md border-b border-emerald-500/15 shadow-xl shadow-black/40 py-3'
          : 'bg-transparent py-5'
      }`}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between">
          {/* Logo & Brand */}
          <div className="flex items-center gap-3 cursor-pointer" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
            <div className="relative flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-500 via-teal-500 to-cyan-500 p-[1px] shadow-lg shadow-emerald-500/20 group">
              <div className="w-full h-full bg-slate-950 rounded-[11px] flex items-center justify-center group-hover:bg-slate-900 transition-colors">
                <Music2 className="w-5 h-5 text-emerald-400 group-hover:scale-110 transition-transform duration-300" />
              </div>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold tracking-tight text-white">SUT Music</span>
                <span className="px-2 py-0.5 text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 rounded-full border border-emerald-500/20">
                  Bot & Web App
                </span>
              </div>
              <p className="text-xs text-slate-400 hidden sm:block">Sharif Music Recommender</p>
            </div>
          </div>

          {/* Desktop Navigation */}
          <div className="hidden lg:flex items-center gap-6 text-sm font-medium text-slate-300">
            <button
              onClick={() => scrollToSection('demo-simulator')}
              className="hover:text-emerald-400 transition-colors flex items-center gap-1.5"
            >
              <Sparkles className="w-4 h-4 text-emerald-400" />
              Interactive Demo
            </button>
            <button
              onClick={() => scrollToSection('recommendation-systems')}
              className="hover:text-emerald-400 transition-colors"
            >
              AI Engines
            </button>
            <button
              onClick={() => scrollToSection('features')}
              className="hover:text-emerald-400 transition-colors"
            >
              Features
            </button>
            <button
              onClick={() => scrollToSection('stats')}
              className="hover:text-emerald-400 transition-colors"
            >
              Metrics
            </button>
            <button
              onClick={() => scrollToSection('pipeline')}
              className="hover:text-emerald-400 transition-colors"
            >
              CI/CD Pipeline
            </button>
            <button
              onClick={() => scrollToSection('contribution')}
              className="hover:text-emerald-400 transition-colors"
            >
              Contribute
            </button>
          </div>

          {/* External Action Links */}
          <div className="hidden md:flex items-center gap-3">
            <a
              href={OFFICIAL_LINKS.telegramGroup}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold bg-slate-900/80 hover:bg-slate-800 text-slate-200 border border-slate-700/60 hover:border-slate-600 transition-all shadow-sm"
              title="SUT Music Telegram Group"
            >
              <Send className="w-3.5 h-3.5 text-sky-400" />
              <span>SUT Music</span>
            </a>

            <a
              href={OFFICIAL_LINKS.webApp}
              target="_blank"
              rel="noopener noreferrer"
              className="relative group flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold bg-gradient-to-r from-emerald-500 to-teal-500 text-slate-950 hover:from-emerald-400 hover:to-teal-400 transition-all shadow-lg shadow-emerald-500/25 hover:shadow-emerald-500/40 hover:-translate-y-0.5"
            >
              <span>Open Web App</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          </div>

          {/* Mobile Hamburger Button */}
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="lg:hidden p-2 rounded-lg bg-slate-900 text-slate-300 border border-slate-800 hover:text-white"
            aria-label="Toggle Navigation Menu"
          >
            {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div className="lg:hidden mt-3 bg-slate-950/95 backdrop-blur-xl border-b border-slate-800 px-4 py-5 shadow-2xl space-y-4">
          <div className="flex flex-col gap-3 font-medium text-slate-300">
            <button
              onClick={() => scrollToSection('demo-simulator')}
              className="text-left px-3 py-2 rounded-lg hover:bg-slate-900 text-emerald-400 flex items-center gap-2"
            >
              <Sparkles className="w-4 h-4" />
              Interactive Demo Frame
            </button>
            <button
              onClick={() => scrollToSection('recommendation-systems')}
              className="text-left px-3 py-2 rounded-lg hover:bg-slate-900"
            >
              Recommendation Engines
            </button>
            <button
              onClick={() => scrollToSection('features')}
              className="text-left px-3 py-2 rounded-lg hover:bg-slate-900"
            >
              Bot Features
            </button>
            <button
              onClick={() => scrollToSection('stats')}
              className="text-left px-3 py-2 rounded-lg hover:bg-slate-900"
            >
              Metrics & Stats
            </button>
            <button
              onClick={() => scrollToSection('pipeline')}
              className="text-left px-3 py-2 rounded-lg hover:bg-slate-900"
            >
              CI/CD Pipeline
            </button>
            <button
              onClick={() => scrollToSection('contribution')}
              className="text-left px-3 py-2 rounded-lg hover:bg-slate-900"
            >
              Documentation & Contribute
            </button>
          </div>

          <div className="pt-3 border-t border-slate-800 flex flex-col gap-2.5">
            <a
              href={OFFICIAL_LINKS.webApp}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-center gap-2 w-full py-2.5 rounded-xl text-xs font-bold bg-emerald-500 text-slate-950"
            >
              <span>Open Web App</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </a>

            <div className="grid grid-cols-2 gap-2 pt-1">
              <a
                href={OFFICIAL_LINKS.telegramGroup}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs bg-slate-900 text-slate-300 border border-slate-800"
              >
                <Send className="w-3.5 h-3.5 text-sky-400" />
                <span>SUT Music</span>
              </a>
              <a
                href={OFFICIAL_LINKS.githubRepo}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs bg-slate-900 text-slate-300 border border-slate-800"
              >
                <Github className="w-3.5 h-3.5 text-slate-300" />
                <span>GitHub Repo</span>
              </a>
            </div>
          </div>
        </div>
      )}
    </nav>
  );
};
