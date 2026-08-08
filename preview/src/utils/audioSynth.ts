// Simple Web Audio API Synthesizer for rich interactive audio demo feedback

class AudioSynth {
  private ctx: AudioContext | null = null;
  private isPlaying = false;
  private currentOsc: OscillatorNode | null = null;
  private currentGain: GainNode | null = null;
  private audioTimer: number | null = null;

  private initCtx() {
    if (!this.ctx && typeof window !== 'undefined') {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (AudioCtx) {
        this.ctx = new AudioCtx();
      }
    }
    if (this.ctx && this.ctx.state === 'suspended') {
      this.ctx.resume();
    }
  }

  public playTone(freq = 440, duration = 0.2, type: OscillatorType = 'sine') {
    try {
      this.initCtx();
      if (!this.ctx) return;

      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();

      osc.type = type;
      osc.frequency.setValueAtTime(freq, this.ctx.currentTime);

      gain.gain.setValueAtTime(0.15, this.ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.0001, this.ctx.currentTime + duration);

      osc.connect(gain);
      gain.connect(this.ctx.destination);

      osc.start();
      osc.stop(this.ctx.currentTime + duration);
    } catch {
      // Audio fallback silent
    }
  }

  public playMelodicDemo(onProgress?: (progress: number) => void, onEnd?: () => void) {
    this.initCtx();
    this.stopDemo();

    if (!this.ctx) return;

    this.isPlaying = true;
    const notes = [261.63, 329.63, 392.0, 523.25, 440.0, 349.23, 392.0, 523.25]; // C E G C A F G C
    let step = 0;
    const totalSteps = notes.length * 4;

    this.audioTimer = window.setInterval(() => {
      if (!this.isPlaying) return;

      const noteFreq = notes[step % notes.length];
      this.playTone(noteFreq, 0.25, 'triangle');

      step++;
      const progress = (step / totalSteps) * 100;

      if (onProgress) {
        onProgress(Math.min(progress, 100));
      }

      if (step >= totalSteps) {
        this.stopDemo();
        if (onEnd) onEnd();
      }
    }, 300);
  }

  public stopDemo() {
    this.isPlaying = false;
    if (this.audioTimer) {
      clearInterval(this.audioTimer);
      this.audioTimer = null;
    }
  }

  public playInteractionFeedback(type: 'like' | 'dislike' | 'download' | 'click' | 'switch') {
    switch (type) {
      case 'like':
        this.playTone(523.25, 0.12, 'sine'); // High C
        setTimeout(() => this.playTone(659.25, 0.18, 'sine'), 100); // E
        break;
      case 'dislike':
        this.playTone(300, 0.15, 'sawtooth');
        setTimeout(() => this.playTone(220, 0.2, 'sawtooth'), 100);
        break;
      case 'download':
        this.playTone(440, 0.1, 'square');
        setTimeout(() => this.playTone(880, 0.25, 'sine'), 100);
        break;
      case 'switch':
        this.playTone(600, 0.08, 'sine');
        break;
      case 'click':
      default:
        this.playTone(400, 0.05, 'triangle');
        break;
    }
  }
}

export const audioSynth = new AudioSynth();
