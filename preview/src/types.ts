export interface Track {
  id: string;
  title: string;
  artist: string;
  albumCover: string;
  duration: number; // in seconds
  genre: string;
  likesCount: number;
  playsCount: number;
  matchScore?: number; // e.g. 98%
  releaseDate?: string;
  isLiked?: boolean;
  isDisliked?: boolean;
  downloadUrl?: string;
}

export type DemoPageId = 'suggest' | 'artist' | 'latest' | 'rank' | 'profile';

export interface DemoPageInfo {
  id: DemoPageId;
  title: string;
  subtitle: string;
  badge: string;
  engineName: string;
  iconName: string;
  description: string;
}

export interface RecommendationEngine {
  id: string;
  name: string;
  pageMapping: string;
  badge: string;
  icon: string;
  summary: string;
  technicalDetails: string;
  algorithmType: string;
  features: string[];
  color: string;
}

export interface GraphNode {
  id: string;
  label: string;
  type: 'engine' | 'user' | 'track' | 'artist' | 'metric';
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  radius: number;
  color: string;
  description: string;
  active?: boolean;
}

export interface GraphEdge {
  source: string;
  target: string;
  label?: string;
  weight?: number;
}

export interface PipelineStep {
  id: number;
  title: string;
  subtitle: string;
  icon: string;
  description: string;
  status: 'idle' | 'running' | 'success';
  log: string;
}

export interface StatMetric {
  id: string;
  label: string;
  value: number;
  prefix?: string;
  suffix?: string;
  description: string;
  icon: string;
  change: string;
}
