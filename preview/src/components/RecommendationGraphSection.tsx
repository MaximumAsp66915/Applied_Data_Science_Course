import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import {
  Sparkles,
  Mic2,
  Radio,
  Trophy,
  Heart,
  Send,
  GitFork,
  CheckCircle2,
  Sliders,
  Layers,
  Info,
  ArrowRight
} from 'lucide-react';
import { RECOMMENDATION_ENGINES, GRAPH_NODES, GRAPH_EDGES, OFFICIAL_LINKS } from '../data/mockData';
import { RecommendationEngine } from '../types';
import { audioSynth } from '../utils/audioSynth';

export const RecommendationGraphSection: React.FC = () => {
  const [selectedEngine, setSelectedEngine] = useState<RecommendationEngine>(RECOMMENDATION_ENGINES[0]);
  const [activeTab, setActiveTab] = useState<string>('recommendation-engine');
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Sync selected engine when tab changes
  const handleSelectEngine = (engine: RecommendationEngine) => {
    setSelectedEngine(engine);
    setActiveTab(engine.id);
    audioSynth.playInteractionFeedback('switch');
  };

  // Render dynamic animated graph canvas background
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let width = (canvas.width = canvas.parentElement?.clientWidth || 600);
    let height = (canvas.height = canvas.parentElement?.clientHeight || 400);

    const handleResize = () => {
      if (canvas && canvas.parentElement) {
        width = canvas.width = canvas.parentElement.clientWidth;
        height = canvas.height = canvas.parentElement.clientHeight;
      }
    };
    window.addEventListener('resize', handleResize);

    // Node positioning math
    const nodes = GRAPH_NODES.map((node, idx) => {
      const angle = (idx / GRAPH_NODES.length) * Math.PI * 2;
      const radiusOffset = node.type === 'user' ? 0 : 120 + (idx % 3) * 30;
      return {
        ...node,
        x: width / 2 + Math.cos(angle) * radiusOffset,
        y: height / 2 + Math.sin(angle) * (radiusOffset * 0.7),
        vx: (Math.random() - 0.5) * 0.4,
        vy: (Math.random() - 0.5) * 0.4,
      };
    });

    // Render loop
    const render = () => {
      ctx.clearRect(0, 0, width, height);

      // Draw glowing edges
      GRAPH_EDGES.forEach((edge) => {
        const srcNode = nodes.find((n) => n.id === edge.source);
        const tgtNode = nodes.find((n) => n.id === edge.target);

        if (srcNode && tgtNode) {
          const isSelected =
            selectedEngine &&
            (srcNode.id.includes(selectedEngine.id.split('-')[0]) ||
              tgtNode.id.includes(selectedEngine.id.split('-')[0]));

          ctx.beginPath();
          ctx.moveTo(srcNode.x, srcNode.y);
          ctx.lineTo(tgtNode.x, tgtNode.y);

          ctx.strokeStyle = isSelected ? 'rgba(16, 185, 129, 0.8)' : 'rgba(148, 163, 184, 0.15)';
          ctx.lineWidth = isSelected ? 2.5 : 1;
          ctx.stroke();

          // Particle flow on edge
          if (isSelected) {
            const time = Date.now() * 0.002;
            const progress = (time % 1);
            const px = srcNode.x + (tgtNode.x - srcNode.x) * progress;
            const py = srcNode.y + (tgtNode.y - srcNode.y) * progress;

            ctx.beginPath();
            ctx.arc(px, py, 3, 0, Math.PI * 2);
            ctx.fillStyle = '#34d399';
            ctx.shadowColor = '#34d399';
            ctx.shadowBlur = 8;
            ctx.fill();
            ctx.shadowBlur = 0;
          }
        }
      });

      // Update & Draw nodes
      nodes.forEach((node) => {
        node.x += node.vx;
        node.y += node.vy;

        // Bounce off canvas edges
        if (node.x < 40 || node.x > width - 40) node.vx *= -1;
        if (node.y < 40 || node.y > height - 40) node.vy *= -1;

        const isHighlighted =
          selectedEngine &&
          (node.id.includes(selectedEngine.id.split('-')[0]) || node.type === 'user');

        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
        ctx.fillStyle = isHighlighted ? node.color : '#334155';
        ctx.fill();

        ctx.lineWidth = isHighlighted ? 3 : 1;
        ctx.strokeStyle = isHighlighted ? '#ffffff' : '#64748b';
        ctx.stroke();

        // Node Label
        ctx.fillStyle = isHighlighted ? '#ffffff' : '#94a3b8';
        ctx.font = isHighlighted ? 'bold 11px sans-serif' : '10px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(node.label, node.x, node.y + node.radius + 14);
      });

      animationFrameId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener('resize', handleResize);
    };
  }, [selectedEngine]);

  const getEngineIcon = (icon: string) => {
    switch (icon) {
      case 'Sparkles':
        return <Sparkles className="w-5 h-5 text-emerald-400" />;
      case 'Mic2':
        return <Mic2 className="w-5 h-5 text-purple-400" />;
      case 'Clock':
        return <Radio className="w-5 h-5 text-cyan-400" />;
      case 'TrendingUp':
        return <Trophy className="w-5 h-5 text-amber-400" />;
      case 'Heart':
        return <Heart className="w-5 h-5 text-pink-400 fill-pink-400/20" />;
      case 'Send':
        return <Send className="w-5 h-5 text-blue-400" />;
      default:
        return <GitFork className="w-5 h-5 text-emerald-400" />;
    }
  };

  return (
    <section id="recommendation-systems" className="py-20 bg-slate-950 relative overflow-hidden">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
        {/* Header */}
        <div className="text-center max-w-3xl mx-auto mb-12">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold mb-3">
            <GitFork className="w-3.5 h-3.5" />
            <span>Connected Recommendation Graph</span>
          </div>
          <h2 className="text-3xl sm:text-5xl font-extrabold text-white tracking-tight">
            Six Specialized <span className="text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 via-teal-300 to-cyan-400">AI Suggestion Engines</span>
          </h2>
          <p className="mt-3 text-slate-400 text-sm sm:text-base">
            Click any engine pop-up card to observe its live graph connections, vector formulas, and Telegram Web App screen integration.
          </p>
        </div>

        {/* Engine Selection Pop-up Tabs */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-10">
          {RECOMMENDATION_ENGINES.map((engine) => {
            const isSelected = selectedEngine.id === engine.id;
            return (
              <button
                key={engine.id}
                onClick={() => handleSelectEngine(engine)}
                className={`p-3.5 rounded-2xl text-left border transition-all relative overflow-hidden group ${
                  isSelected
                    ? 'bg-slate-900 border-emerald-500/80 shadow-lg shadow-emerald-500/15 -translate-y-1'
                    : 'bg-slate-900/40 border-slate-800 hover:border-slate-700 hover:bg-slate-900/70'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="p-2 rounded-xl bg-slate-800/80 group-hover:scale-110 transition-transform">
                    {getEngineIcon(engine.icon)}
                  </div>
                  <span className="text-[10px] font-mono text-slate-400 font-semibold px-2 py-0.5 rounded bg-slate-800">
                    {engine.pageMapping}
                  </span>
                </div>
                <h4 className="text-xs font-bold text-white line-clamp-1">{engine.name}</h4>
                <p className="text-[10px] text-slate-400 mt-0.5 truncate">{engine.badge}</p>

                {isSelected && (
                  <motion.div
                    layoutId="activeGlow"
                    className="absolute inset-0 border-2 border-emerald-500/80 rounded-2xl pointer-events-none"
                  />
                )}
              </button>
            );
          })}
        </div>

        {/* Main Graph Visualizer & Expanded Pop-up Detail Card */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-stretch">
          {/* Left Canvas Graph Visualizer */}
          <div className="lg:col-span-7 bg-slate-900/80 rounded-3xl p-4 border border-slate-800 shadow-2xl relative flex flex-col justify-between min-h-[420px]">
            <div className="flex items-center justify-between mb-2 px-2 pt-2 z-10">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-ping" />
                <span className="text-xs font-bold text-slate-300">Live Vector Proximity Graph</span>
              </div>
              <span className="text-[11px] text-slate-500 font-mono">Real-time Node Connections</span>
            </div>

            {/* Interactive HTML5 Canvas */}
            <div className="relative w-full h-[340px] rounded-2xl overflow-hidden bg-slate-950/60 border border-slate-800/80">
              <canvas ref={canvasRef} className="w-full h-full block" />
            </div>

            <div className="mt-3 flex items-center justify-between text-[11px] text-slate-400 px-2 font-mono">
              <span>Selected Node: <strong className="text-emerald-400">{selectedEngine.name}</strong></span>
              <span>Sub-system: <strong className="text-cyan-400">{selectedEngine.pageMapping}</strong></span>
            </div>
          </div>

          {/* Right Pop-up Motion Details Card */}
          <div className="lg:col-span-5">
            <AnimatePresence mode="wait">
              <motion.div
                key={selectedEngine.id}
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -15 }}
                transition={{ duration: 0.3 }}
                className="bg-slate-900/90 rounded-3xl p-6 border border-emerald-500/30 shadow-2xl space-y-5 h-full flex flex-col justify-between"
              >
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <span className="px-3 py-1 rounded-full text-xs font-mono font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      {selectedEngine.badge}
                    </span>
                    <span className="text-xs text-slate-400 font-semibold">{selectedEngine.pageMapping}</span>
                  </div>

                  <h3 className="text-2xl font-extrabold text-white flex items-center gap-2">
                    {getEngineIcon(selectedEngine.icon)}
                    <span>{selectedEngine.name}</span>
                  </h3>

                  <p className="text-sm text-slate-300 mt-2 leading-relaxed">
                    {selectedEngine.summary}
                  </p>

                  <div className="mt-4 p-3.5 bg-slate-950/80 rounded-2xl border border-slate-800 space-y-1">
                    <span className="text-[10px] font-mono font-bold text-slate-400 uppercase tracking-wider">Algorithm Class</span>
                    <p className="text-xs font-semibold text-emerald-300">{selectedEngine.algorithmType}</p>
                    <p className="text-xs text-slate-400 mt-1 leading-normal">{selectedEngine.technicalDetails}</p>
                  </div>

                  <div className="mt-4 space-y-2">
                    <h5 className="text-xs font-bold text-slate-200 uppercase tracking-wider">Key Engine Features:</h5>
                    {selectedEngine.features.map((feat, idx) => (
                      <div key={idx} className="flex items-center gap-2 text-xs text-slate-300">
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
                        <span>{feat}</span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="pt-4 border-t border-slate-800 flex items-center justify-between">
                  <a
                    href={OFFICIAL_LINKS.notebooksDoc}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs font-semibold text-emerald-400 hover:underline flex items-center gap-1"
                  >
                    <span>View Notebook Implementation</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </a>

                  <a
                    href={OFFICIAL_LINKS.webApp}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-3 py-1.5 rounded-xl bg-emerald-500/10 text-emerald-400 text-xs font-bold hover:bg-emerald-500/20 transition-all"
                  >
                    Test in App
                  </a>
                </div>
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </div>
    </section>
  );
};
