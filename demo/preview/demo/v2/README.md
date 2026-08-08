# SUT Music — Demo (v2)

### 🔗 Links

[![GitHub](https://img.shields.io/badge/GitHub-Repository-181717?style=flat-square&logo=github&logoColor=orange)](https://github.com/MaximumAsp66915/Applied_Data_Science_Course)
[![Live Demo](https://img.shields.io/badge/Live_Demo-v2-107C41?style=flat-square&logo=googlechrome&logoColor=white)](https://maximumasp66915.github.io/Applied_Data_Science_Course/demo/v2/index.html)
[![Video Clip](https://img.shields.io/badge/Demo-Video_Clip-E10098?style=flat-square&logo=html5&logoColor=white)](https://maximumasp66915.github.io/Applied_Data_Science_Course/demo/v2/demo-clip.html)

A static HTML/Tailwind mockup of the SUT Music app, shown inside a realistic
device frame. There is no backend and no real audio playback — track art,
names, waveforms, and stats are all hardcoded in the HTML.

v2 rebuilds v1's single fixed iPhone into a **reusable, multi-device preview
system**: pick any of seven device frames from a dropdown, at any of the
individual app screens, or run the auto-cycling cinematic tour. If you just
need the one classic iPhone-only version, see [`../v1/README.md`](../v1/README.md).

## What's new vs v1

- **Device picker** — a dropdown (top-right corner) to switch the preview
  between seven device shells without touching any code.
- **Shared device chrome** — the phone/tablet/laptop frame, buttons, camera
  cutouts, etc. now live once in `device/device-preview.js` +
  `device/device-preview.css`, instead of being duplicated inline in every
  page like v1.
- **Zoom-safe, "full size" layout** — the page fills its real document box
  (not `100vw`/`100vh`), and each device shell fits its container via plain
  CSS (`aspect-ratio` + `max-width`/`max-height`), with no JavaScript
  measuring the container or recalculating a scale. That means browser/OS
  zoom (pinch, ctrl+scroll, the zoom control in the URL bar) enlarges the
  whole page in place, the way zoom works on any normal webpage, instead of
  the layout shrinking or the page shifting around.
- **Static "SUT MUSIC - DEMO" label** — the caption above the device no
  longer changes to the selected device's name; it's a fixed title regardless
  of which device is picked.

## Files

- `index.html` — thin wrapper that embeds `device/index.html` in an iframe
  filling the page.
- `demo-clip.html` — thin wrapper that embeds `device/iphone-preview.html`
  (the cinematic demo) in an iframe filling the page.
- `device/device-preview.js` — device definitions (real screen ratios,
  button layout, camera cutout style per device) and the shared DOM-building
  logic that assembles a device shell around whatever screen you pass it.
- `device/device-preview.css` — all shell/chrome styling: corner radii,
  bezels, buttons, camera cutouts, hinge lines (foldables), and the zoom-safe
  sizing rules described above.
- `device/index.html` — the actual single-screen preview page (device picker
  + one screen at a time, loaded via `?device=...&page=...` query params).
- `device/iphone-preview.html` — the actual cinematic demo page (device
  picker + auto-cycling camera tour across all screens, plus synthetic
  background music).
- `pages/demo-home.html`, `pages/demo-song.html`, `pages/demo-song-details.html`,
  `pages/demo-artist.html`, `pages/demo-ranks.html`, `pages/demo-search.html`,
  `pages/demo-profile.html`, `pages/demo-suggest.html`, `pages/demo-latest.html`
  — the individual app screens (same content as v1, unchanged).

## Available devices

Selectable from the dropdown in the top-right corner of both `index.html` and
`demo-clip.html`:

| Device | Notes |
|---|---|
| iPhone 17 Pro Max | Dynamic Island, iPhone-style side buttons (mute + volume left, power right). |
| Samsung S24 Ultra | Flat titanium-style frame, centered punch-hole camera, volume rocker + power on the right edge only (no mute switch), S-Pen slot. |
| Samsung S26 Ultra | Same Samsung-accurate chrome as the S24 Ultra, sized to its own real screen ratio. |
| Galaxy Z Fold 7 (foldable) | Unfolded inner-screen ratio, with a hinge line down the middle. |
| Galaxy Z Flip 7 (foldable) | Tall/narrow cover-open ratio, with a horizontal hinge line. |
| iPad Pro | Larger tablet ratio, webcam dot instead of a phone-style camera cutout. |
| MacBook Pro 14" (laptop) | Landscape ratio, laptop-style chin/logo notch instead of side buttons. |

Each shell's width/height/aspect-ratio is set to match that device's real CSS
(logical) viewport, not its native panel resolution, so the on-screen
proportions are representative even though the rendered size is scaled down.

## Adding or adjusting a device

Open `device/device-preview.js` and add a new entry to the
`deviceDefinitions` object:

```js
'my-new-device': {
  label: 'My New Device',
  shell: { width: 400, height: 860, radius: 40, padding: 10, screenRadius: 30, screenTop: 0, screenBottom: 0 },
  buttons: true,
  island: false,
  punchHole: true,
  homeIndicator: false,
  frameClass: 'android'
}
```

Then add a matching `<option>` to the `<select id="devicePicker">` in both
`device/index.html` and `device/iphone-preview.html`. Corner radii, bezel
color, and any device-specific chrome (hinge lines, S-Pen slot, camera style)
are controlled by the `[data-device='...']` / `[data-frame='...']` selectors
in `device/device-preview.css`.

## Changing tracks, artists, and cover art

Same as v1 — each screen under `pages/` is self-contained with content typed
directly into the markup, so changes need to be made per-file. See
[`../v1/README.md`](../v1/README.md#changing-tracks-artists-and-cover-art)
for the full walkthrough (cover art, track/artist text, "shared by" names,
reaction counts, durations, waveform bars) — it applies identically here
since the `pages/` content itself didn't change between v1 and v2.

## Adding the actual song file (audio playback)

Also unchanged from v1 — see
[`../v1/README.md`](../v1/README.md#adding-the-actual-song-file-audio-playback)
for adding an `<audio>` element and wiring it to the existing play/pause
button.

The cinematic demo's own ambient background music is still fully synthetic,
generated in-browser with the Web Audio API — see the `startMusic`/`stopMusic`
functions in `device/iphone-preview.html`'s `<script>`.

## The cinematic demo (`device/iphone-preview.html`)

Shows the selected device floating in 3D space, auto-cycling through every
screen with a caption, progress bar, and playback controls (previous / pause
/ mute / next).

### Changing the screen order / camera angles

Near the top of the `<script>` block is a `sequence` array — one entry per
screen shown during the demo:

```js
const sequence = [
  { url: '../pages/demo-home.html',    label: 'Home Feed',      cam: 'rotateY(0deg) rotateX(0deg) scale(1)',      stageT: 'translateZ(0px)' },
  { url: '../pages/demo-suggest.html', label: 'AI Suggestions', cam: 'rotateY(-12deg) rotateX(4deg) scale(1.06)', stageT: 'translateX(40px) translateZ(60px)' },
  ...
];
```

- `url` — which screen file to load into the device (paths are relative to
  `device/`, hence the `../pages/...`).
- `label` — the caption text shown under the device while that screen is active.
- `cam` — CSS `transform` applied to the device shell itself (tilt/rotate/zoom).
- `stageT` — CSS `transform` applied to the `.demo-clip-device` wrapper
  (shifts the device around the screen for a parallax effect, layered on top
  of `cam`).

Reorder, add, or remove entries to change which screens appear and in what
order.

### Changing the interval / timing

```js
const STEP_MS = 4000;
```

How long (ms) each screen stays up before auto-advancing. The crossfade/
camera-move animation speed is controlled separately, via the `transition`
rules in `device/device-preview.css` — search for `transition: transform 1.1s`
(camera/stage movement) and `transition: opacity 0.45s` (screen crossfade).

## Known quirks

- Static demo files meant to be viewed as flat HTML (opened directly or via
  a simple local server) — no build step required.
- No shared data source: a change to a track/artist/image needs to be
  repeated in every screen file that references it (same trade-off as v1).
- Device sizing is intentionally CSS-only (no JS-measured fit/scale) so that
  browser zoom behaves natively — if you add a new device, keep any sizing
  changes in `device-preview.css`'s `max-width`/`max-height`/`aspect-ratio`
  rules rather than reintroducing a JS resize/fit calculation.
