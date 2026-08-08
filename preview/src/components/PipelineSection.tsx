import React, { useState } from 'react';
import { motion } from 'motion/react';
import { GitBranch, Cpu, PackageCheck, Server, Send, Play, CheckCircle2, Terminal, RefreshCw } from 'lucide-react';
import { PIPELINE_STEPS, OFFICIAL_LINKS } from '../data/mockData';
import { PipelineStep } from '../types';
import { audioSynth } from '../utils/audioSynth';

export const PipelineSection: React.FC = () => {
  const [steps, setSteps] = useState<PipelineStep[]>(PIPELINE_STEPS);
  const [isDeploying, setIsDeploying] = useState<boolean>(false);
  const [activeStepIndex, setActiveStepIndex] = useState<number>(4);
  const [terminalLogs, setTerminalLogs] = useState<string[]>([
    'Pipeline initialized: Applied_Data_Science_Course',
    'CI/CD status: Deployed & Healthy (100% Uptime)',
  ]);

  const triggerPipelineBuild = () => {
    if (isDeploying) return;

    setIsDeploying(true);
    setActiveStepIndex(0);
    setTerminalLogs(['[CI/CD] Starting automated build trigger...']);
    audioSynth.playInteractionFeedback('click');

    let currentStep = 0;
    const interval = setInterval(() => {
      if (currentStep < PIPELINE_STEPS.length) {
        const step = PIPELINE_STEPS[currentStep];
        setActiveStepIndex(currentStep);
        setTerminalLogs((prev) => [...prev, `[Step ${step.id}] ${step.log}`]);
        audioSynth.playInteractionFeedback('switch');
        currentStep++;
      } else {
        clearInterval(interval);
        setIsDeploying(false);
        setActiveStepIndex(PIPELINE_STEPS.length - 1);
        setTerminalLogs((prev) => [
          ...prev,
          ' SUCCESS: Live @SUTMusic_Bot engine updated with zero downtime!',
        ]);
        audioSynth.playInteractionFeedback('like');
      }
    }, 1200);
  };

  const getStepIcon = (icon: string) => {
    switch (icon) {
      case 'GitBranch':
        return <GitBranch className="w-5 h-5 text-sky-400" />;
      case 'Cpu':
        return <Cpu className="w-5 h-5 text-emerald-400" />;
      case 'PackageCheck':
        return <PackageCheck className="w-5 h-5 text-purple-400" />;
      case 'Server':
        return <Server className="w-5 h-5 text-amber-400" />;
      case 'Send':
        return <Send className="w-5 h-5 text-teal-400" />;
      default:
        return <GitBranch className="w-5 h-5 text-emerald-400" />;
    }
  };

  return (
    <section id="pipeline" className="py-20 bg-slate-950 relative overflow-hidden">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 relative z-10">
        <div className="text-center max-w-3xl mx-auto mb-14">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-semibold mb-3">
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            <span>Continuous Integration & Deployment</span>
          </div>
          <h2 className="text-3xl sm:text-5xl font-extrabold text-white tracking-tight">
            Code Commit to <span className="text-transparent bg-clip-text bg-gradient-to-r from-emerald-400 via-teal-300 to-cyan-400">Live Bot Server</span>
          </h2>
          <p className="mt-3 text-slate-400 text-sm sm:text-base">
            Automated CI/CD pipeline motion: how code updates and model retrainings automatically propagate to @SUTMusic_Bot.
          </p>
        </div>

        {/* Trigger Interactive Simulation Button */}
        <div className="flex justify-center mb-10">
          <button
            onClick={triggerPipelineBuild}
            disabled={isDeploying}
            className={`flex items-center gap-2.5 px-6 py-3 rounded-2xl text-xs font-bold transition-all shadow-xl ${
              isDeploying
                ? 'bg-slate-800 text-slate-400 border border-slate-700 cursor-not-allowed'
                : 'bg-gradient-to-r from-emerald-500 to-teal-500 text-slate-950 hover:shadow-emerald-500/30 hover:scale-[1.02]'
            }`}
          >
            {isDeploying ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin text-emerald-400" />
                <span>Simulating CI/CD Deploy Flow...</span>
              </>
            ) : (
              <>
                <Play className="w-4 h-4 fill-slate-950 text-slate-950" />
                <span>Simulate Code Push & Deploy Motion</span>
              </>
            )}
          </button>
        </div>

        {/* Horizontal Pipeline Steps Motion Grid */}
        <div className="grid grid-cols-1 md:grid-cols-5 gap-4 mb-10 relative">
          {PIPELINE_STEPS.map((step, idx) => {
            const isActive = idx === activeStepIndex;
            const isPassed = idx < activeStepIndex;

            return (
              <motion.div
                key={step.id}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.4, delay: idx * 0.1 }}
                className={`p-4 rounded-2xl border transition-all relative overflow-hidden flex flex-col justify-between ${
                  isActive
                    ? 'bg-slate-900 border-emerald-500/80 shadow-lg shadow-emerald-500/20 ring-1 ring-emerald-500/50'
                    : isPassed
                    ? 'bg-slate-900/60 border-slate-700/80 text-slate-300'
                    : 'bg-slate-900/30 border-slate-800 text-slate-500'
                }`}
              >
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <div className="p-2 rounded-xl bg-slate-800">
                      {getStepIcon(step.icon)}
                    </div>
                    <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-slate-800">
                      0{step.id}
                    </span>
                  </div>

                  <h4 className="text-xs font-bold text-white mb-1">{step.title}</h4>
                  <p className="text-[10px] font-semibold text-emerald-400 mb-2">{step.subtitle}</p>
                  <p className="text-[11px] text-slate-400 leading-normal">{step.description}</p>
                </div>

                <div className="mt-4 pt-2 border-t border-slate-800 flex items-center justify-between text-[10px] font-mono">
                  {isPassed ? (
                    <span className="text-emerald-400 flex items-center gap-1 font-bold">
                      <CheckCircle2 className="w-3 h-3" /> Passed
                    </span>
                  ) : isActive ? (
                    <span className="text-amber-400 flex items-center gap-1 font-bold animate-pulse">
                      Processing...
                    </span>
                  ) : (
                    <span className="text-slate-600">Idle</span>
                  )}
                </div>
              </motion.div>
            );
          })}
        </div>

        {/* Live Terminal Build Output Logs */}
        <div className="bg-slate-950 rounded-2xl p-4 border border-slate-800 font-mono text-xs shadow-2xl">
          <div className="flex items-center gap-2 pb-2 border-b border-slate-800 text-slate-400 mb-3">
            <Terminal className="w-4 h-4 text-emerald-400" />
            <span className="font-bold text-slate-200">Live CI/CD Deployment Terminal</span>
          </div>
          <div className="space-y-1.5 max-h-36 overflow-y-auto">
            {terminalLogs.map((log, i) => (
              <div key={i} className="text-emerald-400/90 leading-relaxed">
                {log}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
};
