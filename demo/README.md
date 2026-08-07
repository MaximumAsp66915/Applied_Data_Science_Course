# SUT Music — Phone Preview Demo

This folder is a static HTML/Tailwind mockup of the SUT Music app, shown inside
a fake iPhone frame. There is no backend and no real audio playback — track
art, names, waveforms, and stats are all hardcoded in the HTML.

## Files

- `index.html` — static phone-frame preview, loads one screen at a time in an iframe.
- `ai_studio_code.html` — the animated "cinematic demo" that auto-cycles through all screens with a floating camera and on-screen controls.
- `pages/demo-home.html`, `pages/demo-song.html`, `pages/demo-song-details.html`, `pages/demo-artist.html`,
  `pages/demo-ranks.html`, `pages/demo-search.html`, `pages/demo-profile.html`, `pages/demo-suggest.html`,
  `pages/demo-latest.html` — the individual app screens.

## Changing tracks, artists, and cover art

Each screen is a self-contained HTML file with the content typed directly into
the markup — there's no shared data file. To change a track, artist, or image,
open the relevant screen(s) in a text editor and edit them by hand. The same
track/artist often appears on more than one screen, so update all of them to
keep things consistent. For example "Midnight City" / "M83" currently appears
in:

- `demo-song.html`
- `demo-song-details.html`

**Cover art / avatars** are just `<img src="...">` tags pointing to image URLs, e.g.:

```html
<img src="https://kimi-web-img.kimi.ai/img/rvamag.com/....jpg" alt="" class="w-full h-full object-cover" />
```

Replace the `src` with a link to your own image (or a local file path like
`images/my-cover.jpg` if you add an `images/` folder next to these HTML files).

**Track title / artist name** are plain text, e.g. in `demo-song.html`:

```html
<h1 class="font-display text-xl text-paper leading-tight">Midnight City</h1>
...
<span class="text-brand-glow hover:underline cursor-pointer">M83</span>
```

Just replace the text inside the tags.

**"Shared by" names**, **reaction counts**, **duration labels** (e.g. `1:24` /
`4:03`), and the **waveform bars** (a row of `<span>` elements with inline
`height:` percentages) are all similarly hardcoded per screen — search for the
text/number you want to change and edit it directly.

> Note: the waveform is only a visual decoration (styled bars), and there is no
> `<audio>` element anywhere in these files yet — see below for adding a real song.

## Adding the actual song file (audio playback)

None of the screens currently play real audio — the player UI (play/pause,
waveform, progress) is visual only. To wire up a real song:

1. Add your audio file next to the HTML files, e.g. `audio/midnight-city.mp3`.
2. In the screen that should play it (typically `demo-song.html`), add an
   `<audio>` element, for example right after the opening `<body>` tag:

   ```html
   <audio id="track-audio" src="audio/midnight-city.mp3" preload="metadata"></audio>
   ```

3. Hook the existing play/pause button up to it with a small script before
   `</body>`:

   ```html
   <script>
     const audio = document.getElementById('track-audio');
     const playBtn = document.querySelector('[aria-label="Pause"]'); // the big center button
     playBtn.addEventListener('click', () => {
       if (audio.paused) audio.play(); else audio.pause();
     });
   </script>
   ```

This is the minimum to get sound playing; syncing the waveform/progress bar to
actual playback position would need additional script (using `audio.currentTime`
and `audio.duration`).

The **ai_studio cinematic demo** (`ai_studio_code.html`) has its own separate,
fully synthetic background music generated in-browser with the Web Audio API
(no file involved) — see the `Generated ambient background music` section
near the bottom of that file's `<script>`. That's independent from any real
song file you add to the individual screens.

## The AI Studio cinematic demo (`ai_studio_code.html`)

This file shows the fake iPhone floating in 3D space, auto-cycling through
every screen with a caption and progress bar, plus playback controls
(previous / pause / mute / next) fixed below the phone.

### Changing the screen order / camera angles

Near the top of the `<script>` block is a `sequence` array — one entry per
screen shown during the demo:

```js
const sequence = [
  { url: 'pages/demo-home.html',         label: 'Home Feed',        cam: 'rotateY(0deg) rotateX(0deg) scale(1)',      stageT: 'translateZ(0px)' },
  { url: 'pages/demo-suggest.html',      label: 'AI Suggestions',   cam: 'rotateY(-12deg) rotateX(4deg) scale(1.06)', stageT: 'translateX(40px) translateZ(60px)' },
  ...
];
```

- `url` — which screen file to load into the phone.
- `label` — the caption text shown under the phone while that screen is active.
- `cam` — CSS `transform` applied to the phone itself (tilt/rotate/zoom).
- `stageT` — CSS `transform` applied to the whole stage (shifts the phone
  around the screen for a parallax effect).

Reorder, add, or remove entries to change which screens appear and in what
order. Removing an entry removes it from the loop entirely (and from the step
dots at the bottom of the HUD).

### Changing the interval / timing

A few lines above the `sequence` array:

```js
const STEP_MS = 4000;
```

This is how long (in milliseconds) each screen stays on screen before
auto-advancing to the next one. `4000` = 4 seconds. Increase it to slow the
demo down, decrease it to speed it up. This single value controls the timing
for every screen in the sequence.

The transition itself (how long the crossfade/camera move animation takes) is
controlled separately by the `transition` durations in the `<style>` block —
search for `transition: transform 1.1s` (camera/stage movement) and
`transition: opacity 0.45s` (screen crossfade) if you want to adjust those too.

### Moving the on-screen controls

The playback controls (prev/pause/mute/next) and caption live in the `.hud`
CSS rule in the `<style>` block. It's fixed near the bottom of the browser
window, below the phone:

```css
.hud {
  position: fixed;
  bottom: 12px;
  ...
}
```

Increase `bottom` to move the controls up, decrease it to move them down.

## Known quirks

- These are static demo files meant to be viewed as flat HTML (opened directly
  or via a simple local server) — they don't require a build step.
- Because there's no shared data source, any change to a track/artist/image
  needs to be repeated in every screen file that references it.
