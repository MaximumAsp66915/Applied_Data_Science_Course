# SUT Music — Demo
### 🔗 Links

[![GitHub](https://img.shields.io/badge/GitHub-Repository-181717?style=flat-square&logo=github&logoColor=orange)](https://github.com/MaximumAsp66915/Applied_Data_Science_Course)
[![Live Demo](https://img.shields.io/badge/Live_Demo-v1-107C41?style=flat-square&logo=googlechrome&logoColor=white)](https://maximumasp66915.github.io/Applied_Data_Science_Course/demo/v1/index.html)
[![Video Clip](https://img.shields.io/badge/Demo-Video_Clip-E10098?style=flat-square&logo=html5&logoColor=white)](https://maximumasp66915.github.io/Applied_Data_Science_Course/demo/v1/demo-clip.html)

A static, self-contained phone-frame mockup of the SUT Music app. No backend,
no build step, no database, no real audio playback — track art, names,
waveforms, and stats are all hardcoded directly in the HTML. Open a file in a
browser and it just works, every time.

This folder has two versions, kept side by side:

| Version | What it is | Use it if... |
|---|---|---|
| [`v1/`](v1/README.md) | The original mockup — a single, fixed iPhone frame. `index.html` shows every screen at once in a grid of small phones; `demo-clip.html` is a self-contained cinematic auto-cycling tour. | You just need the classic iPhone-only demo, or want the simplest possible single-file setup. |
| [`v2/`](v2/README.md) | The current version — a reusable multi-device preview system. Same screens and cinematic tour as v1, but with a device picker (iPhone, Samsung S24/S26 Ultra, Galaxy Z Fold 7, Galaxy Z Flip 7, iPad Pro, MacBook Pro 14"), shared device chrome, a static "SUT MUSIC - DEMO" label, and zoom-safe sizing that scales correctly with browser/OS zoom. | You want to preview the app on different screen shapes/ratios, or want the more actively maintained version. |

Both versions present the exact same nine app screens under their own
`pages/` folder (`demo-home`, `demo-song`, `demo-song-details`, `demo-artist`,
`demo-ranks`, `demo-search`, `demo-profile`, `demo-suggest`, `demo-latest`) —
the screen content itself hasn't changed between versions, only how it's
framed and presented.

## Which one should I open?

- **Quick look, iPhone only:** `v1/index.html` (grid of all screens) or
  `v1/demo-clip.html` (auto-cycling tour).
- **Want to check other devices / screen ratios, or the actively developed
  version:** `v2/index.html` (pick a device, browse one screen at a time) or
  `v2/demo-clip.html` (pick a device, auto-cycling tour).

See each version's own README for how to edit tracks/artists/cover art, wire
up real audio, change the cinematic demo's screen order and timing, and (for
v2) add new devices.
