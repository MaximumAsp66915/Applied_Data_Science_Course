import React from 'react';
import { Navbar } from './components/Navbar';
import { HeroSection } from './components/HeroSection';
import { MiniAppSimulator } from './components/MiniAppSimulator';
import { RecommendationGraphSection } from './components/RecommendationGraphSection';
import { KeyFeaturesGrid } from './components/KeyFeaturesGrid';
import { StatsSection } from './components/StatsSection';
import { PipelineSection } from './components/PipelineSection';
import { ContributionSection } from './components/ContributionSection';
import { Footer } from './components/Footer';

export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans selection:bg-emerald-500 selection:text-slate-950">
      <Navbar />
      <main>
        <HeroSection />
        <MiniAppSimulator />
        <RecommendationGraphSection />
        <KeyFeaturesGrid />
        <StatsSection />
        <PipelineSection />
        <ContributionSection />
      </main>
      <Footer />
    </div>
  );
}
