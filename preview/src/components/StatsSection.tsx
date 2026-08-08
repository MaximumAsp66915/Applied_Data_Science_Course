import React, { useState, useEffect } from 'react';
import { motion } from 'motion/react';
import { Music, Users, Zap, GitFork, TrendingUp, Sparkles } from 'lucide-react';
import { STAT_METRICS } from '../data/mockData';

export const StatsSection: React.FC = () => {
  const [animatedValues, setAnimatedValues] = useState<{ [key: string]: number }>({
    tracks: 0,
    artists: 0,
    users: 0,
    'graph-edges': 0,
  });

  useEffect(() => {
    // Count-up animation on scroll into view
    const duration = 2000;
    const steps = 40;
    const intervalTime = duration / steps;
    let stepCount = 0;

    const timer = setInterval(() => {
      stepCount++;
      const progress = Math.min(stepCount / steps, 1);

      setAnimatedValues({
        tracks: Math.floor(progress * 50000),
        artists: Math.floor(progress * 12000),
        users: Math.floor(progress * 15000),
        'graph-edges': Math.floor(progress * 120000),
      });

      if (progress >= 1) clearInterval(timer);
    }, intervalTime);

    return () => clearInterval(timer);
  }, []);

  const getMetricIcon = (icon: string) => {
    switch (icon) {
      case 'Music':
        return <Music className="w-6 h-6 text-emerald-400" />;
      case 'Users':
        return <Users className="w-6 h-6 text-cyan-400" />;
      case 'Zap':
        return <Zap className="w-6 h-6 text-amber-400" />;
      case 'GitFork':
        return <GitFork className="w-6 h-6 text-purple-400" />;
      default:
        return <TrendingUp className="w-6 h-6 text-emerald-400" />;
    }
  };

  return (
    <section id="stats" className="py-20 bg-slate-950 relative overflow-hidden">
      {/* Connected Graph Lines Background */}
      <div className="absolute inset-0 pointer-events-none opacity-20">
        <svg className="w-full h-full">
          <line x1="20%" y1="30%" x2="50%" y2="50%" stroke="#10b981" strokeWidth="1.5" strokeDasharray="4 4" />
          <line x1="50%" y1="50%" x2="80%" y2="30%" stroke="#06b6d4" strokeWidth="1.5" strokeDasharray="4 4" />
          <line x1="50%" y1="50%" x2="30%" y2="70%" stroke="#a855f7" strokeWidth="1.5" strokeDasharray="4 4" />
          <line x1="50%" y1="50%" x2="70%" y2="70%" stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="4 4" />
        </svg>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
        <div className="text-center max-w-3xl mx-auto mb-14">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold mb-3">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Scale & Metrics</span>
          </div>
          <h2 className="text-3xl sm:text-5xl font-extrabold text-white tracking-tight">
            System Scale <span className="text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 via-teal-300 to-cyan-400">By The Numbers</span>
          </h2>
          <p className="mt-3 text-slate-400 text-sm sm:text-base">
            Graph-connected node counters updated continuously across Telegram users and indexed music tracks.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {STAT_METRICS.map((metric, idx) => {
            const currentVal = animatedValues[metric.id] || metric.value;
            return (
              <motion.div
                key={metric.id}
                initial={{ opacity: 0, scale: 0.9, y: 20 }}
                whileInView={{ opacity: 1, scale: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: idx * 0.1 }}
                className="p-6 rounded-3xl bg-slate-900/90 border border-slate-800 shadow-2xl relative overflow-hidden group hover:border-emerald-500/50 hover:-translate-y-1 transition-all"
              >
                {/* Floating Node Background */}
                <div className="absolute top-2 right-2 w-16 h-16 bg-emerald-500/5 rounded-full blur-xl group-hover:bg-emerald-500/15 transition-all" />

                <div className="flex items-center justify-between mb-4">
                  <div className="p-3 rounded-2xl bg-slate-800/90 group-hover:scale-110 transition-transform">
                    {getMetricIcon(metric.icon)}
                  </div>
                  <span className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    {metric.change}
                  </span>
                </div>

                <div className="text-3xl sm:text-4xl font-black text-white font-mono tracking-tight">
                  {currentVal.toLocaleString()}{metric.suffix}
                </div>

                <h4 className="text-sm font-bold text-slate-200 mt-1">{metric.label}</h4>
                <p className="text-xs text-slate-400 mt-2 leading-relaxed">{metric.description}</p>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
};
