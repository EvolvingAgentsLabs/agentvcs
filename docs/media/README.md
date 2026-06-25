# docs/media

Generated explainer media for the README.

## `runtime-evolution.gif`

The 16-second explainer of the core idea: an autonomous agent rewrites its own
skills/tools/prompts at run-time, a new git release would erase that, and agentvcs
versions the run-time line and merges it back into a release **with an agent**.

Authored as a deterministic [HyperFrames](https://github.com/heygen-com/hyperframes)
composition (`runtime-evolution.html`) — HTML + CSS + GSAP, rendered locally with
headless Chrome + FFmpeg, no cloud/API.

### Regenerate

```bash
# Node 22+ and FFmpeg required.
mkdir -p /tmp/hf && cd /tmp/hf
npx --yes hyperframes@latest init agentvcs-explainer
cp /path/to/agentvcs/docs/media/runtime-evolution.html agentvcs-explainer/index.html
cd agentvcs-explainer
npx --yes hyperframes@latest lint                       # 0 errors expected
npx --yes hyperframes@latest render -f 30 -q high -o runtime-evolution.mp4

# MP4 -> optimized GIF (2-pass palette, 960px, 14fps)
ffmpeg -y -i runtime-evolution.mp4 -vf "fps=14,scale=960:-1:flags=lanczos,palettegen=stats_mode=diff" palette.png
ffmpeg -y -i runtime-evolution.mp4 -i palette.png \
  -lavfi "fps=14,scale=960:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=sierra2_4a:diff_mode=rectangle" \
  /path/to/agentvcs/docs/media/runtime-evolution.gif
```
