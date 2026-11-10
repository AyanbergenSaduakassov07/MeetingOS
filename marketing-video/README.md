# MeetingOS launch film

A 60 s, 1920×1080, 30 fps launch film made with [Remotion](https://remotion.dev). Every product shot is a real screenshot of the running MeetingOS app; nothing on screen is a mock-up.

| Output | File |
|---|---|
| Film (H.264, CRF 16, AAC 320k) | `output/MeetingOS-Launch-Film.mp4` |
| LinkedIn thumbnail (1920×1080) | `output/MeetingOS-thumbnail.png` |

`output/` is gitignored. Render it locally (below); the finished film and thumbnail were also copied to `~/Desktop`.

## Preview, edit, re-render

```bash
cd marketing-video
bun install            # or npm install
npm run studio         # live preview with a timeline, at http://localhost:3000
npm run render         # writes output/MeetingOS-Launch-Film.mp4 (~30 s on an M-series Mac)
npm run thumbnail      # writes output/MeetingOS-thumbnail.png
npx tsc -p .           # type check
```

## Structure

| Time | Scene | File |
|---|---|---|
| 0–7 s | Opening: "Every meeting creates information." over a real meeting's waveform | `src/scenes/Opening.tsx` |
| 7–14 s | Product reveal: logo, then the dashboard | `src/scenes/ProductReveal.tsx` |
| 14–28 s | Workflow: consent → processing → timestamped transcript, with the meeting's own audio | `src/scenes/LiveMeeting.tsx` |
| 28–43 s | Intelligence: decisions with cited timestamps, risks and actions, RU and KK | `src/scenes/Intelligence.tsx` |
| 43–53 s | Copilot: a question, the streamed answer, its sources | `src/scenes/Copilot.tsx` |
| 53–60 s | Lockup: "Every meeting. More meaningful." plus credits | `src/scenes/Closing.tsx` |

- **Timing:** scene start frames live in `T` in `src/theme.ts`. Colours, fonts and easing are in the same file.
- **Camera moves:** each `<Shot>` takes `keys`: a list of `{ at: frame, rect: [x, y, w, h] }` in screenshot pixels (3200×2000). The camera eases between them. See `src/components/Shot.tsx`.
- **If you move a scene cut,** also update `CUTS_S` and `TICKS_S` in `scripts/make_audio.py` and run `npm run audio`, so the score's hits still land on the cuts.

## Re-capturing the footage

`scripts/capture.py` drives the running app with Playwright at 2× and writes `public/screenshots/`.

1. Start the backend on :8470 and the web app on :5174 (see the root README). Use a scratch data directory that holds **only** the demo meetings (AMI ES2002a, FLEURS kk, FLEURS ru, and the short pricing clip used for the upload shots). Meeting titles in the background of the consent shot are visible, so nothing else may be in that list.
2. Run the capture from the repo root:

```bash
FILM_AMI_WAV=/path/to/ES2002a.wav \
  .venv/bin/python marketing-video/scripts/capture.py              # every step
# or a subset: ... capture.py english copilot languages upload
```

- **Optional variables:**
  - `MEETINGOS_API_KEY`: only if the backend requires a key. It is read from the environment and is never shown on screen.
  - `FILM_BASE_URL`: the app's address, if it isn't on :5174.
- **Meeting IDs:** `AMI_ID`, `KK_ID` and `RU_ID` at the top of `capture.py` are the demo meetings in the scratch DB used for filming. Change them to match your own uploads.
- **Steps:** `english` (dashboard, summary, item cards), `upload` (consent → processing → transcript), `languages` (KK and RU transcript panels), `copilot` (replayed answer frames).

## Audio

`npm run audio` runs `scripts/make_audio.py` and rebuilds these files:

| File | What it is |
|---|---|
| `public/audio/score.wav` | Original score, synthesized from scratch with numpy: a pad, low hits on the cuts, UI ticks, a riser, and a resolve on the logo. It uses no samples and no licensed music. |
| `public/audio/voice.wav` | 6.5 s from the AMI ES2002a meeting ("…selling this remote control for 25 euro"). Built only when `FILM_AMI_WAV` is set. |
| `src/peaks.json` | The opening's waveform bars, taken from the same meeting. Built only when `FILM_AMI_WAV` is set. |

## Honesty notes: read before publishing

- **Demo data only.** The meetings are public research corpora:
  - AMI Meeting Corpus ES2002a, CC BY 4.0.
  - FLEURS Kazakh (kk_kz) and Russian (ru_ru) dev clips, CC BY 4.0: anonymous read speech, concatenated into one recording per language.
  - Earlier footage that showed a Russian government-meeting recording and an interview with a named person was removed. Both were dropped from the filming database, and every shot was recaptured.
  - The credits line on the lockup names the corpora.
- **Copilot answer is a replay.** The OpenRouter free quota was exhausted while filming. The question, the answer text and the 5 cited segments come from a real earlier run of the same question. `capture.py` streams them back through the real copilot UI by intercepting `/ask/stream` in the browser. The credits say "Copilot answer replayed from a recorded run".
- **Framed-out banner.** Because of the same quota, every meeting page shows an amber "Extraction did not finish" banner. The camera framing keeps it out of view. The extracted items shown were produced earlier and are real, but all are "Not yet verified", as the cards show.
- **No claims beyond the product.** The film does not claim:
  - live or real-time transcription (the flow shown is upload → processing → transcript);
  - speaker identification;
  - on-device processing. The default transcription provider is cloud Whisper, so "private" or "local" claims would be wrong for the default setup.
- **No credentials or private data on screen.** Captures run against a scratch data directory with no API key in the UI. The only meeting titles behind the consent dialog are the demo meetings listed above.

## Tooling note

Installing the official Remotion Claude Code plugin was blocked during production. To add it yourself:

```
claude plugin marketplace add remotion-dev/claude-code-plugin
claude plugin install remotion@remotion
```
