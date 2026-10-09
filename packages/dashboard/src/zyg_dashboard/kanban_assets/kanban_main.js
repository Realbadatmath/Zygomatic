// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* ── Utility helpers ─────────────────────────────────────────────────────────── */
function randId()      { return 'job-' + Math.random().toString(36).slice(2,7).toUpperCase(); }
function randEl(arr)   { return arr[Math.floor(Math.random() * arr.length)]; }
function randInt(a, b) { return Math.floor(Math.random() * (b - a + 1)) + a; }
function timeAgo(sec)  {
  if (sec < 60)   return sec + 's ago';
  if (sec < 3600) return Math.floor(sec/60) + 'm ago';
  return Math.floor(sec/3600) + 'h ago';
}
/* Card clocks come from the server (card_times), never from Date.now() here:
   the page only knows what it saw while it was open, so a freshly loaded board
   cannot date a stage that started hours ago.  Both helpers render '—' for a
   card the pipeline has no timeline row for — a queued card has genuinely not
   started, and the placeholders these replaced claimed "0s ago / 0s" for it. */
function timeAgoOrDash(sec) {
  if (sec === null || sec === undefined || !isFinite(sec)) return '—';
  return timeAgo(Math.max(0, Math.round(sec)));
}
/* Same shape as pipeline_runtime.format_runtime, so a card's Duration and the
   Live Tail's ⏱ Pipeline Runtime read alike. */
function fmtDuration(sec) {
  if (sec === null || sec === undefined || !isFinite(sec)) return '—';
  const t = Math.max(0, Math.round(sec));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), ss = t % 60;
  const pad = n => String(n).padStart(2, '0');
  return h ? `${h}h ${pad(m)}m ${pad(ss)}s` : `${m}m ${pad(ss)}s`;
}

const TEMPLATES = {

  /* ══════════════════════════════════════════════════════════════════════════
     DOCUMENTARY PIPELINE
  ══════════════════════════════════════════════════════════════════════════ */
  documentary: {
    name: 'Documentary',
    label: '[ DOCUMENTARY PIPELINE ]',
    columns: [

      /* ── Research ── */
      { id: 'research', name: 'Research', cards: [

        { prompt: 'Topic Setup', agent: 'Claude claude-sonnet-4-5',
          meta: {
            description: '<p><strong>Translates the raw user directive into a structured production brief.</strong></p><ul><li>Calls Claude claude-sonnet-4-5 with the user topic/directive</li><li>Returns structured JSON: scene count, visual style, tone, per-scene narration targets</li><li>Output is the master spec that drives every downstream stage</li></ul>',
            llms:  ['claude-sonnet-4-6 (Anthropic)'],
            tools: ['Anthropic Messages API', 'JSON brief parser'],
          }},

        { prompt: 'Playwright Web Research', agent: 'Super Browser Agent',
          meta: {
            description: '<p><strong>Autonomous browser agent that gathers live source material from the web.</strong></p><ul><li>Opens real web pages, follows links relevant to the topic</li><li>Extracts and summarises text from each page</li><li>Output feeds directly into Script Generation</li></ul>',
            llms:  ['—'],
            tools: ['Playwright / headless Chromium', 'HTML scraper', 'Search engine API', 'Link follower'],
          }},

        { prompt: 'Semantic Scholar + arXiv', agent: 'Research Agent',
          meta: {
            description: '<p><strong>Retrieves peer-reviewed sources to substantiate the documentary script.</strong></p><ul><li>Queries Semantic Scholar and arXiv for papers matching the topic</li><li>Extracts citations, abstracts, and key statistics</li><li>Merges results into the shared research context</li></ul>',
            llms:  ['—'],
            tools: ['Semantic Scholar API', 'arXiv search API', 'PDF text extractor'],
          }},

        { prompt: 'PDF + Vector Document Search', agent: 'Document Agent',
          meta: {
            description: '<p><strong>Mines user-uploaded documents and local knowledge base for relevant content.</strong></p><ul><li>Parses PDFs, Word files, and text documents</li><li>Runs vector similarity search to find topic-relevant chunks</li><li>Retrieved content feeds into Script Generation alongside web research</li></ul>',
            llms:  ['—'],
            tools: ['PDF parser (PyMuPDF)', 'Vector similarity search (FAISS/chroma)', 'Document chunk retriever'],
          }},

      ]},

      /* ── Scripting ── */
      { id: 'scripting', name: 'Scripting', cards: [

        { prompt: 'Script Generation', agent: 'Claude claude-sonnet-4-6',
          meta: {
            description: '<p><strong>Synthesises all research into the canonical production script.</strong></p><ul><li>Aggregates web, academic, and document research into a single context window</li><li>Generates a full scene-by-scene script: headings, narration blocks, on-screen text, timing cues</li><li>Output JSON is the source of truth for all generation stages</li></ul>',
            llms:  ['claude-sonnet-4-6 (Anthropic)'],
            tools: ['Anthropic Messages API', 'Research aggregator', 'JSON scene formatter'],
          }},

        { prompt: 'Murch Engine — Emotion & Rhythm', agent: 'Murch Engine (murch_engine.py)',
          meta: {
            description: '<p><strong>Tags each scene with emotional and rhythmic metadata — inspired by Walter Murch\'s editing theory.</strong></p><ul><li>Classifies each scene: tension / wonder / grief / awe / triumph / mystery / unease / shock</li><li>Scores pacing tension and edit rhythm per scene</li><li>Produces per-scene shot_type (medium / wide / close-up / overhead / low) and focal_zone (center / left / right / top / bottom)</li><li><strong>Hard-cut guard</strong>: shock/tension always cut — never cross-faded</li><li><strong>Emotion speed multiplier</strong>: grief=0.55×, calm=0.70×, mystery=0.80×, awe=1.0×, tension=1.4×, shock=1.5×</li></ul>',
            llms:  ['—'],
            tools: ['murch_engine.py', '_TRANSITION_TABLE (31 entries)', '_SHOT_TRANSITION_OVERRIDES (17 rules)', 'Scene emotion tagger', 'Pacing analyser'],
          }},

        { prompt: 'Visual Intent Tagging', agent: 'Claude claude-sonnet-4-5',
          meta: {
            description: '<p><strong>Assigns a visual intent tag to each scene to steer FLUX image prompts.</strong></p><ul><li>Reads each scene narration text</li><li>Classifies: establishing shot / close-up detail / abstract concept / character portrait / action sequence</li><li>Tags are used by the FLUX prompt builder — identity tags trigger seed locking</li></ul>',
            llms:  ['claude-sonnet-4-5 (Anthropic)'],
            tools: ['Visual intent classifier', 'FLUX prompt builder', 'Seed lock registry'],
          }},

      ]},

      /* ── Generation ── */
      { id: 'generation', name: 'Generation', cards: [

        { prompt: 'IndexTTS-2 — en-GB-RyanNeural', agent: 'IndexTTS-2 (voice cloning)',
          meta: {
            description: '<p><strong>Synthesises the full documentary narration with IndexTTS-2 — a local zero-shot voice-cloning model (bilibili), run in its own venv behind a subprocess worker.</strong></p><ul><li>Voice id <strong>en-GB-RyanNeural</strong> keeps its historical spelling but is now an opaque identifier: <code>tts_service._voice_seed_for()</code> maps it to a gender-matched, deterministic reference WAV from the 16-voice seed pool, so the narrator sounds the same across chunks and across runs</li><li>Emotion is inferred from the narration text itself (<code>use_emo_text</code>) — no markup of any kind is added to the script</li><li>Pacing is structural: sentences are synthesised separately and reassembled with programmatic silence (420 ms normal, 520 ms after ? or !, 800 ms at a paragraph break), then loudness-normalised to −16 LUFS</li><li>~19.7 GB VRAM, ~0.83× realtime; Chatterbox takes over automatically on failure or when free VRAM is below the ~21 GB gate</li><li>Output: per-scene MP3 audio files</li><li>Subtitle timing is recovered downstream by Whisper alignment (script-aligned word timestamps; faster-whisper large-v3 segments as fallback) — the cloner emits no word timings</li></ul>',
            llms:  ['IndexTTS-2 (bilibili, local voice cloning)', 'Chatterbox (Resemble AI, MIT) — fallback'],
            tools: ['tts_service (IndexTTS-2 subprocess worker)', 'voice seed pool (_voice_seed_for)', 'Whisper subtitle alignment (downstream)'],
          }},

        { prompt: 'FLUX.1-schnell Image Generation', agent: 'FLUX.1-schnell + LoRA',
          meta: {
            description: '<p><strong>Generates one cinematic keyframe image per scene using FLUX.1-schnell with a style LoRA.</strong></p><ul><li>Model: FLUX.1-schnell (Black Forest Labs, local)</li><li>Documentary-cinematic LoRA loaded at checkpoint-6000, scale 0.75</li><li>Seed locking — identity-tagged scenes reuse first-assigned seed for character consistency across scenes</li><li>Up to 2 retries at 28 steps + guidance 3.5 if anatomy QA score &lt; 0.65</li><li>FLUX fully unloaded from VRAM after this stage</li></ul>',
            llms:  ['FLUX.1-schnell (Black Forest Labs, local)'],
            tools: ['FluxPipeline (diffusers)', 'LoRA weight loader (checkpoint-6000, scale 0.75)', 'CUDA VRAM manager (_gpu_lock)'],
          }},

        { prompt: 'MediaPipe Anatomy QA', agent: 'MediaPipe Holistic',
          meta: {
            description: '<p><strong>Scores each keyframe for anatomy correctness — currently INERT in the production venv.</strong></p><ul><li>Calls the legacy mp.solutions.holistic API, which no longer exists in mediapipe 0.10.35 (Tasks-only) — the blanket exception handler returns a perfect 1.00 for every image</li><li>Score &lt; 0.65 would flag a frame for the repair pass, but no frame ever scores below it, so repairs never trigger from this scorer</li><li>Working hand QC (MediaPipe Tasks hand_landmarker, fail-closed) lives in anatomy_qc / hand_qc_service — this stage awaits the same port</li></ul>',
            llms:  ['—'],
            tools: ['mp.solutions.holistic (legacy — absent from mediapipe 0.10.35)', 'QA score calculator (returns 1.00 in effect)', 'flux_fill_service.repair_batch (qa_threshold 0.65, never triggered here)'],
          }},

        { prompt: 'ControlNet OpenPose (optional)', agent: 'XLabs flux-controlnet-openpose',
          meta: {
            description: '<p><strong>Injects pose skeleton conditioning into FLUX to enforce correct anatomy on character scenes.</strong></p><ul><li>Only active when ControlNet weights are cached at <code>models/flux-controlnet-openpose/</code></li><li>Extracts OpenPose skeleton from reference or first-generated image</li><li>Injects skeleton as FLUX conditioning — character pose locked across scenes</li><li>Skipped automatically if weights are missing — graceful degradation</li></ul>',
            llms:  ['—'],
            tools: ['XLabs flux-controlnet-openpose weights', 'OpenPose skeleton extractor', 'FluxControlNetPipeline (diffusers)'],
          }},

        { prompt: 'IPAdapter Face Consistency (optional)', agent: 'XLabs flux-ip-adapter',
          meta: {
            description: '<p><strong>Injects a reference face into FLUX cross-attention so the same face appears across all character scenes.</strong></p><ul><li>Hard-disabled in the pipeline (<code>_ipa_ready = False</code> — no HuggingFace connectivity): never active, even when weights are cached</li><li>Uses first-generated character image as face reference</li><li>Face embedding injected into every subsequent scene prompt via cross-attention</li><li>Skipped automatically if weights are missing</li></ul>',
            llms:  ['—'],
            tools: ['XLabs flux-ip-adapter weights', 'Face encoder (CLIP ViT-H)', 'IPAdapterFluxPipeline (diffusers)'],
          }},

        { prompt: 'WAN2.1-I2V Video Generation', agent: 'WAN2.1-I2V-14B-480P',
          meta: {
            description: '<p><strong>Animates each keyframe into a short motion clip using WAN2.1 Image-to-Video.</strong></p><ul><li>Model: Wan2_1-I2V-14B-480P fp8 via the resident ComfyUI server (diffusers path is the fallback when ComfyUI is down)</li><li>Each clip starts from its keyframe still — characters, lighting, and composition exactly match</li><li>65 frames @ 17fps ≈ 3.8s per clip — 20 inference steps (30 for close-ups)</li><li>Adaptive flow_shift by shot type: 2.0 close-up / 2.5 medium / 3.5 wide — tighter shots get steadier motion</li><li>Clip looped with ffmpeg to match TTS narration duration</li></ul>',
            llms:  ['WAN2.1-I2V-14B-480P (local, fp8)'],
            tools: ['wan_video_service.py', 'ComfyUI wan_i2v graph (primary)', 'WanImageToVideoPipeline (diffusers fallback)', 'ffmpeg stream_loop', 'CUDA VRAM manager'],
          }},

      ]},

      /* ── QA & Repair ── */
      { id: 'quality', name: 'QA & Repair', cards: [

        { prompt: 'MediaPipe Anatomy Mask', agent: 'MediaPipe Holistic',
          meta: {
            description: '<p><strong>Re-scans post-generation images and generates inpainting masks for any remaining anatomy defects.</strong></p><ul><li>Runs after the still generation + retry loop — catches defects that survive retries</li><li>Generates pixel-level masks around detected defect regions (hands, fingers, joints)</li><li>Mask feeds the repair ladder: Qwen-Image-2512 InstantX inpaint (Tier 1, Apache-2.0) → FLUX Fill (only if the Qwen stack is missing AND FLUX renders are unpaused) → OpenCV TELEA (last resort)</li><li>Caveat: mask building still calls legacy mp.solutions.holistic, absent from the production mediapipe 0.10.35 — mask generation fails and the repair pass is skipped</li></ul>',
            llms:  ['—'],
            tools: ['MediaPipe Holistic (legacy — absent from mediapipe 0.10.35)', 'Mask generator (defect region extractor)'],
          }},

        { prompt: 'OpenCV TELEA Inpainting', agent: 'OpenCV TELEA (last resort)',
          meta: {
            description: '<p><strong>Fast CPU inpainting — fills anatomy defect regions using the TELEA algorithm.</strong></p><ul><li>Always available (pure CPU, no VRAM)</li><li>Uses MediaPipe-generated mask to isolate defect region</li><li>TELEA fills the region using surrounding pixel context</li><li>Suitable for smaller defects — fast, deterministic result</li><li>Last-resort tier since 2026-08-09 — runs only when the Qwen InstantX inpaint tier and FLUX Fill are unavailable or failed</li></ul>',
            llms:  ['—'],
            tools: ['OpenCV cv2.inpaint (INPAINT_TELEA)', 'Defect mask consumer'],
          }},

        { prompt: 'Diffusion Inpaint (Qwen InstantX)', agent: 'Qwen InstantX inpaint (FLUX Fill paused)',
          meta: {
            description: '<p><strong>Diffusion inpainting with FLUX Fill — currently PAUSED (BFL Non-Commercial licence, monetised channel).</strong></p><ul><li>Since 2026-08-09 the Tier 1 repair engine is Qwen-Image-2512 + InstantX inpaint ControlNet (Apache-2.0) via ComfyUI</li><li>FLUX Fill runs only when the Qwen inpaint stack is unavailable AND ZYG_FLUX_RENDERS=allowed — with Qwen models on disk and the pause active, this tier is dead code</li><li>Also requires ≥20GB free VRAM and cached flux-fill weights</li><li>Repaired images synced back into scene_images before WAN I2V loads</li></ul>',
            llms:  ['Qwen-Image-2512 + InstantX inpaint (Apache-2.0) — live Tier 1', 'FLUX Fill (Black Forest Labs, NC — paused)'],
            tools: ['flux_fill_service.py', 'Qwen InstantX inpaint via ComfyUI (Tier 1)', 'FluxFillPipeline (diffusers, pause-gated)', 'licence_provenance flux pause gate', 'CUDA VRAM manager (≥20GB gate)'],
          }},

        { prompt: 'YOLOv8 Object Tracking', agent: 'YOLOv8 (ultralytics)',
          meta: {
            description: '<p><strong>Detects and restores props/objects that disappear mid-clip due to WAN temporal attention drift.</strong></p><ul><li>Runs YOLOv8 in tracking mode on every WAN video clip</li><li>Detects frame-by-frame disappearance of tracked objects (weapons, tools, props)</li><li>On disappearance: composites the object back from the source still or best reference frame — cv2 seamlessClone, alpha-blend (0.75) fallback near borders</li><li>Rebuilds the corrected clip with ffmpeg after compositing</li></ul>',
            llms:  ['—'],
            tools: ['object_track_service.py', 'YOLOv8 (ultralytics, ByteTrack tracking)', 'OpenCV seamlessClone + alpha-blend compositor', 'ffmpeg clip rebuilder'],
          }},

        { prompt: 'RIFE ncnn-Vulkan Frame Interpolation', agent: 'rife-ncnn-vulkan (Tier 1)',
          meta: {
            description: '<p><strong>Neural 2× frame interpolation to smooth temporal artefacts in WAN clips — Vulkan compute, zero CUDA VRAM.</strong></p><ul><li>Inserts 1 AI-generated frame between each pair → 2× temporal resolution, no motion ghosting</li><li>Model: RIFE v4.6 (rife-v4.6 weights)</li><li>Uses Vulkan compute — runs on GPU without consuming PyTorch VRAM</li><li>Binary: <code>~/.local/bin/rife-ncnn-vulkan</code></li><li>Runs after YOLOv8 Object Tracking, before final assembly</li></ul>',
            llms:  ['—'],
            tools: ['rife_service.py', 'rife-ncnn-vulkan binary (Vulkan)', 'rife-v4.6 model weights', 'ffmpeg frame extractor + re-encoder'],
          }},

        { prompt: 'ffmpeg minterpolate', agent: 'ffmpeg minterpolate (Tier 2)',
          meta: {
            description: '<p><strong>CPU motion-compensated frame blending — fallback when rife-ncnn-vulkan binary is unavailable.</strong></p><ul><li>Short clips (&lt;200 frames): blend mode for subtle smoothing</li><li>Long clips (≥200 frames): 2× motion-compensated interpolation</li><li>Reduces flickering and ghosting in WAN temporal output</li><li>Runs only when Tier 1 RIFE binary is not found</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg minterpolate filter (mi_mode=mci)', 'ffmpeg frame extractor'],
          }},

      ]},

      /* ── Assets ── */
      { id: 'assets', name: 'Assets', cards: [

        { prompt: 'Smart Clip Scoring + Trim', agent: 'Clip Processor',
          meta: {
            description: '<p><strong>Scores, selects, and trims stock footage clips to match each scene\'s visual intent.</strong></p><ul><li>Scores each candidate clip against the scene visual intent tag</li><li>Selects highest-scoring clip per scene</li><li>Trims to required duration and rate-adjusts if needed</li><li>Output: ready-to-assemble, time-matched clip set</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg', 'Scene-fit scorer', 'Clip trim engine', 'Rate adjuster'],
          }},

      ]},

      /* ── Assembly ── */
      { id: 'assembly', name: 'Assembly', cards: [

        { prompt: 'ffmpeg lut3d Color Grade', agent: 'ffmpeg lut3d + unsharp',
          meta: {
            description: '<p><strong>Applies a cinematic .cube LUT + sharpening to every clip before final concat.</strong></p><ul><li>LUT selected per visual_style: cinematic / orange_teal / documentary / anime / filmic</li><li>Each LUT is a 33×33×33 3D color lookup table generated mathematically — no DaVinci required</li><li>Followed by <code>unsharp=5:5:0.5:3:3:0.15</code> for fine-detail recovery</li><li>CPU-only, ~1–3s per clip — fallback: pass-through if LUT file missing</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg lut3d filter', 'ffmpeg unsharp filter', 'assets/luts/*.cube (5 grades)', 'generate_luts.py'],
          }},

        { prompt: 'Ken Burns Animation', agent: 'ffmpeg zoompan',
          meta: {
            description: '<p><strong>Animates every still image with cinematic Ken Burns motion.</strong></p><ul><li>Motion types: push_in (close-up/tight), pull_out (medium, every 3rd), pan_r/pan_l (wide/establishing, alternating), drift (overhead/drone)</li><li>Zoom rate scaled by Murch emotion speed multiplier: grief=0.55×, calm=0.70×, mystery=0.80×, awe=1.0×, tension=1.4×, shock=1.5×</li><li>Focal zone locks push/pull anchor to subject position: center=0.50, left=0.25, right=0.75, top=0.20, bottom=0.80</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg zoompan filter', 'Focal zone anchor calculator', 'Emotion speed multiplier table'],
          }},

        { prompt: 'Murch Engine — Transition Graph', agent: 'Murch Engine xfade',
          meta: {
            description: '<p><strong>Builds the ffmpeg xfade filter graph from the 31-entry emotion table and 17 shot-tightness override rules.</strong></p><ul><li>Emotion table: grief→fade, calm→fade, mystery→dissolve, awe→wipeleft, tension→cut, shock→cut, triumph→wiperight, unease→smoothleft</li><li>Shot-tightness overrides: close→wide = pull-back dissolve, wide→close = push-in dissolve, overhead→any = fadeblack (17 rules)</li><li>Hard-cut guard: shock/tension always hard-cut regardless of emotion table</li><li>Transition duration: 0.3–0.8s based on emotion intensity</li></ul>',
            llms:  ['—'],
            tools: ['murch_engine.py (build_xfade_filter_graph)', 'ffmpeg xfade filter (31 entries + 17 overrides)'],
          }},

        { prompt: 'ffmpeg concat — Final Assembly', agent: 'ffmpeg concat demuxer',
          meta: {
            description: '<p><strong>Concatenates all graded, animated, and transitioned scene clips into the master output video.</strong></p><ul><li>Uses ffmpeg concat demuxer to join clips in script order</li><li>Each clip already contains its TTS narration audio</li><li>Copies both streams without re-encoding for maximum speed</li><li>Output: master MP4 saved to pipeline output directory</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg concat demuxer', 'ffmpeg audio stream copy', 'ffmpeg video stream copy'],
          }},

        { prompt: 'Book Intro Title Card', agent: 'Claude + ffmpeg drawtext',
          meta: {
            description: '<p><strong>Renders a cinematic title card with ffmpeg drawtext — no LLM writes the copy.</strong></p><ul><li>Title and description come from pipeline state (essay title / topic); the ending card uses operator-supplied ending_text</li><li>Renders animated title text with fade-in using ffmpeg drawtext</li><li>Book-intro prepend is currently disabled in the scholarly pipeline; the ending card is appended with ffmpeg concat</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg drawtext filter', 'ffmpeg fade filter', 'ffmpeg concat'],
          }},

        { prompt: 'ffmpeg Subtitle Burn-In', agent: 'ffmpeg subtitles filter',
          meta: {
            description: '<p><strong>Generates sentence-level subtitles for the final video.</strong></p><ul><li>Timing from Whisper: script-aligned word timestamps when narration text is available, else faster-whisper large-v3 + VAD segments (shared zyg_whisper loader)</li><li>Subtitle cards wrapped at 42 chars / max 2 lines with an 83 ms cinema lead-in</li><li>SRT saved beside the video and delivered to YouTube as a caption track — video copied clean, no burn-in</li></ul>',
            llms:  ['—'],
            tools: ['zyg_whisper (faster-whisper large-v3 + VAD)', 'murch_engine Whisper word alignment', 'SRT writer (YouTube caption mode)'],
          }},

        { prompt: 'ACE-Step Background Music', agent: 'ACE-Step 1.5 turbo (MIT)',
          meta: {
            description: '<p><strong>Tier 1 — AI-generates a unique background music track (default 60s) matched to the dominant scene emotion.</strong></p><ul><li>Model: ACE-Step 1.5 turbo AIO (MIT weights — replaced CC-BY-NC MusicGen 2026-08-09), via ComfyUI native nodes</li><li>Prompt derived from dominant emotion: battle / triumphant / epic / mysterious / sad / peaceful / dark / adventure</li><li>Unique instrumental track every run — MIT-licensed weights, commercially clean</li><li>Mixed at 12% volume with 2s fade-in and 3s fade-out under narration</li><li>ComfyUI evicts the checkpoint from VRAM after each job</li></ul>',
            llms:  ['ACE-Step 1.5 turbo (ACE Studio, local, MIT)'],
            tools: ['ace_step_service.py', 'ComfyUI native ACE-Step 1.5 nodes', 'ffmpeg amix + afade'],
          }},

        { prompt: 'yt-dlp Music Fallback', agent: 'yt-dlp (Tier 2)',
          meta: {
            description: '<p><strong>Tier 2 — Downloads a royalty-free YouTube track when ACE-Step is unavailable.</strong></p><ul><li>Searches YouTube for royalty-free tracks matching the dominant emotion keyword</li><li>Downloads ~128kbps MP3 using yt-dlp</li><li>Mixed at 12% volume under narration — same amix chain as Tier 1</li><li>Activated only when ACE-Step fails or GPU VRAM is insufficient</li></ul>',
            llms:  ['—'],
            tools: ['yt-dlp (YouTube downloader)', 'audio_service.py', 'ffmpeg amix + afade'],
          }},

      ]},

    ],
  }, // end documentary

  /* ══════════════════════════════════════════════════════════════════════════
     VIDEO PIPELINE
  ══════════════════════════════════════════════════════════════════════════ */
  video: {
    name: 'Video',
    label: '[ VIDEO PIPELINE ]',
    columns: [

      /* ── Planning ── */
      { id: 'planning', name: 'Planning', cards: [

        { prompt: 'Scene Planning', agent: 'Claude claude-sonnet-4-6',
          meta: {
            description: '<p><strong>Translates the user directive into a scene-by-scene production plan.</strong></p><ul><li>Calls Claude claude-sonnet-4-6 with the user directive</li><li>Returns a JSON array of scene objects, each with visual description and narration text</li><li>Output drives all downstream generation stages</li></ul>',
            llms:  ['claude-sonnet-4-6 (Anthropic)'],
            tools: ['Anthropic Messages API', 'JSON scene parser'],
          }},

      ]},

      /* ── Visuals ── */
      { id: 'visuals', name: 'Visuals', cards: [

        { prompt: 'Qwen-2512 Image Generation', agent: 'Qwen-Image-2512 (ComfyUI)',
          meta: {
            description: '<p><strong>Generates one cinematic keyframe image per scene using Qwen-Image-2512 via the resident ComfyUI server.</strong></p><ul><li>Model: Qwen-Image-2512 (Apache-2.0, local via ComfyUI) — default video-still family since 2026-08-09 (ZYG_VIDEO_STILL_FAMILY=qwen)</li><li>Attempt tiers: steps 20 / cfg 2.5, then steps 28 / cfg 3.0 — QA retries disabled, first successful render kept; seed randomised per attempt</li><li>FLUX.1-dev tiers are licence-paused; diffusers FLUX.1-schnell loads only when ComfyUI is unavailable (ZYG_FORCE_FLUX_LOCAL=1 to force) — the documentary-cinematic style LoRA applies only on that diffusers leg</li></ul>',
            llms:  ['Qwen-Image-2512 (Apache-2.0, local via ComfyUI)'],
            tools: ['video_flux_still_service.py', 'comfy_generation_service.generate_still (ComfyUI :8188)', 'FluxPipeline (diffusers — fallback only)'],
          }},

        { prompt: 'MediaPipe Anatomy QA', agent: 'MediaPipe Holistic',
          meta: {
            description: '<p><strong>Anatomy scorer — currently INERT in the live venv (every image scores 1.00).</strong></p><ul><li>Code calls the legacy mp.solutions.holistic API, which no longer exists in mediapipe 0.10.35 (Tasks-only)</li><li>The blanket except returns a perfect score, so the 0.65 retry / inpaint trigger never fires from this stage</li><li>Needs a port to the MediaPipe Tasks API (hand_landmarker / face_landmarker) as used by anatomy_qc.py</li></ul>',
            llms:  ['—'],
            tools: ['MediaPipe Holistic (pose + hand + face landmarks)', 'QA score calculator', 'Retry dispatcher'],
          }},

        { prompt: 'ControlNet OpenPose (optional)', agent: 'InstantX FLUX.1-dev-Controlnet-Union',
          meta: {
            description: '<p><strong>Injects pose skeleton conditioning into the diffusers FLUX fallback path for correct anatomy on character scenes.</strong></p><ul><li>Model: InstantX FLUX.1-dev-Controlnet-Union (~6.6 GB, HF cache), union mode 4 = OpenPose</li><li>Extracts OpenPose skeleton from reference or first-generated image</li><li>Only reached when ComfyUI is unavailable (or ZYG_FORCE_FLUX_LOCAL=1) — the primary Qwen-2512 still path skips it</li><li>Gracefully skipped if weights are missing</li></ul>',
            llms:  ['—'],
            tools: ['InstantX FLUX.1-dev-Controlnet-Union weights (HF cache)', 'OpenPose skeleton extractor', 'FluxControlNetPipeline (diffusers)'],
          }},

        { prompt: 'IPAdapter Face Consistency (optional)', agent: 'XLabs flux-ip-adapter',
          meta: {
            description: '<p><strong>Currently DISABLED in code — IPAdapter setup is hard-skipped in Stage 2.</strong></p><ul><li>pipeline_video sets IPAdapter ready = False (no HuggingFace connectivity) — cached weights are never loaded</li><li>Applies only to the diffusers FLUX fallback path, which the primary ComfyUI/Qwen-2512 still path bypasses anyway</li><li>Face consistency is carried by character LoRAs on the ComfyUI path</li></ul>',
            llms:  ['—'],
            tools: ['XLabs flux-ip-adapter weights', 'Face encoder (CLIP ViT-H)', 'IPAdapterFluxPipeline (diffusers)'],
          }},

      ]},

      /* ── Audio ── */
      { id: 'audio', name: 'Audio', cards: [

        { prompt: 'IndexTTS-2 — en-GB-RyanNeural', agent: 'IndexTTS-2 (primary)',
          meta: {
            description: '<p><strong>Primary TTS — per-scene narration via IndexTTS-2, a local zero-shot voice cloner.</strong></p><ul><li>Voice id en-GB-RyanNeural is an opaque identifier — <code>_voice_seed_for()</code> resolves it to a fixed, gender-matched reference WAV from the 16-voice seed pool</li><li>Emotion inferred from the scene narration text (<code>use_emo_text</code>); sentence pauses inserted programmatically (420 / 520 / 800 ms) and the assembly normalised to −16 LUFS</li><li>Runs first for every scene; Chatterbox only fills gaps</li><li>Output: one MP3 per scene under <code>tts/tts_NNNN.mp3</code></li></ul>',
            llms:  ['IndexTTS-2 (bilibili, local voice cloning)'],
            tools: ['tts_service', 'IndexTTS-2 subprocess worker (own venv)', 'ffmpeg concat (multi-chunk)'],
          }},

        { prompt: 'Chatterbox — seed-pool voice', agent: 'Chatterbox (fallback)',
          meta: {
            description: '<p><strong>Fallback TTS — Chatterbox (Resemble AI, local, MIT).</strong></p><ul><li>Only for scenes IndexTTS-2 failed to synthesise, or when free VRAM is below the ~21 GB gate (Chatterbox needs ~4.1 GB)</li><li>Clones the same seed-pool reference WAV, so the voice does not change mid-episode</li><li>Output carries an inaudible Resemble Perth watermark, surfaced in the worker JSON for provenance</li><li>Logged as <code>chatterbox-fallback</code></li></ul>',
            llms:  ['Chatterbox (Resemble AI, MIT)'],
            tools: ['Chatterbox subprocess worker (own venv)', 'ffmpeg concat', 'SRT proportional timer'],
          }},

        { prompt: 'soundbible.com Foley Downloader', agent: 'audio_service.py',
          meta: {
            description: '<p><strong>Finds and downloads diegetic foley sound effects matching scene keywords.</strong></p><ul><li>Analyses each scene description for sonic keywords (sword, crowd, thunder, wind, gunshot, etc.)</li><li>Downloads matching CC0 samples from soundbible.com — cached locally after first use</li><li>Validates downloaded audio with ffprobe before use</li></ul>',
            llms:  ['—'],
            tools: ['audio_service.py', 'soundbible.com CC0 library (curl download)', 'ffprobe audio validator', 'Keyword→SFX mapper'],
          }},

        { prompt: 'ffmpeg amix — Foley Mixer', agent: 'ffmpeg amix',
          meta: {
            description: '<p><strong>Blends foley SFX into each scene\'s TTS narration audio before clip mux.</strong></p><ul><li>Ambient sounds (wind, ocean, rain, birds) mixed at 20% volume</li><li>Impact sounds (sword, explosion, gunshot) mixed at 30% volume</li><li>Foley trimmed / looped to match TTS duration with ffmpeg aloop + atrim</li><li>Runs per-scene before WAN clip is muxed</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg amix filter', 'ffmpeg aloop + atrim', 'ffmpeg audio stream muxer'],
          }},

      ]},

      /* ── Video ── */
      { id: 'video', name: 'Video', cards: [

        { prompt: 'WAN2.1-I2V Video Generation', agent: 'WAN2.1-I2V-14B-480P',
          meta: {
            description: '<p><strong>Animates each anchor keyframe into a short motion clip using WAN2.1 Image-to-Video.</strong></p><ul><li>Model: WAN2.1-I2V-14B-480P (~28GB VRAM), submitted to the resident ComfyUI server</li><li>Each clip anchored to its scene still (Qwen-2512 by default) — characters, lighting, composition exactly match</li><li>65 frames @ 17fps ≈ 3.8s per sub-clip (20 steps; close-ups 30) — sub-clips chained per scene with anti-drift anchor resets</li><li>Per-shot flow_shift: 2.0 close-up / 2.5 medium / 3.5 wide; near-static clips retry at 5.0</li></ul>',
            llms:  ['WAN2.1-I2V-14B-480P (local, ~28GB VRAM)'],
            tools: ['wan_video_service.py', 'ComfyUI WanVideoWrapper (wan_i2v graph, sdpa attention)', 'WanImageToVideoPipeline (diffusers — fallback)', 'CUDA VRAM manager'],
          }},

        { prompt: 'ffmpeg Stream Loop + SRT Burn-In', agent: 'ffmpeg',
          meta: {
            description: '<p><strong>Loops each WAN clip to match TTS narration duration and burns in sentence-level subtitles.</strong></p><ul><li>ffmpeg stream_loop repeats the WAN clip until it matches the TTS audio length</li><li>Sentence-level SRT subtitles burned in via ffmpeg subtitles filter</li><li>White text, black outline, bottom-aligned with 40px margin</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg stream_loop', 'ffmpeg subtitles filter (SRT burn-in)', 'SRT file writer'],
          }},

        { prompt: 'FLUX img2img Scene Chaining', agent: 'FLUX img2img (continuous mode)',
          meta: {
            description: '<p><strong>Ensures visual continuity — each scene starts from the last frame of the previous WAN clip.</strong></p><ul><li>Active only when scene_mode = "continuous"</li><li>Extracts final frame of previous WAN clip; upscaled to 1360×768 (LANCZOS) before img2img</li><li>FLUX img2img regenerates at strength 0.35 (4 steps, guidance 0.0) — preserves character and environment while adapting to new scene prompt</li><li>Chained frame upscaled 4× (LANCZOS) as the WAN I2V starting frame for the next scene</li></ul>',
            llms:  ['FLUX.1-schnell (img2img mode, strength 0.35)'],
            tools: ['FluxImg2ImgPipeline (diffusers)', 'PIL LANCZOS 4× upscale', 'ffmpeg last-frame extractor', 'CUDA VRAM manager'],
          }},

      ]},

      /* ── QA & Repair ── */
      { id: 'quality', name: 'QA & Repair', cards: [

        { prompt: 'MediaPipe Anatomy Mask', agent: 'MediaPipe Holistic',
          meta: {
            description: '<p><strong>Generates pixel-level masks around anatomy defects — currently INERT in the live venv.</strong></p><ul><li>Mask builder calls the legacy mp.solutions.holistic API, absent from mediapipe 0.10.35 — mask generation fails and repair is skipped</li><li>Upstream anatomy QA scores every frame 1.00 for the same reason, so no candidates reach repair</li><li>Needs a port to the MediaPipe Tasks API (hand_landmarker), as used by anatomy_qc.py</li></ul>',
            llms:  ['—'],
            tools: ['MediaPipe Holistic (landmark detector)', 'Defect mask generator'],
          }},

        { prompt: 'OpenCV TELEA Inpainting', agent: 'OpenCV TELEA (last resort)',
          meta: {
            description: '<p><strong>Fast CPU inpainting using the TELEA algorithm — last-resort anatomy repair.</strong></p><ul><li>Always available — pure CPU, no VRAM</li><li>Uses the repair mask to isolate and fill the defect region</li><li>Runs only when the Qwen InstantX inpaint tier (and licence-paused FLUX Fill) are unavailable</li></ul>',
            llms:  ['—'],
            tools: ['OpenCV cv2.inpaint (INPAINT_TELEA)'],
          }},

        { prompt: 'Diffusion Inpaint (Qwen InstantX)', agent: 'Qwen InstantX inpaint (FLUX Fill paused)',
          meta: {
            description: '<p><strong>Diffusion inpainting — Tier 1 is now Qwen-Image-2512 + InstantX inpaint ControlNet (both Apache-2.0) via ComfyUI.</strong></p><ul><li>Qwen inpaint (hand_fixer_qwen_inpaint graph) runs first whenever ComfyUI is reachable and its two model files are on disk</li><li>FLUX Fill (BFL Non-Commercial) is licence-paused since 2026-08-09 — reachable only if the Qwen stack is missing AND ZYG_FLUX_RENDERS=allowed</li><li>Repaired images synced back into scene_images before WAN I2V</li></ul>',
            llms:  ['Qwen-Image-2512 + InstantX inpaint ControlNet (Apache-2.0)', 'FLUX Fill (BFL NC — paused)'],
            tools: ['flux_fill_service.py', 'ComfyUI hand_fixer_qwen_inpaint workflow', 'FluxFillPipeline (diffusers — paused)'],
          }},

        { prompt: 'YOLOv8 Object Tracking', agent: 'YOLOv8 (ultralytics)',
          meta: {
            description: '<p><strong>Restores props/objects that disappear mid-clip due to WAN temporal attention drift.</strong></p><ul><li>Tracks objects frame-by-frame (ByteTrack mode)</li><li>On disappearance: seamlessClone composite from the source still (Qwen-2512 by default), alpha 0.75 blend fallback near frame borders</li><li>Rebuilt clip written back with ffmpeg</li></ul>',
            llms:  ['—'],
            tools: ['object_track_service.py', 'YOLOv8 (ultralytics, ByteTrack)', 'OpenCV seamlessClone (alpha-blend fallback)', 'ffmpeg clip rebuilder'],
          }},

        { prompt: 'RIFE ncnn-Vulkan Interpolation', agent: 'rife-ncnn-vulkan (Tier 1)',
          meta: {
            description: '<p><strong>Neural 2× frame interpolation — eliminates WAN temporal stuttering using Vulkan compute.</strong></p><ul><li>Inserts 1 generated frame between each pair → 2× temporal resolution</li><li>RIFE v4.6 model; Vulkan compute — no PyTorch VRAM consumed</li><li>Binary: <code>~/.local/bin/rife-ncnn-vulkan</code></li></ul>',
            llms:  ['—'],
            tools: ['rife_service.py', 'rife-ncnn-vulkan binary (Vulkan)', 'rife-v4.6 weights', 'ffmpeg frame extractor + re-encoder'],
          }},

        { prompt: 'ffmpeg minterpolate Fallback', agent: 'ffmpeg minterpolate (Tier 2)',
          meta: {
            description: '<p><strong>CPU motion-compensated blending — fallback when RIFE binary is unavailable.</strong></p><ul><li>Short clips (&lt;200 frames): blend mode; long clips (≥200 frames): 2× interpolation</li><li>Reduces flickering and ghosting in WAN output</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg minterpolate filter (mi_mode=mci)'],
          }},

      ]},

      /* ── Assembly ── */
      { id: 'assembly', name: 'Assembly', cards: [

        { prompt: 'ffmpeg lut3d Color Grade', agent: 'ffmpeg lut3d + unsharp',
          meta: {
            description: '<p><strong>Applies a cinematic .cube LUT + sharpening to every clip before final concat.</strong></p><ul><li>LUT per visual_style: cinematic / orange_teal / documentary / anime / filmic</li><li>33×33×33 3D LUT generated mathematically — no DaVinci required</li><li>unsharp=5:5:0.5:3:3:0.15 recovers fine detail lost in WAN synthesis</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg lut3d filter', 'ffmpeg unsharp filter', 'assets/luts/*.cube (5 grades)'],
          }},

        { prompt: 'ffmpeg concat — Final Assembly', agent: 'ffmpeg concat demuxer',
          meta: {
            description: '<p><strong>Concatenates all scene clips into the master output video.</strong></p><ul><li>Joins clips in script order; each already contains TTS narration + foley SFX</li><li>Stream-copy — no re-encode for maximum speed</li><li>Output: master MP4 to pipeline output directory</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg concat demuxer', 'ffmpeg audio/video stream copy'],
          }},

        { prompt: 'ACE-Step Background Music', agent: 'ACE-Step 1.5 turbo (MIT)',
          meta: {
            description: '<p><strong>Tier 1 — AI-generates a unique background music track matched to dominant scene emotion.</strong></p><ul><li>~60s original music by default (cap 180s via ZYG_ACE_MAX_SECONDS), rendered on the resident ComfyUI server — no licensing</li><li>Dominant emotion → music mood map: battle / triumphant / epic / mysterious / sad / peaceful</li><li>Mixed at 12% volume with 2s fade-in + 3s fade-out under narration</li></ul>',
            llms:  ['ACE-Step 1.5 turbo (ACE Studio, local, MIT)'],
            tools: ['ace_step_service.py', 'ComfyUI native ACE-Step 1.5 nodes', 'ffmpeg amix + afade'],
          }},

        { prompt: 'yt-dlp Music Fallback', agent: 'yt-dlp (Tier 2)',
          meta: {
            description: '<p><strong>Tier 2 — Downloads royalty-free YouTube track when ACE-Step is unavailable.</strong></p><ul><li>Searches and downloads ~128kbps MP3 matched to dominant emotion keyword</li><li>Same 12% amix chain as Tier 1</li></ul>',
            llms:  ['—'],
            tools: ['yt-dlp', 'ffmpeg amix + afade'],
          }},

        { prompt: 'soundbible.com Ambient Fallback', agent: 'soundbible.com CC0 (Tier 3)',
          meta: {
            description: '<p><strong>Tier 3 — CC0 ambient loop from soundbible.com — last resort music fallback.</strong></p><ul><li>Downloads a pre-mapped ambient loop (ocean / rain / wind / forest) matching scene emotion</li><li>Looped to match video length with ffmpeg aloop</li></ul>',
            llms:  ['—'],
            tools: ['soundbible.com CC0 library', 'ffmpeg aloop', 'ffmpeg amix + afade'],
          }},

      ]},

    ],
  }, // end video

  /* ══════════════════════════════════════════════════════════════════════════
     SECOND LEDGER — Wan2.1 + VACE character scene renders (2026-08-01)

     These are the scene20_* renders (Cornelis + Abel). They are driven by a
     standalone script, NOT by the GUI pipeline API, so their live state comes
     from the run logbook on disk via kanban_video_status.py -> the server's
     template key 'second_ledger'.

     EVERY CARD TITLE HERE IS A REAL STAGE NAME THE DRIVER EMITS. The mapping
     lives in kanban_video_status.STAGE_CARDS and the two must stay in step —
     a card whose title has no stage simply never leaves 'queued', which is the
     failure this board replaced. The old 'video' board above describes a
     different pipeline entirely (FLUX keyframe -> WAN2.1-I2V -> ffmpeg loop)
     and never matched a single VACE stage.
  ══════════════════════════════════════════════════════════════════════════ */
  second_ledger: {
    name: 'Second Ledger',
    label: '[ THE SECOND LEDGER — VACE SCENE ]',
    columns: [

      /* ── Setup ── */
      { id: 'setup', name: 'Setup', cards: [

        { prompt: 'Resolve Run Config', agent: 'run_logbook + version assert',
          meta: {
            description: '<p><strong>Resolves the run identity and refuses to start if any output path disagrees with it.</strong></p><ul><li>ONE version constant drives the run dir, all 18 output paths and the ComfyUI upscale prefix</li><li><code>assert_version_paths()</code> blocks a stale filename before anything is created — v12 silently overwrote v11\'s FINAL because the OUT dir changed but the filename constant did not</li><li>Opens the logbook: env snapshot, resolved render kwargs, beat texts + sha12, ref/mask sha256, LoRA strengths, driver sha256</li></ul>',
            llms:  ['—'],
            tools: ['run_logbook.start_run / record_config', 'assert_version_paths()', 'CHECKPOINTS.json'],
          }},

        { prompt: 'Candle Graded Pin', agent: 'wan_vace_service per-region pin',
          meta: {
            description: '<p><strong>Builds the differential-diffusion noise_mask — pinned on the candle only.</strong></p><ul><li>Candle box at level 0.65, neutral 1.00 everywhere else = <strong>3.007% of frame pinned</strong></li><li>v12 pinned 83.16% (the whole character mask): Cornelis\'s face motion collapsed 0.70 → 0.33 and jitter appeared frame-wide</li><li>Measured on v12\'s shipped mask, the candle box was 92.8% below neutral (mean 0.699) — the flicker the operator asked to keep came from a pin at this value, so v13 reproduces it</li><li>Both face halves measure min 1.000 — provably untouched</li></ul>',
            llms:  ['—'],
            tools: ['wan_vace_service.pin_regions_from_meta()', 'build_graded_pin_mask()', 'WanVideoEncode noise_mask'],
          }},

      ]},

      /* ── Preflight ── */
      { id: 'preflight', name: 'Preflight', cards: [

        { prompt: 'Preflight Gates', agent: 'mask + straddle + CLIP semantics',
          meta: {
            description: '<p><strong>Gates the control mask and the anchor BEFORE the 90-minute render is allowed to start.</strong></p><ul><li>Mask gate: white_frac within [0.005, max_white], soft-band and border checks</li><li>Straddle gate: warns when a prop boundary is cut by the mask edge (book / pipe region)</li><li>CLIP semantics: pipe-in-mouth-or-hand, hand-on-pipe</li><li>Silhouette mask closed the pole zone that was hallucinating wall decoration (76.4% → 0.0% open)</li></ul>',
            llms:  ['open_clip (semantic checks)'],
            tools: ['wan_vace_service.preflight_mask_gates()', 'build_char_mask()', 'asset_validate.validate_prop_ref()'],
          }},

      ]},

      /* ── Render ── */
      { id: 'render', name: 'Render', cards: [

        { prompt: 'VACE Render', agent: 'Wan2.1 T2V-14B + VACE',
          meta: {
            description: '<p><strong>The 90-minute sample. One continuous scene, not stitched segments.</strong></p><ul><li>832×480, 341 frames @ 17fps, one seed</li><li>Context windows: 81 frames, overlap 24, stride 4, fuse=pyramid, FreeNoise — this is what removed the visible scene skip</li><li>Four scheduled beats mapped [0,1,2,2,3,3] across six windows, zero dead beats</li><li>Per-beat prompt clipping at 1500 chars (the old flat 4000-char cap silently truncated tails)</li></ul>',
            llms:  ['Wan2.1 T2V-14B + VACE module (local)'],
            tools: ['ComfyUI-WanVideoWrapper', 'WanVideoContextOptions', 'generate_vace_static_clip()', 'character LoRAs'],
          }},

      ]},

      /* ── FX ── */
      { id: 'fx', name: 'FX Composite', cards: [

        { prompt: 'Ink Write-On Quad', agent: 'ink_fx v3 + SAM2 matte',
          meta: {
            description: '<p><strong>Writes the ledger text ONTO the page plane, not onto the screen.</strong></p><ul><li>Perspective quad tracked to the open page; SAM2 occlusion matte keeps the hand in front of the ink</li><li>Auto-blur + per-frame alpha grain so the ink sits in the plate rather than floating over it</li><li>Measured: sharpness 3.99 → 1.02, matte violation 0.41 → 0.0009</li></ul>',
            llms:  ['—'],
            tools: ['ink_fx.composite_write_on_quad()', 'SAM2 segmentation', 'PIL perspective transform'],
          }},

        { prompt: 'Pipe Smoke (2-layer)', agent: 'smoke_fx v2',
          meta: {
            description: '<p><strong>Two-layer smoke keyed to the pipe draws.</strong></p><ul><li>Bowl and mouth pins from shot metadata; draw times drive density</li><li>Fixed a hard alpha clamp that produced a 12.18× white flash at 19.47s, and an <code>int(t*2.0)</code> staircase in the ramp — excess now 2.08×</li></ul>',
            llms:  ['—'],
            tools: ['smoke_fx.composite_pipe_smoke_v2()', 'ffmpeg'],
          }},

      ]},

      /* ── QA ── */
      { id: 'qa', name: 'QA', cards: [

        { prompt: 'VLM Inspection', agent: 'Qwen3-VL-8B-Instruct-FP8',
          meta: {
            description: '<p><strong>Local vision judge on region CROPS — reject-only, never overrides a pixel gate.</strong></p><ul><li>THE CROP RULE: pipe-grip defects scored 5/5 on region crops and 0/2 on the full frame</li><li>FP8 at ~10.2GB stays resident beside a render; self-refuses while ComfyUI is sampling</li><li>Checklist items phrased positively (negated questions measured wrong 4/4)</li><li>Blind to ink defects — that half belongs to the pixel gates</li></ul>',
            llms:  ['Qwen3-VL-8B-Instruct-FP8 (local, Apache-2.0)'],
            tools: ['vlm_inspector.py', 'config/vlm_checklists.json', 'comfy_offload.py'],
          }},

        { prompt: 'QC Gates', agent: 'pipeline_debug gate suite',
          meta: {
            description: '<p><strong>Every gate that can catch a defect without the operator having to watch the clip.</strong></p><ul><li><strong>Character balance</strong> — cross-character face-flow ratio; fails v11\'s 2.24 asymmetry, passes v6\'s 1.68 (statistic is the MEDIAN; on the mean the gate is impossible)</li><li><strong>Regression vs baseline</strong> — every metric signed against the named parent run; only regression-direction moves fail</li><li>Region flow floors, motion quality/balance, prop geometry triad, frame border, FX grain</li></ul>',
            llms:  ['—'],
            tools: ['qc_character_balance()', 'qc_regression_vs()', 'qc_region_flow()', 'qc_prop_geometry()', 'MTCNN face boxes'],
          }},

      ]},

      /* ── Finish ── */
      { id: 'finish', name: 'Finish', cards: [

        { prompt: 'Upscale + Interpolate', agent: 'RealESRGAN ×2 + RIFE',
          meta: {
            description: '<p><strong>Resolution and frame-rate finish.</strong></p><ul><li>RealESRGAN ×2 per frame through ComfyUI</li><li>RIFE interpolation 17fps → 24fps</li><li>Re-encoded at CRF 16</li></ul>',
            llms:  ['—'],
            tools: ['RealESRGAN_x2.pth', 'RIFE ncnn-Vulkan', 'ffmpeg libx264'],
          }},

        { prompt: 'Ambience + Audio Mix', agent: 'audio_mix + licensed bed',
          meta: {
            description: '<p><strong>Maritime ambience audible throughout, clearer in the pauses.</strong></p><ul><li>Licence-gated CC0 bed only (commercial publication: Apache-2.0 / MIT / BSD / CC0)</li><li>Sidechain duck with a slow release so the bed lifts back in Abel\'s pauses rather than cutting</li><li>Bed at −32 LUFS, master −14 LUFS; duck recalibrated to threshold 0.06 / ratio 3</li><li>Narration currently OFF at the operator\'s request</li></ul>',
            llms:  ['IndexTTS-2 (narration — currently disabled)'],
            tools: ['audio_mix.duck_mix()', 'ffmpeg loudnorm (two-pass)', 'CC0 ambience library'],
          }},

        { prompt: 'Report + Logbook', agent: 'run_logbook + run_ledger',
          meta: {
            description: '<p><strong>Writes the record that makes the next run diagnosable.</strong></p><ul><li>result.json + LOGBOOK.md + CHECKPOINTS.json (atomic, .bak retained, resumable)</li><li><code>compare_runs A B</code> prints the config delta beside the metric delta — this is what surfaced <code>ZYG_VACE_DIFFDIFF 0→1</code> next to <code>face_alive.cornelis 0.70 → 0.33</code></li><li>Gate verdicts mirrored into run_ledger.sqlite3 for trend z-scores</li></ul>',
            llms:  ['—'],
            tools: ['run_logbook.finish_run / compare_runs', 'run_ledger.compare_gates()', 'pipeline_debug report.html'],
          }},

      ]},

    ],
  }, // end second_ledger

  /* ══════════════════════════════════════════════════════════════════════════
     MANGA PIPELINE — FLUX panels + Ken Burns, no WAN
  ══════════════════════════════════════════════════════════════════════════ */
  manga: {
    name: 'Manga',
    label: '[ MANGA PIPELINE ]',
    columns: [
      { id: 'planning', name: 'Planning', cards: [
        { prompt: 'Scene Planning', agent: 'Claude claude-sonnet-4-6',
          meta: {
            description: '<p><strong>Plans panel-by-panel manga/comic sequence from the user directive.</strong></p><ul><li>Ink linework, screentone, illustrated panels — not photographic</li><li>Per-panel flux_prompt + optional narration</li><li>No WAN animation prompts</li></ul>',
            llms:  ['claude-sonnet-4-6 (Anthropic)'],
            tools: ['Anthropic Messages API', 'JSON scene parser'],
          }},
      ]},
      { id: 'visuals', name: 'Visuals', cards: [
        { prompt: 'Qwen-2512 Image Generation', agent: 'Qwen-Image-2512 (ComfyUI)',
          meta: {
            description: '<p><strong>Generates one manga panel image per scene on Qwen-Image-2512 via ComfyUI (video still family default since 2026-08-09); FLUX.1-schnell diffusers is the fallback when ComfyUI is down.</strong></p><ul><li>Manga style: ink lines, screentone, high contrast</li><li>No WAN — panels animated in post with Ken Burns</li></ul>',
            llms:  ['Qwen-Image-2512 (Apache-2.0, local); FLUX.1-schnell (diffusers fallback)'],
            tools: ['ComfyUI qwen_txt2img workflow (video_flux_still_service)', 'FluxPipeline (diffusers — fallback when ComfyUI is down)'],
          }},
        { prompt: 'MediaPipe Anatomy QA', agent: 'MediaPipe Holistic',
          meta: {
            description: '<p><strong>QA on panel anatomy — hands, faces, proportions.</strong></p><ul><li>Stage 2b scorer still calls the legacy mp.solutions Holistic API — non-functional in the production venv (mediapipe 0.10.35): every panel scores 1.0, so the repair tier (Qwen InstantX inpaint → TELEA) never triggers from this gate</li></ul>',
            llms:  ['—'],
            tools: ['MediaPipe Holistic (legacy API — dead in mediapipe 0.10.35, scores default to pass)', 'flux_fill_service.repair_batch (Qwen InstantX inpaint → TELEA)'],
          }},
      ]},
      { id: 'audio', name: 'Audio', cards: [
        { prompt: 'IndexTTS-2 — en-GB-RyanNeural', agent: 'IndexTTS-2 (primary)',
          meta: {
            description: '<p><strong>Primary TTS — per-panel narration via IndexTTS-2, a local zero-shot voice cloner.</strong></p><ul><li>Voice id en-GB-RyanNeural resolves through <code>_voice_seed_for()</code> to a fixed, gender-matched reference WAV</li><li>Same engine as video/documentary pipelines</li><li>Emotion inferred from the panel narration text; no local engine emits word timings, so subtitle timings come from the Whisper backfill</li><li>One MP3 per panel/scene</li></ul>',
            llms:  ['IndexTTS-2 (bilibili, local voice cloning)'],
            tools: ['tts_service', 'IndexTTS-2 subprocess worker (own venv)', 'ffmpeg concat (multi-chunk)'],
          }},
        { prompt: 'Chatterbox — seed-pool voice', agent: 'Chatterbox (fallback)',
          meta: {
            description: '<p><strong>Fallback TTS — only when IndexTTS-2 fails per scene, or when free VRAM is below the ~21 GB gate.</strong></p><ul><li>Chatterbox (Resemble AI, MIT) in its own venv, ~4.1 GB VRAM</li><li>Clones the same seed-pool reference WAV as the primary leg</li><li>Output carries an inaudible Resemble Perth watermark</li><li>Logged as <code>chatterbox-fallback</code> in pipeline output</li></ul>',
            llms:  ['Chatterbox (Resemble AI, MIT)'],
            tools: ['Chatterbox subprocess worker (own venv)', 'ffmpeg concat', 'SRT proportional timer'],
          }},
        { prompt: 'soundbible.com Foley Downloader', agent: 'audio_service.py',
          meta: {
            description: '<p><strong>Optional diegetic SFX matched to panel keywords.</strong></p>',
            llms:  ['—'],
            tools: ['audio_service.py', 'Freesound API (CC, when FREESOUND_API_KEY set)', 'soundbible.com CC0 library'],
          }},
      ]},
      { id: 'video', name: 'Panels', cards: [
        { prompt: 'Ken Burns Panel Animation', agent: 'ffmpeg zoompan',
          meta: {
            description: '<p><strong>Animates each FLUX panel with Ken Burns zoom/pan (30 fps) or static hold (1 fps).</strong></p><ul><li>Default: zoompan Ken Burns per shot type</li><li><code>manga_panel_fps=1</code> → hold/slideshow mode</li><li>No WAN — fast, low VRAM</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg zoompan', 'libx264 encoder'],
          }},
        { prompt: 'ffmpeg Stream Loop + SRT Burn-In', agent: 'ffmpeg',
          meta: {
            description: '<p><strong>Loops panel clip to TTS duration and burns subtitles when narration enabled.</strong></p>',
            llms:  ['—'],
            tools: ['ffmpeg subtitles filter', 'SRT writer'],
          }},
      ]},
      { id: 'assembly', name: 'Assembly', cards: [
        { prompt: 'ffmpeg concat — Final Assembly', agent: 'ffmpeg concat demuxer',
          meta: {
            description: '<p><strong>Concatenates all panel clips into final MP4.</strong></p>',
            llms:  ['—'],
            tools: ['ffmpeg concat demuxer'],
          }},
        { prompt: 'ACE-Step Background Music', agent: 'ACE-Step 1.5 turbo (MIT)',
          meta: {
            description: '<p><strong>Optional BGM under narration.</strong></p>',
            llms:  ['ACE-Step 1.5 turbo (MIT)'],
            tools: ['ace_step_service.py'],
          }},
      ]},
    ],
  }, // end manga

  /* ══════════════════════════════════════════════════════════════════════════
     INTRO PIPELINE
  ══════════════════════════════════════════════════════════════════════════ */
  intro: {
    name: 'Intro',
    label: '[ INTRO PIPELINE ]',
    columns: [

      /* ── Planning ── */
      { id: 'planning', name: 'Planning', cards: [

        { prompt: 'Scene Planning', agent: 'Claude claude-sonnet-4-6',
          meta: {
            description: '<p><strong>Decomposes the intro prompt into a single cinematic scene description.</strong></p><ul><li>One short, visually-driven scene prompt — minimal narration, maximum visual impact</li><li>No multi-scene loop — intro mode always uses 1 scene at 15 seconds</li><li>Narration disabled — the video is silent except for background music</li><li>Output: single scene JSON with image_prompt and visual_style</li></ul>',
            llms:  ['claude-sonnet-4-6 (Anthropic)'],
            tools: ['Anthropic Messages API', 'JSON scene parser', 'Keyword fallback scene builder'],
          }},

      ]},

      /* ── Image Gen ── */
      { id: 'generation', name: 'Image Gen', cards: [

        { prompt: 'FLUX.1-schnell Keyframe', agent: 'Qwen-Image-2512 (ComfyUI)',
          meta: {
            description: '<p><strong>Generates the single cinematic keyframe on Qwen-Image-2512 via ComfyUI (video still family default since 2026-08-09).</strong></p><ul><li>One still from the scene description — no multi-scene loop</li><li>Shot-aware resolution: 1360×768 wide / 896×896 default — scaled and padded to 1920×1080 at assembly</li><li>FLUX.1-schnell (diffusers) loads only as fallback when ComfyUI is unavailable</li><li>Generator VRAM released before WAN loads</li></ul>',
            llms:  ['Qwen-Image-2512 (Apache-2.0, local); FLUX.1-schnell (diffusers fallback)'],
            tools: ['comfy_generation_service (qwen_txt2img)', 'video_flux_still_service (QA retry tiers)', 'FluxPipeline (diffusers — fallback)', 'CUDA VRAM manager'],
          }},

        { prompt: 'LoRA Style Loader', agent: 'LoRA weight loader',
          meta: {
            description: '<p><strong>Applies the documentary-cinematic style LoRA on the diffusers FLUX.1-schnell fallback leg only — the live ComfyUI Qwen-Image-2512 keyframe path applies no FLUX style LoRA.</strong></p><ul><li>Loads checkpoint-6000, scale 0.75 before FLUX inference</li><li>ControlNet and IPAdapter skipped in intro mode to stay within VRAM budget</li><li>LoRA unloaded alongside FLUX after generation</li></ul>',
            llms:  ['—'],
            tools: ['LoRA weight loader (checkpoint-6000, scale 0.75)', 'diffusers load_lora_weights()'],
          }},

      ]},

      /* ── WAN Video ── */
      { id: 'video', name: 'WAN Video', cards: [

        { prompt: 'WAN2.1-I2V Animation', agent: 'WAN2.1-I2V-14B-480P',
          meta: {
            description: '<p><strong>Animates the FLUX keyframe into a 15-second cinematic motion clip.</strong></p><ul><li>Model: WAN2.1-I2V-14B-480P (~28GB VRAM)</li><li>FLUX image used as frame 0 — colour, character, and composition preserved</li><li>duration_seconds=15; no subtitle burn-in; no foley SFX</li><li>Per-shot scheduler shift on the ComfyUI leg — 2.0 close-up / 2.5 medium / 3.5 wide</li></ul>',
            llms:  ['WAN2.1-I2V-14B-480P (local, ~28GB VRAM)'],
            tools: ['wan_video_service.py', 'ComfyUI wan_i2v workflow (WanVideoSampler — primary, ZYG_USE_COMFYUI=1)', 'WanImageToVideoPipeline (diffusers — fallback)', 'CUDA VRAM manager'],
          }},

        { prompt: 'ffmpeg Stream Loop', agent: 'ffmpeg',
          meta: {
            description: '<p><strong>Loops the WAN clip to exactly 15 seconds for the intro output.</strong></p><ul><li>ffmpeg stream_loop repeats WAN output to target duration</li><li>Clean video-only loop — no audio track at this stage</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg stream_loop'],
          }},

      ]},

      /* ── Assembly ── */
      { id: 'assembly', name: 'Assembly', cards: [

        { prompt: 'ACE-Step Background Music', agent: 'ACE-Step 1.5 turbo (MIT)',
          meta: {
            description: '<p><strong>Tier 1 — Generates original music (default 60s, cap 180s) matched to the intro\'s visual mood.</strong></p><ul><li>Runs on the resident ComfyUI server (native ACE-Step 1.5 nodes); VRAM freed after each job — unique every run, no licensing concerns</li><li>Music prompt derived from scene description mood</li><li>Mixed at 12% volume with fade-in/out</li></ul>',
            llms:  ['ACE-Step 1.5 turbo (ACE Studio, local, MIT)'],
            tools: ['ace_step_service.py', 'ComfyUI native ACE-Step 1.5 nodes'],
          }},

        { prompt: 'yt-dlp Music Fallback', agent: 'yt-dlp (Tier 2)',
          meta: {
            description: '<p><strong>Tier 2 — Downloads royalty-free YouTube track when ACE-Step is unavailable.</strong></p><ul><li>~128kbps MP3 matched to scene mood keyword</li><li>Same 12% amix mix chain as Tier 1</li></ul>',
            llms:  ['—'],
            tools: ['yt-dlp', 'ffmpeg amix + afade'],
          }},

        { prompt: 'soundbible.com Ambient Fallback', agent: 'soundbible.com CC0 (Tier 3)',
          meta: {
            description: '<p><strong>Tier 3 — CC0 ambient loop — last resort when Tier 1 and Tier 2 both fail.</strong></p><ul><li>Pre-mapped ambient loop looped to video duration with ffmpeg aloop</li></ul>',
            llms:  ['—'],
            tools: ['soundbible.com CC0 library', 'ffmpeg aloop', 'ffmpeg amix'],
          }},

        { prompt: 'ffmpeg Audio + Video Merge', agent: 'ffmpeg amix',
          meta: {
            description: '<p><strong>Merges the background music track with the looped WAN video into a clean MP4.</strong></p><ul><li>Music-only audio — no narration track in intro mode</li><li>Output: clean MP4 at 1920×1080 ready for title card append</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg amix (12% vol)', 'ffmpeg afade (2s in / 3s out)', 'ffmpeg MP4 muxer'],
          }},

        { prompt: 'ffmpeg Ending Title Card', agent: 'ffmpeg drawtext',
          meta: {
            description: '<p><strong>Appends a 3-second cinematic black title card to the end of the intro.</strong></p><ul><li>Black 1920×1080 frame with centered white studio name text</li><li>Fade-in 0.5s → hold 2s → fade-out 0.5s — classic studio card feel</li><li>Silent audio track synced with card duration</li><li>Concatenated with ffmpeg filter_complex or concat demuxer fallback</li><li>Special characters (colons, apostrophes, backslashes) auto-escaped for drawtext</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg drawtext filter', 'ffmpeg fade filter', 'ffmpeg concat / filter_complex', 'ffprobe (audio stream probe)'],
          }},

      ]},

    ],
  }, // end intro

  /* ══════════════════════════════════════════════════════════════════════════
     STORYTELLER PIPELINE
  ══════════════════════════════════════════════════════════════════════════ */
  storyteller: {
    name: 'Storyteller',
    label: '[ STORYTELLER PIPELINE ]',
    columns: [

      /* ── Character ── */
      { id: 'character', name: 'Character', cards: [

        { prompt: 'Blender 4.3.2 Headless Render', agent: 'Blender 4.3.2 (headless)',
          meta: {
            description: '<p><strong>Stage 1a — Generates a fully parametric 3D character using Blender in headless mode and renders 20 reference angles.</strong></p><ul><li>Accepts the wizard Step 1 spec <em>and</em> the new <strong>Advanced Identity</strong> panel (face shape, eye shape, hair length/texture, nose/lip shape, distinctive marks, default clothing, accessories, expression, posture, heritage hint, custom quality / negative prompt). Anything left on <code>Auto</code> is auto-filled by <code>character_bible_service.apply_auto_defaults()</code> using gender / genre / age / hair-colour heuristics, so every descriptor reaching ComfyUI is concrete.</li><li>Builds from mesh primitives: UV sphere (head), cylinders (torso/limbs), cubes (feet)</li><li>Height scaled via <code>HEIGHT_SCALE = height_m / 1.70</code></li><li><strong>Animated style</strong> → Toon BSDF shader; <strong>Photorealistic</strong> → Principled BSDF + subsurface scattering</li><li>Renders 16 full-body angles (22.5° steps, 50mm lens, 2.8m) + 4 face close-ups (85mm, 0.55m) = 20 images</li><li>Writes <code>manifest.json</code> listing all render paths for the LoRA trainer</li></ul>',
            llms:  ['—'],
            tools: ['Blender 4.3.2 (blender --background --python)', 'blender_scripts/generate_character.py', 'Blender BSDF shader builder', 'Blender camera rig (20 angles)'],
          }},

        { prompt: 'FLUX Character Render', agent: 'FLUX.1-schnell (Blender fallback)',
          meta: {
            description: '<p><strong>Fallback character generation — if Blender is unavailable or fails, FLUX generates 20 character images directly.</strong></p><ul><li>Only activated when Blender headless render fails or Blender is not installed</li><li>Generates 20 images with descriptive prompts covering all required angles</li><li>Prompts include: angle descriptor, gender, hair, eye colour, height, skin tone, visual style</li><li>Less consistent than Blender renders — LoRA training may be less precise</li></ul>',
            llms:  ['—'],
            tools: ['FLUX.1-schnell (Black Forest Labs, local)', 'FluxPipeline (diffusers)', 'blender_character_service.py (_flux_fallback)', 'CUDA VRAM manager'],
          }},

        { prompt: 'Caption Generation', agent: 'blender_character_service.py',
          meta: {
            description: '<p><strong>Stage 1b — Generates training caption .txt files paired with each of the 20 character renders.</strong></p><ul><li>Full-body captions: <em>"ZYG_CHAR_XXXXXX, a [age]-year-old [gender] character with [hair length+texture+color] hair, [face shape] face, [eye shape+color] eyes, [skin] skin, [build], wearing [default clothing], [accessories], [expression] expression, [posture], full body, [angle]° view"</em></li><li>Close-up captions: <em>"ZYG_CHAR_XXXXXX, close-up face portrait, [gender] character with [face shape] face, [nose shape] nose, [lip shape] lips, [distinctive marks]…"</em></li><li>Trigger token <code>ZYG_CHAR_XXXXXX</code> is the LoRA anchor — injected into every FLUX scene prompt at generation time</li><li>Captions now carry the full Advanced Identity descriptor set so the trained LoRA learns face shape, eye shape, hair structure, wardrobe and distinctive marks together — not just colour</li><li>Output: dataset folder at <code>lora-datasets/storyteller_chars/&lt;char_id&gt;/</code></li></ul>',
            llms:  ['—'],
            tools: ['blender_character_service.py (_write_captions)', 'Caption .txt writer (one per image)', 'Trigger token generator (ZYG_CHAR_<id[:6].upper()>)'],
          }},

      ]},

      /* ── LoRA Training ── */
      { id: 'training', name: 'LoRA Training', cards: [

        { prompt: 'SimpleTuner FLUX LoRA Training', agent: 'SimpleTuner (background thread)',
          meta: {
            description: '<p><strong>Stage 1c — Trains a custom FLUX LoRA on the 20 character renders so all story images feature the same face and body.</strong></p><ul><li>Config: epoch-scaled steps (1200 base, floor 900 / cap 1800), lora_rank=64, lora_alpha=32, 1024px pixel-area buckets, 20 repeats/image, int8-quanto base + bf16</li><li>Base model: flux1-dev (schnell is distilled — rejected for LoRA training). FLUX training is PAUSED by the 2026-08-09 licence gate (BFL NC): refused as <code>flux_licence_paused</code>, run continues in IPAdapter-only mode; SDXL/Qwen family training is unaffected</li><li>Runs in a background thread via ThreadPoolExecutor — wizard continues immediately</li><li>Status polled every 12s by the browser — shows % progress in Step 5</li><li>Pipeline waits up to 90 minutes at Stage 1 (ZYG_LORA_PIPELINE_WAIT_S=5400); if still training → IPAdapter-only mode</li><li>Checkpoint saved to <code>lora-outputs/storyteller_chars/&lt;char_id&gt;/</code></li></ul>',
            llms:  ['FLUX.1-dev (LoRA training base — PAUSED by the 2026-08-09 licence gate)'],
            tools: ['lora_trainer_service.py', 'SimpleTuner (train.py)', 'SimpleTuner config.json writer', 'SimpleTuner multidatabackend.json writer', 'tqdm step parser (progress %)', 'ThreadPoolExecutor (background)'],
          }},

        { prompt: 'IPAdapter-Only Mode (LoRA timeout fallback)', agent: 'XLabs flux-ip-adapter',
          meta: {
            description: '<p><strong>Activated when FLUX LoRA training is licence-paused (2026-08-09 gate) or doesn\'t complete within the 90-minute wait — uses IPAdapter face injection instead.</strong></p><ul><li>First character render used as face reference image</li><li>Face embedding injected into every FLUX scene prompt via cross-attention</li><li>Less precise than a trained LoRA but ensures character visual consistency without waiting</li><li>Applied in FLUX Image Gen stage when <code>lora_ready = False</code></li></ul>',
            llms:  ['—'],
            tools: ['XLabs flux-ip-adapter weights', 'Face encoder (CLIP ViT-H)', 'IPAdapterFluxPipeline (diffusers)', 'CUDA VRAM manager'],
          }},

      ]},

      /* ── Story Script ── */
      { id: 'scripting', name: 'Story Script', cards: [

        { prompt: 'Claude claude-sonnet-4-6 — Story Script', agent: 'Claude claude-sonnet-4-6',
          meta: {
            description: '<p><strong>Stage 2 — Claude writes the complete scene-by-scene story calibrated to duration, era, and character.</strong></p><ul><li>Inputs: story_prompt, character_params (full Advanced Identity set — age, face/eye/lip/nose shape, hair length+texture, build, clothing, accessories, expression, posture, heritage, distinctive marks), era_start, era_end, clip_duration_minutes, camera_mode, visual_style</li><li>Claude\'s character brief now includes <em>"a [age]-year-old [heritage] [gender], [face shape] face, [build], [hair phrase], wearing [default clothing], [accessories], [expression] expression, rendered in [render style] style"</em> so generated scene prompts inherit consistent identity language</li><li>Computes n_scenes: ≤0.5 min → int(dur×60/7), 0.5–3 min → int(dur×60/8), &gt;3 min → int(dur×60/9), max 120</li><li>Produces JSON array: title, narration, image_prompt, shot_type, emotion, focal_zone per scene</li><li>Character trigger token injected into every image_prompt for LoRA anchoring</li><li>Era context injected: period-appropriate settings, clothing, props, atmosphere</li></ul>',
            llms:  ['Claude claude-sonnet-4-6 (Anthropic)'],
            tools: ['Anthropic Messages API', 'JSON scene parser', 'Fallback scene builder (regex)'],
          }},

        { prompt: 'Murch Engine — Emotion & Shot Analysis', agent: 'Murch Engine (murch_engine.py)',
          meta: {
            description: '<p><strong>Stage 2b — Parses Claude\'s scene metadata to drive the Ken Burns and xfade engines.</strong></p><ul><li>Each scene carries: emotion (calm/tension/awe/grief/triumph/mystery/shock/unease), shot_type, focal_zone</li><li>Emotion speed multiplier → Ken Burns zoom rate: grief=0.55×, calm=0.70×, mystery=0.80×, awe=1.0×, tension=1.4×, shock=1.5×</li><li>Focal zone anchor: center=0.50, left=0.25, right=0.75, top=0.20, bottom=0.80</li><li>31-entry transition table + 17 shot-tightness override rules for cinematic xfades</li></ul>',
            llms:  ['—'],
            tools: ['murch_engine.py (build_xfade_filter_graph)', 'Emotion-speed map', 'Shot-tightness transition table (17 rules)', 'Focal-zone anchor calculator'],
          }},

      ]},

      /* ── Narration ── */
      { id: 'audio', name: 'Narration', cards: [

        { prompt: 'IndexTTS-2', agent: 'IndexTTS-2 (user-selected voice)',
          meta: {
            description: '<p><strong>Stage 3 — Synthesises the full story narration with IndexTTS-2, cloning the voice selected in wizard Step 2.</strong></p><ul><li>Voice options: Aria (US female), Sonia (UK female), Ana (US girl), Ryan (UK male), Christopher (US male), Jacob (US boy), Brian (US narrator), Thomas (UK documentary) — the ids keep their historical spelling and are now opaque handles</li><li><code>tts_service._voice_seed_for()</code> maps each id to a gender-matched, deterministic reference WAV from the 16-voice seed pool (8 male / 8 female), so a character keeps one voice across episodes</li><li>Emotion is inferred from the story text itself (<code>use_emo_text</code>) — no markup is added to the narration</li><li>Word and subtitle timings come from the Whisper backfill; no local engine emits them</li><li>TTS duration is the master clock — FLUX scene durations fitted to match narration length exactly</li></ul>',
            llms:  ['IndexTTS-2 (bilibili, local voice cloning — user-selected voice)'],
            tools: ['tts_service (IndexTTS-2 subprocess worker)', 'voice seed pool (_voice_seed_for)', 'Duration extractor (soundfile / ffprobe)', 'Whisper word-timing backfill'],
          }},

        { prompt: 'Chatterbox — seed-pool voice', agent: 'Chatterbox (fallback)',
          meta: {
            description: '<p><strong>Fallback TTS — Chatterbox (Resemble AI, MIT) when IndexTTS-2 fails or free VRAM is below the ~21 GB gate.</strong></p><ul><li>Clones the same gender-matched seed-pool reference WAV, so the selected voice survives the fallback</li><li>~4.1 GB VRAM — fits beside a GPU that is already loaded</li><li>Saves full narration as MP3; output carries an inaudible Resemble Perth watermark</li><li>TTS duration extracted with ffprobe for scene timing</li></ul>',
            llms:  ['Chatterbox (Resemble AI, MIT)'],
            tools: ['Chatterbox subprocess worker (own venv)', 'ffmpeg encode', 'ffprobe duration extractor'],
          }},

      ]},

      /* ── Image Gen ── */
      { id: 'generation', name: 'Image Gen', cards: [

        { prompt: 'FLUX + Character LoRA', agent: 'FLUX + Character LoRA',
          meta: {
            description: '<p><strong>Stage 3.5 — Generates one scene image per story scene with the character LoRA injected.</strong></p><ul><li>Model: FLUX.1-schnell — flux1-dev is PAUSED (2026-08-09 licence gate). While paused, flux-family Comfy renders refuse (<code>flux_licence_paused</code> — a dev-trained character LoRA stays NC on any unet; no schnell fallback on Comfy) and scenes fall back to the diffusers schnell leg; character LoRA loaded at scale 0.8 if training completed</li><li>Every image_prompt from Claude already contains the trigger token (e.g. ZYG_CHAR_ABC123) — LoRA anchors character identity across all scenes</li><li><strong>ComfyUI path</strong>: when <code>ZYG_COMFY_PRIMARY=1</code>, scenes are routed through <code>comfy_generation_service</code>, which:<ul><li>builds the positive prompt = <code>identity_prompt_prefix(bible)</code> + scene + <code>indoor_style_suffix</code> + <code>quality_suffix</code></li><li>writes the per-character <code>negative_prompt</code> from the bible into node 21 (no longer always empty)</li><li>auto-selects workflow: <code>flux_character_locked</code> (LoRA only) → <code>flux_character_ipadapter</code> (+IPAdapter when master reference exists) → <code>flux_character_instantid</code> (when <code>conditioning.instantid_enabled=true</code> AND InstantID/PuLID nodes are installed)</li><li>runs the <strong>FaceDetailer second pass</strong> automatically when Impact-Pack is installed (auto-stripped if not) — re-renders just the face at higher detail to fix FLUX\'s wide-shot muddiness</li></ul></li><li>Camera angle from wizard Step 4 appended to every prompt: automatic / front / ¾ / side / close-up / overhead / low</li><li>Resolution: 1280×720 (HD widescreen) — matches Ken Burns output</li><li>Up to 120 scenes; progress reported 30→60%</li><li>FLUX unloaded from VRAM after this stage (and ComfyUI <code>/free</code> is called before stage start)</li></ul>',
            llms:  ['FLUX.1-schnell (Black Forest Labs, local)'],
            tools: ['FluxPipeline (diffusers)', 'Character LoRA weight loader (lora-outputs/storyteller_chars/)', 'CUDA VRAM manager (_gpu_lock)'],
          }},

        { prompt: 'IPAdapter Face Injection (LoRA fallback)', agent: 'XLabs flux-ip-adapter',
          meta: {
            description: '<p><strong>Active when LoRA training did not complete in time — injects character face via IPAdapter cross-attention.</strong></p><ul><li>Only used when lora_ready = False (LoRA timed out)</li><li>First Blender render used as face reference</li><li>Consistent face across all FLUX scene images via embedding injection</li></ul>',
            llms:  ['—'],
            tools: ['XLabs flux-ip-adapter weights', 'Face encoder (CLIP ViT-H)', 'IPAdapterFluxPipeline (diffusers)', 'CUDA VRAM manager'],
          }},

      ]},

      /* ── Ken Burns ── */
      { id: 'animation', name: 'Ken Burns', cards: [

        { prompt: 'PIL Ken Burns Renderer', agent: '_render_kb_pil_shared (PIL EXTENT)',
          meta: {
            description: '<p><strong>Stage 4 — Animates every scene image into a smooth Ken Burns motion clip using true sub-pixel bicubic rendering.</strong></p><ul><li>PIL Image.transform(EXTENT) + bicubic — maps a float source rectangle to output at each frame with no integer quantisation</li><li>Eliminates the freeze-then-snap stutter caused by FFmpeg zoompan\'s integer crop math</li><li>Motion types: push_in (close-up/tight), pull_out (every 3rd medium), pan_r/pan_l (wide, alternating), drift (overhead/drone)</li><li>Zoom delta scaled by emotion speed multiplier; focal zone locks push/pull anchor to subject</li><li>Parallel: ThreadPoolExecutor up to 16 workers — each slot owns its PIL image + ffmpeg subprocess</li></ul>',
            llms:  ['—'],
            tools: ['_render_kb_pil_shared() (module-level, slide_w=1280, slide_h=720)', 'PIL Image.transform(EXTENT, BICUBIC)', 'ThreadPoolExecutor (max_workers=min(cpu_count, n_imgs, 16))'],
          }},

        { prompt: 'ffmpeg libx264 Frame Encoder', agent: 'ffmpeg (rawvideo → libx264)',
          meta: {
            description: '<p><strong>Encodes PIL-rendered frames into a per-scene MP4 clip using ffmpeg rawvideo pipe.</strong></p><ul><li>Each PIL frame piped as raw RGB to an ffmpeg subprocess</li><li>Codec: libx264 ultrafast, CRF 15 — high quality, fast encode</li><li>24fps output; each clip duration fitted to TTS narration length (clamped 3–30s per scene)</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg rawvideo input (stdin pipe)', 'ffmpeg libx264 encoder (ultrafast, CRF 15)', 'ffmpeg MP4 muxer'],
          }},

      ]},

      /* ── Assembly ── */
      { id: 'assembly', name: 'Assembly', cards: [

        { prompt: 'Murch Engine — xfade Graph Builder', agent: 'Murch Engine (murch_engine.py)',
          meta: {
            description: '<p><strong>Stage 5a — Builds the ffmpeg xfade filter graph from 31-entry emotion table + 17 shot-tightness overrides.</strong></p><ul><li>Emotion table: grief→fade, calm→fade, mystery→dissolve, awe→wipeleft, tension→cut, shock→cut, triumph→wiperight, unease→smoothleft</li><li>17 shot-tightness rules: close→wide = pull-back dissolve, wide→close = push-in dissolve, overhead→any = fadeblack</li><li>Hard-cut guard: shock/tension always hard-cut regardless of emotion table</li><li>Transition duration: 0.3–0.8s based on emotion intensity</li></ul>',
            llms:  ['—'],
            tools: ['murch_engine.py (build_xfade_filter_graph)', '_TRANSITION_TABLE (31 entries)', '_SHOT_TRANSITION_OVERRIDES (17 rules)'],
          }},

        { prompt: 'ffmpeg xfade — Transition Assembly', agent: 'ffmpeg xfade filter',
          meta: {
            description: '<p><strong>Stage 5b — Applies cinematic transitions between all scene clips using the Murch Engine xfade graph.</strong></p><ul><li>ffmpeg filter_complex: per-image scale (lanczos) → xfade chain → [vout]</li><li>Fallback: hard-cut concat if Murch Engine or xfade graph fails</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg filter_complex (scale + xfade)', 'ffmpeg concat demuxer (hard-cut fallback)'],
          }},

        { prompt: 'ffmpeg Audio + Video Merge', agent: 'ffmpeg amix',
          meta: {
            description: '<p><strong>Stage 5c — Combines the assembled slideshow video with the TTS narration and optional music.</strong></p><ul><li>TTS narration merged with background music via amix if music present, else stream-copied</li><li>Output: MP4 at 1280×720, audio AAC 192k</li><li>If TTS was skipped: video-only output</li></ul>',
            llms:  ['—'],
            tools: ['ffmpeg amix (TTS + music)', 'ffmpeg output: 1280×720 MP4, AAC 192k'],
          }},

        { prompt: 'ACE-Step Background Music', agent: 'ACE-Step 1.5 turbo (MIT)',
          meta: {
            description: '<p><strong>Tier 1 — AI-generates a background music track matched to the story\'s dominant emotion.</strong></p><ul><li>Original instrumental track (default 60s, cap 180s) on the resident ComfyUI server — MIT weights, no licensing concerns</li><li>Dominant emotion across all scenes → maps to: battle / triumphant / epic / mysterious / sad / peaceful / dark / adventure</li><li>Mixed at 12% volume with 2s fade-in and 3s fade-out under narration</li></ul>',
            llms:  ['ACE-Step 1.5 turbo (ACE Studio, local, MIT)'],
            tools: ['ace_step_service.py', 'ComfyUI native ACE-Step 1.5 nodes', 'ffmpeg amix + afade'],
          }},

        { prompt: 'yt-dlp Music Fallback', agent: 'yt-dlp (Tier 2)',
          meta: {
            description: '<p><strong>Tier 2 — Downloads royalty-free YouTube track when ACE-Step is unavailable.</strong></p><ul><li>Emotion keyword → YouTube search → ~128kbps MP3 download</li><li>Same 12% amix chain as Tier 1</li></ul>',
            llms:  ['—'],
            tools: ['yt-dlp', 'ffmpeg amix + afade'],
          }},

        { prompt: 'soundbible.com Ambient Fallback', agent: 'soundbible.com CC0 (Tier 3)',
          meta: {
            description: '<p><strong>Tier 3 — CC0 ambient loop — last resort when Tier 1 and Tier 2 both fail.</strong></p><ul><li>Dominant emotion → ambient loop selection (ocean / rain / forest / wind)</li><li>Looped to match video duration</li></ul>',
            llms:  ['—'],
            tools: ['soundbible.com CC0 library', 'ffmpeg aloop', 'ffmpeg amix'],
          }},

      ]},

    ],
  }, // end storyteller

  /* ══════════════════════════════════════════════════════════════════════════
     CHARACTER CREATION PIPELINE
  ══════════════════════════════════════════════════════════════════════════ */
  character_creation: {
    name: 'Character Creation',
    label: '[ CHARACTER CREATION ]',
    columns: [

      /* ── 3D Render ── */
      { id: 'render', name: '3D Render', cards: [

        { prompt: 'Blender 4.3.2 Headless Render', agent: 'Blender 4.3.2 (headless)',
          meta: {
            description: '<p><strong>Stage 1a — Renders 20 reference angles of the character in Blender (headless).</strong></p><ul><li>Accepts the Step 1 spec <em>plus</em> the new Advanced Identity panel (face shape, eye shape, hair length/texture, nose/lip shape, distinctive marks, default clothing, accessories, expression, posture, heritage, custom quality/negative prompt). Fields left on <code>Auto</code> are filled by <code>character_bible_service.apply_auto_defaults()</code> before this stage runs.</li><li>16 full-body angles (22.5° steps) + 4 face close-ups = 20 renders</li><li>Animated style → Toon BSDF; Photorealistic → Principled BSDF + SSS</li><li>Writes manifest.json with all render paths for the LoRA trainer</li></ul>',
            llms:  ['—'],
            tools: ['Blender 4.3.2 (--background --python)', 'blender_scripts/generate_character.py', 'Blender BSDF shader builder', 'Blender camera rig (20 angles)'],
          }},

        { prompt: 'FLUX Character Render', agent: 'FLUX.1-schnell (Blender fallback)',
          meta: {
            description: '<p><strong>Fallback — if Blender is unavailable, FLUX generates 20 character images directly.</strong></p><ul><li>Activated when Blender fails or is not installed</li><li>Prompts cover all angles: gender, hair, eyes, height, skin, visual style</li><li>Less geometrically consistent than Blender renders — LoRA may be less precise</li></ul>',
            llms:  ['—'],
            tools: ['FLUX.1-schnell (Black Forest Labs, local)', 'FluxPipeline (diffusers)', 'blender_character_service.py (_flux_fallback)', 'CUDA VRAM manager'],
          }},

      ]},

      /* ── Dataset ── */
      { id: 'dataset', name: 'Dataset', cards: [

        { prompt: 'Caption Generation', agent: 'blender_character_service.py',
          meta: {
            description: '<p><strong>Stage 1b — Writes training caption .txt files paired with each of the 20 renders.</strong></p><ul><li>Full-body: "ZYG_CHAR_XXXXXX, a [age]-year-old [gender] character, [face shape] face, [hair length+texture+colour] hair, [eye shape+colour] eyes, [skin] skin, [build], wearing [default clothing], [accessories], [expression] expression, [posture]…"</li><li>Close-up: "ZYG_CHAR_XXXXXX, close-up face portrait, [face shape] face, [nose shape] nose, [lip shape] lips, [distinctive marks]…"</li><li>Trigger token is the LoRA anchor — injected into every FLUX scene prompt at generation time</li><li>Captions now carry the full Advanced Identity set so the LoRA learns face shape, nose, lips, hair structure and wardrobe together — not just colour</li><li>Output: lora-datasets/storyteller_chars/&lt;char_id&gt;/</li></ul>',
            llms:  ['—'],
            tools: ['blender_character_service.py (_write_captions)', 'Caption .txt writer', 'Trigger token generator (ZYG_CHAR_<id[:6].upper()>)'],
          }},

      ]},

      /* ── LoRA Training ── */
      { id: 'lora', name: 'LoRA Training', cards: [

        { prompt: 'SimpleTuner FLUX LoRA Training', agent: 'SimpleTuner (background thread)',
          meta: {
            description: '<p><strong>Stage 1c — Trains a custom FLUX LoRA on the 20 renders.</strong></p><ul><li>1000 steps, lora_rank=64, lora_alpha=32, 512×512, 20 repeats/image, bfloat16</li><li>Runs in background — wizard continues immediately; status polled every 12s</li><li>Pipeline waits up to 30 min; if still training → IPAdapter-only mode</li><li>Checkpoint saved to lora-outputs/storyteller_chars/&lt;char_id&gt;/</li></ul>',
            llms:  ['FLUX.1-dev (training base — schnell is inference-only; flux training refused while licence-paused)'],
            tools: ['lora_trainer_service.py', 'SimpleTuner (train.py)', 'SimpleTuner config.json writer', 'tqdm step parser', 'ThreadPoolExecutor'],
          }},

        { prompt: 'IPAdapter-Only Mode (LoRA timeout fallback)', agent: 'XLabs flux-ip-adapter',
          meta: {
            description: '<p><strong>Fallback — activates if LoRA training exceeds 30 minutes.</strong></p><ul><li>Uses first render as face reference — injected via IPAdapter cross-attention</li><li>Less precise than a trained LoRA but guarantees character consistency</li><li>Applied automatically in Stage 3.5 when lora_ready = False</li></ul>',
            llms:  ['—'],
            tools: ['XLabs flux-ip-adapter weights', 'Face encoder (CLIP ViT-H)', 'IPAdapterFluxPipeline (diffusers)', 'CUDA VRAM manager'],
          }},

      ]},

    ],
  }, // end character_creation

  /* ══════════════════════════════════════════════════════════════════════════
     MULTI-ANGLE CONTACT SHEET PIPELINE
  ══════════════════════════════════════════════════════════════════════════ */
  contact_sheet_creation: {
    name: 'Multi-Angle Contact Sheet',
    label: '[ MULTI-ANGLE CONTACT SHEET ]',
    columns: [
      { id: 'sheet', name: 'Contact Sheet', cards: [
        { prompt: 'Contact Sheet Generation', agent: 'contact_sheet_pipeline.py',
          meta: {
            description: '<p><strong>Stage 1 — Generate 48 true angles per-cell (yaw ring, pitch ring, fine head ring, crown/chin + T-pose ortho).</strong></p><ul><li>Approved anchor (auto family: Qwen-Image-2512 while FLUX.1-dev is licence-paused, FLUX otherwise), then Qwen-Image-Edit per-cell rotations (angles LoRA at 0.9 since 2026-07-16, <code>ZYG_QWEN_EDIT_ANGLES_LORA_SCALE</code>); IP-Adapter/pose ControlNet fallbacks; full-body cells at 2:3</li><li>Optional best-of-N per cell: <code>ZYG_CONTACT_SHEET_BEST_OF</code> ≥2 generates N seeds and keeps the ArcFace-best (default 1)</li><li>Qwen-Image-Edit-2511 downloaded, opt-in via <code>ZYG_QWEN_EDIT_UNET</code> (A/B vs 2509 first — angles LoRA is 2509-trained)</li><li><strong>Attribute compliance gate (2026-07-16):</strong> VLM reads the delivered anchor vs the spec (eye colour / hair / skin tone); mismatches retry with boosted tokens + wrong-colour negatives, then a targeted qwen iris recolour; whatever ships is synced back to the character bible</li><li>Stitched preview pages + composite saved as <code>contact_sheet/contact_sheet_master.png</code> (preview only — never sliced; re-stitched after QC repairs)</li><li>Inspect before training — Agent Zero approval gate</li></ul>',
            llms:  ['—'],
            tools: ['contact_sheet_pipeline.generate_contact_sheet()', 'comfy_generation_service.generate_still()', '_generate_cell_best_of()', 'cell_vlm_judge.judge_attributes()'],
          }},
        { prompt: 'QC Safety Valve', agent: 'Agent Zero (only if quality collapses)',
          meta: {
            description: '<p><strong>Stage 2 — Normally skipped: single-approval flow continues straight to identity QC.</strong></p><ul><li>The run parks here ONLY when the usable-tile rate drops below <code>ZYG_CONTACT_SHEET_QC_MIN_PASS_RATE</code> (default 60%)</li><li>Usable = verdict-OK minus EVERY dataset exclusion (2026-07-16): VLM-flagged ghost tiles keep verdict "pass" but count against the valve, so a mass ghost event parks the run</li><li>Zero then sends a review card; Allow resumes, or the run stays parked</li></ul>',
            llms:  ['—'],
            tools: ['contact_sheet_pipeline.wait_for_approval()'],
          }},
      ]},
      { id: 'dataset', name: 'Dataset', cards: [
        { prompt: 'Tile Crop', agent: 'contact_sheet_pipeline.py',
          meta: {
            description: '<p><strong>Stage 3 — Collect per-angle tiles.</strong></p><ul><li>Per-cell mode (default): each of the 48 angles is its own generated image — tiles are copied, never sliced from a grid</li><li>Legacy grid modes still slice sheets (preview-quality only)</li><li>Output: <code>contact_sheet/tiles/tile_XX.png</code></li></ul>',
            llms:  ['—'],
            tools: ['contact_sheet_pipeline.split_sheet_into_tiles()'],
          }},
        { prompt: 'Identity QC (ArcFace)', agent: 'identity_qc_service.py',
          meta: {
            description: '<p><strong>Stage 4 — Face-embedding drift gate + pose verification on every tile vs the sheet-A anchor.</strong></p><ul><li>antelopev2 ArcFace default (AuraFace opt-in via <code>ZYG_IDQC_PACK</code>, pack-calibrated thresholds) cosine, angle-aware thresholds (frontal 0.42 / profile 0.25, back views exempt)</li><li>Pose gates (2026-07-16): head roll &gt;55° = bad_orientation (catches sideways/upside-down frames, back/crown exempt); frontal labels fail above 60° yaw, oblique below 12°, profile below 12°</li><li>Fail-closed no_face: ANY face-expected tile with no detectable face regenerates or is dropped — never trained on</li><li>Escalation ladder per bad tile: fresh-seed qwen re-edit → chain-edit from the nearest PASSING cell (full-body tiles exempt) → FLUX IP-Adapter switch → drop; best candidate wins, regens match original params (guidance 1.0)</li></ul>',
            llms:  ['—'],
            tools: ['identity_qc_service.score_images_against_anchor()', 'contact_sheet_pipeline.run_identity_qc()', '_identity_embed_worker.py (yaw+roll export)'],
          }},
        { prompt: 'VLM Defect Judge', agent: 'cell_vlm_judge.py',
          meta: {
            description: '<p><strong>Stage 4b (2026-07-16) — Tiered vision-model review of every tile: the only gate that sees translucent ghost faces.</strong></p><ul><li>ArcFace, face detectors (det 0.22) and Laplacian texture are all measured-blind to ghost remnants (Kira Dunn audit) — this gate exists for exactly that class</li><li>Tier 1: local Ollama <code>qwen3.5:9b</code> (free) catches gross defects; Tier 2: Claude vision (pairwise anchor+cell, ~cents/sheet) catches subtle on-face ghosts</li><li>Flag-only semantics: a flag routes the tile into the regen ladder and, if unrepaired, into fail-closed dataset exclusion — a clean verdict never overrides other gates</li><li>3-strike circuit breaker per tier; local model unloaded before any ComfyUI generation (VRAM)</li><li>Env: <code>ZYG_CELL_VLM_JUDGE / _LOCAL / _CLOUD / _CLOUD_MODEL</code></li><li>Known limit: faintest rear-hair ghosts evade single-shot VLMs — human sheet review remains the final gate</li></ul>',
            llms:  ['qwen3.5:9b (Ollama, local)', 'claude-sonnet-4-6 (Anthropic API)'],
            tools: ['cell_vlm_judge.judge_cell()', 'cell_vlm_judge.release()'],
          }},
        { prompt: 'Caption Generation', agent: 'contact_sheet_pipeline.py',
          meta: {
            description: '<p><strong>Stage 5 — Per-tile captions + copy to dataset as <code>contactsheet_XX.png</code>.</strong></p><ul><li>Trigger token on every caption</li><li>QC-excluded tiles are skipped</li><li>Updates manifest.json for SimpleTuner</li></ul>',
            llms:  ['—'],
            tools: ['contact_sheet_pipeline.write_tile_captions()'],
          }},
      ]},
      { id: 'lora', name: 'LoRA Training', cards: [
        { prompt: 'SimpleTuner FLUX LoRA Training', agent: 'SimpleTuner (background thread)',
          meta: {
            description: '<p><strong>Stage 6 — Train character LoRA v1 from QC-passed tiles (optional dual SDXL for photoreal).</strong></p><ul><li><strong>DISABLED by default since 2026-07-16</strong> while the sheet workflow is hardened — the run stops after the dataset is fully prepared so a human reviews the sheet first; re-enable with <code>ZYG_CONTACT_SHEET_LORA_TRAINING=1</code></li><li>Uses existing <code>lora_trainer_service</code> (self-cleans checkpoints after success)</li><li>Skippable per-run with <code>kick_lora=false</code></li></ul>',
            llms:  ['FLUX.1-dev (flux runs — training refused while licence-paused)', 'Qwen-Image-2512 (qwen runs)'],
            tools: ['lora_trainer_service', '_char_train_lora_for_family()'],
          }},
        { prompt: 'Angle Expansion (LoRA v1)', agent: 'contact_sheet_pipeline.py',
          meta: {
            description: '<p><strong>Stage 7 — LoRA flywheel: v1 generates the angles a face embedding cannot lock. (Inactive while training is disabled.)</strong></p><ul><li>16 hard angles: backs, crown, worm/bird eye, back three-quarters, T-pose ortho</li><li>Each survivor is ArcFace-gated where a face is visible AND VLM-judged (2026-07-16) — expansion tiles come from the same ghost-prone qwen-edit path as the sheet</li><li>Kept images join the dataset as <code>expansion_XX.png</code></li></ul>',
            llms:  ['FLUX.1-dev + character LoRA v1 (flux runs — paused)', 'Qwen-Image-2512 + character LoRA v1 (qwen runs)'],
            tools: ['contact_sheet_pipeline.run_angle_expansion()', 'cell_vlm_judge.judge_cell()'],
          }},
        { prompt: 'LoRA Refine (v2)', agent: 'SimpleTuner (background thread)',
          meta: {
            description: '<p><strong>Stage 8 — Retrain on the expanded dataset → LoRA v2 with full angular coverage.</strong></p><ul><li>48 sheet tiles + kept expansion angles</li><li>Failure keeps v1 (non-fatal)</li><li>Character bible updated to v2</li></ul>',
            llms:  ['FLUX.1-dev (flux runs — training refused while licence-paused)', 'Qwen-Image-2512 (qwen runs)'],
            tools: ['lora_trainer_service', 'character_bible_service.update_lora()'],
          }},
      ]},
    ],
  }, // end contact_sheet_creation

  /* ══════════════════════════════════════════════════════════════════════════
     CREATURE CREATION PIPELINE
  ══════════════════════════════════════════════════════════════════════════ */
  creature_creation: {
    name: 'Creature Creation',
    label: '[ CREATURE CREATION — MULTI-ANGLE SHEET + LORA ]',
    columns: [
      { id: 'brief', name: 'Brief', cards: [
        { prompt: 'Creature Brief', agent: 'Ollama vision (qwen3.5:9b)',
          meta: {
            description: '<p><strong>Stage 1 — The local vision model DESCRIBES your reference image(s) (or your text concept) into a training brief.</strong></p><ul><li>Name, species, colours, eyes, fur/skin texture, distinctive features, rendering style</li><li>Source is explicit: <code>reference</code> (1..n uploaded images) or <code>scratch</code> (text only)</li></ul>',
            llms:  ['qwen3.5:9b vision (Ollama, local)'],
            tools: ['creature_training_service._generate_creature_brief()'],
          }},
      ]},
      { id: 'sheet', name: 'Multi-Angle Sheet', cards: [
        { prompt: 'Reference Anchor', agent: 'Qwen-Image-Edit-2509 / FLUX.2 klein-4B',
          meta: {
            description: '<p><strong>Stage 2a — The identity anchor.</strong></p><ul><li>Reference mode: the best-framed upload is the anchor; a FULL-BODY anchor is derived by edit when the upload is a close-up — judged against the source</li><li>Scratch mode: FLUX.2 klein-4B txt2img, best-of-3 seeds, each judged against the brief</li></ul>',
            llms:  ['Qwen-Image-Edit-2509 (Apache-2.0)', 'FLUX.2 klein-4B (Apache-2.0)'],
            tools: ['creature_sheet_service.build_sheet()'],
          }},
        { prompt: 'Multi-Angle Sheet', agent: 'Qwen-Image-Edit-2509 + multiple-angles LoRA',
          meta: {
            description: '<p><strong>Stage 2b — 16 camera-rotation EDITS of the anchor (8 in compact mode).</strong></p><ul><li>Front, 3/4 L/R, side L/R, back 3/4 L/R, behind, high, low, top-down, 3 face close-ups, wide, texture detail</li><li>Identity is inherited from the anchor, not re-rolled per cell</li></ul>',
            llms:  ['Qwen-Image-Edit-2509 + dx8152 multiple-angles LoRA'],
            tools: ['comfy_generation_service.generate_still(qwen_edit_angle)'],
          }},
        { prompt: 'Sheet QC', agent: 'Qwen3-VL judge + DINOv2',
          meta: {
            description: '<p><strong>Stage 2c — Every cell is judged three ways.</strong></p><ul><li>Structural: blank frame, unchanged-vs-anchor, duplicates (phash)</li><li>Identity: DINOv2 CLS cosine vs the anchor (ArcFace is blind to creatures)</li><li>Semantic: Qwen3-VL binary checklist on a REFERENCE|CANDIDATE strip — same creature, one subject, no human, no text, anatomy, viewpoint</li><li>Failed cells regenerate (2 rounds); unrepaired cells stay on the sheet as EXCLUDED</li></ul>',
            llms:  ['Qwen3-VL-8B-Instruct-FP8 (resident tier)', 'facebook/dinov2-base'],
            tools: ['creature_judge.judge_batch()', 'creature_identity.similarity()'],
          }},
      ]},
      { id: 'review', name: 'Review', cards: [
        { prompt: 'Sheet Review', agent: 'Operator',
          meta: {
            description: '<p><strong>Stage 3 — Review gate.</strong> The run parks at <code>awaiting_review</code> with the labelled sheet. Approve → captions + LoRA training; reject → nothing trains.</p><ul><li><code>POST /api/internal/creature/&lt;id&gt;/approve</code></li><li><code>POST /api/internal/creature/&lt;id&gt;/reject</code></li></ul>',
            llms:  ['—'],
            tools: ['bp_pipeline_api.api_internal_creature_approve()'],
          }},
      ]},
      { id: 'lora', name: 'LoRA Training', cards: [
        { prompt: 'Caption Generation', agent: 'creature_sheet_service.training_tiles()',
          meta: {
            description: '<p><strong>Stage 4a — Only PASSING cells + the references become training tiles, captioned with the trigger token <code>ZYG_CREATURE_XXXXXX</code>, the brief and the viewpoint.</strong></p>',
            llms:  ['—'],
            tools: ['creature_sheet_service.training_tiles()'],
          }},
        { prompt: 'LoRA Training', agent: 'SimpleTuner (klein-4b, bf16)',
          meta: {
            description: '<p><strong>Stage 4b — FLUX.2 klein-4B LoRA (Apache-2.0 base).</strong></p><ul><li>Output: <code>lora-outputs/creatures/&lt;id&gt;/lora-weights-klein/</code></li><li>FLUX.1-dev is refused by the licence gate; <code>ZYG_CREATURE_TRAIN_FAMILY</code> selects klein | qwen | sdxl</li></ul>',
            llms:  ['FLUX.2 klein-base-4B (SimpleTuner flux2)'],
            tools: ['lora_trainer_service.py', 'SimpleTuner train.py'],
          }},
        { prompt: 'Preview Render', agent: 'klein + trained LoRA → judged',
          meta: {
            description: '<p><strong>Stage 5 — Three LoRA renders, each judged against the anchor (same strip judge + DINOv2) so the LoRA is measured, not eyeballed.</strong></p>',
            llms:  ['FLUX.2 klein-4B + creature LoRA', 'Qwen3-VL judge'],
            tools: ['creature_training_service._render_previews()'],
          }},
      ]},
    ],
  }, // end creature_creation

  /* ══════════════════════════════════════════════════════════════════════════
     TEMPLATES PIPELINE — prompt registry authoring, visual style templates,
     pipeline configuration templates, and TTS narration voice templates.
  ══════════════════════════════════════════════════════════════════════════ */
  templates: {
    name: 'Templates',
    label: '[ TEMPLATES PIPELINE ]',
    columns: [

      /* ── Intake ── */
      { id: 'intake', name: 'Intake', cards: [

        { prompt: 'Template Request Parsing', agent: 'Claude claude-sonnet-4-6',
          meta: {
            description: '<p><strong>Stage 1a — Parses the operator\'s template request into a structured brief.</strong></p><ul><li>Determines template type: prompt / pipeline config / visual style / TTS narration / LoRA trigger</li><li>Identifies target pipeline: documentary / video / manga / storyteller / character_creation / creature_creation</li><li>Extracts required dynamic slots (e.g. <code>{topic}</code>, <code>{tone}</code>, <code>{visual_style}</code>) and static boilerplate</li><li>Output JSON: <code>{ type, target_pipeline, slots[], base_text, category }</code></li></ul>',
            llms:  ['claude-sonnet-4-6 (Anthropic)'],
            tools: ['Anthropic Messages API', 'prompt_registry.py (register_prompt)', 'JSON brief parser'],
          }},

        { prompt: 'Category & Pipeline Routing', agent: 'crewai_web_gui.py',
          meta: {
            description: '<p><strong>Stage 1b — Routes the brief to the correct authoring sub-flow.</strong></p><ul><li><strong>Prompt template</strong> → Design → Text Validation → Registry</li><li><strong>Visual style template</strong> → Design → FLUX visual test → Registry</li><li><strong>TTS narration template</strong> → Design → IndexTTS-2 dry run → Registry</li><li><strong>Pipeline config template</strong> → Design → Config schema validation → Registry</li><li>Sets <code>template_route</code> field consumed by downstream stages</li></ul>',
            llms:  ['—'],
            tools: ['crewai_web_gui.py (routing logic)', 'prompt_registry.py'],
          }},

      ]},

      /* ── Design ── */
      { id: 'design', name: 'Design', cards: [

        { prompt: 'Prompt Scaffolding', agent: 'Claude claude-sonnet-4-6',
          meta: {
            description: '<p><strong>Stage 2a — Writes the base template text with all dynamic slots in place.</strong></p><ul><li>Uses double-brace syntax for slots: <code>{{topic}}</code>, <code>{{scene_count}}</code>, <code>{{tone}}</code></li><li>Incorporates known good patterns from existing prompt_registry.json entries</li><li>Targets the specific model family in use (FLUX / SDXL / Qwen / IndexTTS-2)</li><li>Includes negative prompt block for visual templates</li></ul>',
            llms:  ['claude-sonnet-4-6 (Anthropic)'],
            tools: ['Anthropic Messages API', 'data/runtime/prompt_registry.json (reference)'],
          }},

        { prompt: 'Variable Extraction & Schema', agent: 'Claude claude-sonnet-4-6',
          meta: {
            description: '<p><strong>Stage 2b — Extracts all slots and builds the JSON schema for runtime injection.</strong></p><ul><li>Produces <code>slots: [{ name, type, required, default, description }]</code></li><li>Validates that every <code>{{slot}}</code> in the template text has a corresponding schema entry</li><li>Marks slots as required / optional with safe defaults</li><li>Schema stored alongside template in prompt_registry.json for UI form generation</li></ul>',
            llms:  ['claude-sonnet-4-6 (Anthropic)'],
            tools: ['Anthropic Messages API', 'JSON schema validator'],
          }},

        { prompt: 'Pipeline Config Template (if type=config)', agent: 'crewai_web_gui.py',
          meta: {
            description: '<p><strong>Stage 2c (config-type only) — Generates the pipeline configuration JSON skeleton.</strong></p><ul><li>Mirrors the structure of existing pipeline state files (<code>data/runtime/*_state.json</code>)</li><li>Pre-fills safe defaults for all optional fields</li><li>Adds comments (stored as <code>_comment</code> keys) for operator guidance</li><li>Validated against the active pipeline\'s config schema before proceeding</li></ul>',
            llms:  ['—'],
            tools: ['crewai_web_gui.py', 'data/runtime/ (state file references)'],
          }},

      ]},

      /* ── Validation ── */
      { id: 'validation', name: 'Validation', cards: [

        { prompt: 'Text Generation Dry Run', agent: 'Claude claude-sonnet-4-6',
          meta: {
            description: '<p><strong>Stage 3a — Tests the prompt template end-to-end with synthetic slot values.</strong></p><ul><li>Substitutes all slots with realistic test values</li><li>Runs the completed prompt through Claude and checks structural validity of the output</li><li>Verifies JSON output parses correctly (for brief-type templates)</li><li>Verifies narrative coherence (for narration/scripting templates)</li><li>Fails if output length, JSON keys, or tone diverges from target spec</li></ul>',
            llms:  ['claude-sonnet-4-6 (Anthropic)'],
            tools: ['Anthropic Messages API', 'JSON schema validator'],
          }},

        { prompt: 'Visual Test Render (if type=visual)', agent: 'FLUX.1-schnell / ComfyUI',
          meta: {
            description: '<p><strong>Stage 3b (visual-type only) — Generates a test image to verify the prompt template\'s visual output.</strong></p><ul><li>Substitutes template slots with canonical test values and sends to FLUX.1-schnell via ComfyUI</li><li>Anatomy QA scorer checks the output (<code>_score_anatomy()</code>); threshold 0.65</li><li>Seed locked at 42 for reproducibility across template iterations</li><li>Preview image saved to <code>data/runtime/template_preview_&lt;id&gt;.png</code></li></ul>',
            llms:  ['FLUX.1-schnell (Black Forest Labs, local)'],
            tools: ['comfy_generation_service.generate_still()', 'FLUX anatomy QA scorer', 'ComfyUI /prompt endpoint'],
          }},

        { prompt: 'TTS Dry Run (if type=tts)', agent: 'IndexTTS-2',
          meta: {
            description: '<p><strong>Stage 3c (TTS-type only) — Renders a short sample from the narration template to verify voice and pacing.</strong></p><ul><li>Substitutes test narration text into the template and synthesises it exactly as a pipeline would</li><li>Cloned through the seed-pool reference WAV that the target voice id resolves to; there is no markup layer, so what gets validated is the narration <em>text</em> — emotion is inferred from it automatically</li><li>Checks the pause map lands as designed (420 ms between sentences, 520 ms after ? or !, 800 ms at a paragraph break) and that the assembled sample normalises to −16 LUFS</li><li>Sample MP3 saved for operator review before registration</li></ul>',
            llms:  ['—'],
            tools: ['tts_service (_tts_split_sentences, _tts_assemble)', 'IndexTTS-2 subprocess worker', 'Chatterbox fallback worker'],
          }},

        { prompt: 'Output QA Score', agent: 'crewai_web_gui.py',
          meta: {
            description: '<p><strong>Stage 3d — Aggregates validation results into a pass/fail QA score.</strong></p><ul><li>Text templates: checks output length, JSON validity, tone alignment → score 0–100</li><li>Visual templates: anatomy QA score ≥ 0.65 + style alignment check</li><li>TTS narration templates: render success + duration within target range</li><li>Score < 70 triggers automatic Refinement stage; score ≥ 70 proceeds to Registry</li></ul>',
            llms:  ['—'],
            tools: ['crewai_web_gui.py (qa_score logic)', 'anatomy QA scorer'],
          }},

      ]},

      /* ── Refinement ── */
      { id: 'refinement', name: 'Refinement', cards: [

        { prompt: 'Iterative Prompt Tuning', agent: 'Claude claude-sonnet-4-6',
          meta: {
            description: '<p><strong>Stage 4a — Claude analyses the QA failure and rewrites the template.</strong></p><ul><li>Receives the full QA report: what failed, expected vs actual output</li><li>Applies targeted edits — structural fixes, slot expansion, tone correction, negative prompt tuning</li><li>Up to 3 auto-retry cycles before escalating to operator review</li><li>Each revision tagged with a new version ID for audit trail in prompt_registry.json</li></ul>',
            llms:  ['claude-sonnet-4-6 (Anthropic)'],
            tools: ['Anthropic Messages API', 'prompt_registry.py (register_prompt with parent_id)'],
          }},

        { prompt: 'LoRA Trigger Alignment (visual templates)', agent: 'Qwen-Image-2512 + LoRA',
          meta: {
            description: '<p><strong>Stage 4b — Verifies that visual templates correctly activate the target LoRA.</strong></p><ul><li>Checks that the trigger token (e.g. <code>ZYG_CHAR_ABC123</code>) is present in the positive prompt</li><li>Runs a side-by-side render: with and without the trigger token at LoRA scale 0.75 — qwen family (<code>qwen_character_locked</code> workflow); flux-family renders are refused while FLUX is paused, and FLUX.1-dev-trained LoRAs stay NC derivatives on any unet</li><li>Compares visual difference score — trigger must produce measurable style shift</li><li>Skipped when template does not reference a character or creature LoRA</li></ul>',
            llms:  ['Qwen-Image-2512 (Apache-2.0, local)'],
            tools: ['comfy_generation_service.generate_still()', 'LoRA weight loader', 'CUDA VRAM manager'],
          }},

        { prompt: 'Pause & Pacing Fix (TTS templates)', agent: 'IndexTTS-2',
          meta: {
            description: '<p><strong>Stage 4c — Fixes pacing and phrasing in narration voice templates.</strong></p><ul><li>Analyses the sample audio for unnatural pauses, wrong emphasis, or clipped words</li><li>There are no prosody tags to adjust: the engine takes both pacing and emotion straight from the text, so the fix is editing the narration wording and punctuation plus the pause map — 420 ms between sentences, 520 ms after ? or !, 800 ms at a paragraph break</li><li>Re-renders until duration matches ±5% of the reference narration target</li></ul>',
            llms:  ['—'],
            tools: ['tts_service (_tts_split_sentences pause map)', 'IndexTTS-2 subprocess worker', 'Whisper word-timing backfill'],
          }},

      ]},

      /* ── Registry ── */
      { id: 'registry', name: 'Registry', cards: [

        { prompt: 'Version Registration', agent: 'prompt_registry.py',
          meta: {
            description: '<p><strong>Stage 5a — Commits the validated template to prompt_registry.json with full metadata.</strong></p><ul><li>Assigns a unique <code>id</code> (UUID) and increments the version counter</li><li>Sets <code>parent_id</code> chain for version history traceability</li><li>Stores: template text, slot schema, category, target_pipeline, author, created_at, qa_score</li><li>Previous active version automatically marked <code>active: false</code> — retained for rollback</li></ul>',
            llms:  ['—'],
            tools: ['prompt_registry.py (register_prompt)', 'data/runtime/prompt_registry.json'],
          }},

        { prompt: 'Category Tagging & Search Indexing', agent: 'crewai_web_gui.py',
          meta: {
            description: '<p><strong>Stage 5b — Tags the template for discovery and indexes it for the Prompts tab search.</strong></p><ul><li>Assigns: <code>category</code> (narration / visual / config / tts / lora), <code>pipeline</code> (documentary / video / …), <code>tags[]</code></li><li>Updates the in-memory prompt index served by <code>/api/asset_manager/prompts</code></li><li>Template immediately searchable and filterable in the Asset Manager → Prompts tab</li></ul>',
            llms:  ['—'],
            tools: ['crewai_web_gui.py (/api/asset_manager/prompts)', 'data/runtime/prompt_registry.json'],
          }},

        { prompt: 'Activation & Pipeline Injection', agent: 'crewai_web_gui.py',
          meta: {
            description: '<p><strong>Stage 5c — Marks the template active and makes it available to live pipeline runs.</strong></p><ul><li>Sets <code>active: true</code> in prompt_registry.json</li><li>Live pipelines query the registry at runtime — no restart required</li><li>Operator can force-activate a specific version via <code>POST /api/prompt_registry/update</code></li><li>Rollback available via <code>POST /api/prompt_registry/revert</code> — reverts to previous <code>parent_id</code></li></ul>',
            llms:  ['—'],
            tools: ['crewai_web_gui.py (/api/prompt_registry/update)', '/api/prompt_registry/revert', 'prompt_registry.py'],
          }},

      ]},

    ],
  }, // end templates

}; // end TEMPLATES

// ── Medusa board (2026-07-26) ─────────────────────────────────────────────────
// Dedicated adult-women swimwear workflow. Injected as its own key via an IIFE
// (leaves the big TEMPLATES literal untouched) BEFORE the SDXL clone below, so it
// appears in both family views. Card `prompt` titles MUST match bp_medusa._CARD_ORDER.
(function _addMedusaTemplate(T) {
  T.medusa = {
    name: 'Medusa',
    label: '[ MEDUSA — SWIMWEAR CHARACTER ]',
    columns: [
      { id: 'request', name: 'Request', cards: [
        { prompt: 'Swimwear Character Request', agent: 'medusa (:5300)',
          meta: { description: '<p>Adult-women swimwear character request, approved from the Medusa operator queue. Women only, 18+, catalog-clean swimwear.</p>', llms: ['—'], tools: ['bp_medusa.py', 'medusa_server.py (:5300)'] }},
      ]},
      { id: 'sheet', name: '48-Angle Sheet', cards: [
        { prompt: 'Per-Cell Contact Sheet', agent: 'contact_sheet_pipeline.py',
          meta: { description: '<p>Full 48-angle per-cell contact sheet — anchor on Qwen-Image-2512 while FLUX.1-dev is licence-paused (Qwen-edit + IP-Adapter identity lock) — reused verbatim from the stock pipeline, with a thread-local swimwear-clean negative.</p>', llms: ['—'], tools: ['contact_sheet_pipeline.py', 'comfy_generation_service.py'] }},
      ]},
      { id: 'qc', name: 'Identity QC', cards: [
        { prompt: 'Tile Crop + Identity QC', agent: 'identity_qc_service.py',
          meta: { description: '<p>Tiles cropped from the approved sheet and identity-QC filtered before training.</p>', llms: ['—'], tools: ['identity_qc_service.py'] }},
      ]},
      { id: 'captions', name: 'Captions', cards: [
        { prompt: 'Caption Training Set', agent: 'contact_sheet_pipeline.py',
          meta: { description: '<p>Trigger-first captions written beside each kept tile in the training/ dataset dir.</p>', llms: ['—'], tools: ['contact_sheet_pipeline.py'] }},
      ]},
      { id: 'training', name: 'LoRA Training', cards: [
        { prompt: 'FLUX LoRA Training', agent: 'lora_trainer_service.py',
          meta: { description: '<p>FLUX LoRA trained on the swimwear dataset via SimpleTuner.</p>', llms: ['—'], tools: ['lora_trainer_service.py', 'SimpleTuner'] }},
      ]},
      { id: 'refine', name: 'Flywheel Refine', cards: [
        { prompt: 'Angle Expansion + LoRA v2', agent: 'lora_trainer_service.py',
          meta: { description: '<p>Angle-expansion flywheel + LoRA v2 refine.</p>', llms: ['—'], tools: ['lora_trainer_service.py'] }},
      ]},
      { id: 'done', name: 'Ready', cards: [
        { prompt: 'Character Ready', agent: 'character_bible_service.py',
          meta: { description: '<p>Character bible updated with the trained LoRA path; ready for use.</p>', llms: ['—'], tools: ['character_bible_service.py'] }},
      ]},
    ],
  };
})(TEMPLATES);

// The Medusa Training board was removed from the Workflows list on 2026-09-17
// at the operator's request. Nothing was retired behind it: photo preparation
// still runs in the Medusa app itself (:5300, Training tab -> bp_medusa_training.py),
// which is where its live progress was always shown. This board only ever
// described that workflow, and a ?view=medusa_training deep link now falls back
// to the default board because the key no longer exists in TEMPLATES.

// ── Environments board (2026-07-28): scenery generation, 2D still + 3D camera-move. ──
(function _addEnvironmentsTemplate(T) {
  T.environments = {
    name: 'Environments',
    label: '[ ENVIRONMENTS — SCENERY ]',
    columns: [
      { id: 'brief', name: 'Brief', cards: [
        { prompt: 'Environment Brief', agent: '3D-Environment-Agent',
          meta: { description: '<p>Turn a directive into an environment spec (biome, era, time-of-day, camera). The <b>2D/3D toggle</b> beside the model selector picks a still scenery plate (2D) vs a camera-move video (3D).</p>', llms: ['Claude'], tools: ['pipeline_environments.py'] }},
      ]},
      { id: 'gen2d', name: '2D Scenery', cards: [
        { prompt: '2D Scenery Plate', agent: '2D-Compositor-Agent',
          meta: { description: '<p>Wide establishing environment still (SDXL, optional arcane restyle) — for still pipelines.</p>', llms: ['—'], tools: ['pipeline_environments.generate_scenery_2d'] }},
      ]},
      { id: 'gen3d', name: '3D Scenery', cards: [
        { prompt: '3D Camera-Move Clip', agent: '3D-Environment-Agent',
          meta: { description: '<p>Animate the plate through Wan I2V as a camera move through the scenery — for video pipelines. ~5s preview via test mode.</p>', llms: ['—'], tools: ['pipeline_environments.generate_scenery_3d', 'wan_video_service'] }},
      ]},
      { id: 'composite', name: 'Composite', cards: [
        { prompt: 'Character Composite', agent: '2D-Compositor-Agent',
          meta: { description: '<p>Optionally composite trained-LoRA characters into the environment (arcane_multichar / face-pass).</p>', llms: ['—'], tools: ['arcane_multichar.py'] }},
      ]},
      { id: 'deliver', name: 'Deliver', cards: [
        { prompt: 'Grade & Deliver', agent: '2D-Compositor-Agent',
          meta: { description: '<p>Color-grade and output to output/environments/.</p>', llms: ['—'], tools: ['pipeline_effects.apply_effect_2d'] }},
      ]},
    ],
  };
})(TEMPLATES);

// ── Effects board (2026-07-28): VFX, 2D compositing + 3D motion FX. ──
(function _addEffectsTemplate(T) {
  T.effects = {
    name: 'Effects',
    label: '[ EFFECTS — VFX ]',
    columns: [
      { id: 'brief', name: 'Brief', cards: [
        { prompt: 'Effect Brief', agent: '3D-Effects-Agent',
          meta: { description: '<p>Which FX (atmosphere / optical / particle / motion). The <b>2D/3D toggle</b> picks a still compositing pass (2D) vs a motion-FX clip (3D).</p>', llms: ['Claude'], tools: ['pipeline_effects.py'] }},
      ]},
      { id: 'fx2d', name: '2D FX', cards: [
        { prompt: '2D FX Layer', agent: '2D-Effects-Agent',
          meta: { description: '<p>Post-render compositing FX on a still (bloom / godrays / vignette / grain / grade). Identity-safe, no GPU — runs after the face is locked.</p>', llms: ['—'], tools: ['pipeline_effects.apply_effect_2d'] }},
      ]},
      { id: 'fx3d', name: '3D FX', cards: [
        { prompt: '3D Motion FX Clip', agent: '3D-Effects-Agent',
          meta: { description: '<p>Bake motion FX (embers, rain, smoke, magic) into a short clip via Wan I2V. ~5s preview via test mode.</p>', llms: ['—'], tools: ['pipeline_effects.generate_effect_3d', 'wan_video_service'] }},
      ]},
      { id: 'blend', name: 'Composite', cards: [
        { prompt: 'Composite / Blend', agent: '3D-Compositor-Agent',
          meta: { description: '<p>Blend the FX layer over the source plate/clip.</p>', llms: ['—'], tools: ['object_track_service.py'] }},
      ]},
      { id: 'deliver', name: 'Deliver', cards: [
        { prompt: 'Grade & Deliver', agent: '3D-Compositor-Agent',
          meta: { description: '<p>Final grade and output to output/effects/.</p>', llms: ['—'], tools: ['—'] }},
      ]},
    ],
  };
})(TEMPLATES);

// ── Wardrobe board (2026-07-28): apply a shared-library outfit to any character, no retrain. ──
(function _addWardrobeTemplate(T) {
  T.wardrobe = {
    name: 'Wardrobe',
    label: '[ WARDROBE — OUTFITS ]',
    columns: [
      { id: 'brief', name: 'Brief', cards: [
        { prompt: 'Wardrobe Brief', agent: '2D-Compositor-Agent',
          meta: { description: '<p>Pick a character + an outfit from the <b>shared wardrobe library</b> (Asset Manager → Wardrobe). Applies to any trained-LoRA character with NO retrain.</p>', llms: ['Claude'], tools: ['wardrobe_service.py'] }},
      ]},
      { id: 'apply', name: 'Apply Outfit', cards: [
        { prompt: 'Apply Outfit', agent: '2D-Compositor-Agent',
          meta: { description: '<p>Qwen-Image-Edit changes ONLY the clothing to the chosen outfit; face, hair, body, pose, background and art-style are preserved. Reuses the existing qwen-edit engine.</p>', llms: ['—'], tools: ['wardrobe_service.change_outfit', 'qwen-image-edit'] }},
      ]},
      { id: 'deliver', name: 'Deliver', cards: [
        { prompt: 'Deliver', agent: '2D-Compositor-Agent',
          meta: { description: '<p>Identity QC then output to output/wardrobe/.</p>', llms: ['—'], tools: ['identity_qc_service.py'] }},
      ]},
    ],
  };
})(TEMPLATES);

// ── Children's Music board (2026-08-29): sound-only songwriting workflow. ──
// Card `prompt` titles MUST equal the stage strings pipeline_kidsmusic._set_stage
// emits (pipeline_kidsmusic.STAGES) — a card title no stage ever matches sits at
// 'queued' for the whole run, which is exactly how the Second Ledger board once
// looked permanently stalled.
(function _addKidsMusicTemplate(T) {
  T.kidsmusic = {
    name: "Melodies \u00b7 Children's Music",
    label: "[ MELODIES \u203a CHILDREN'S MUSIC \u2014 LIVE COMPOSER ]",
    columns: [
      { id: 'brief', name: 'Brief', cards: [
        { prompt: 'Song Brief', agent: 'kids_music_theory.py',
          meta: { description: "<p><strong>Turns the request into a musically coherent brief.</strong></p><ul><li>Age band decides the singable range, the largest allowed leap, how much syncopation is on the table and the note-density ceiling — toddler C4–C5, preschool C4–D5, early school B3–F5</li><li>Mood decides the mode, metre, tempo window and the General-MIDI instrument set</li><li>Anything the operator states explicitly overrides both; anything left blank gets a default that cannot contradict the band</li></ul>",
                 llms: ['—'], tools: ['kids_music_theory._normalise_brief'] }},
        { prompt: 'Lyrics', agent: 'ollama qwen3.5:9b',
          meta: { description: "<p><strong>Writes the lyric to a syllable budget, before the tune exists.</strong></p><ul><li>The budget comes from the age band (toddler 4–7 syllables a line, early school 6–11) and it is what the rhythm search is later fitted to — lyrics first, rhythm second, so words land on beats instead of being squeezed onto them</li><li>One line per two bars, two lines per four-bar section</li><li>A banned-word filter drops anything frightening; a template lyric fills in when the model is down, so a song is never blocked on an LLM</li><li>Skipped entirely for an instrumental</li></ul>",
                 llms: ['qwen3.5:9b (local, think:false)'], tools: ['kids_music_service.write_lyrics'] }},
      ]},
      { id: 'compose', name: 'Compose', cards: [
        { prompt: 'Compose & Score', agent: 'kids_music_theory.py',
          meta: { description: "<p><strong>The melody is CONSTRUCTED under constraints, then measured — not sampled and hoped for.</strong></p><ul><li>Rhythm comes from a written-out vocabulary of bar cells filtered per band (eighths only in pairs on a beat; no syncopation below early school)</li><li>Pitch is chosen as a scale INDEX, so ±1 is literally a step: stepwise motion is the cheapest move in the search rather than something checked afterwards</li><li>Hard rules: inside the tessitura, never a tritone, never a leap past the band cap, no fifth repeat of one pitch</li><li>Soft rules, sampled by weight: chord tone on every strong beat, a leap answered by a step the other way, an arch contour, one clear high point</li><li>A motif is generated once per section letter and recalled (transposed to join legally) so an A section really repeats — that is what makes a song learnable</li><li>The last bar comes home: tonic note, tonic chord, held</li><li>Twelve measured metrics → a weighted score. Roughly 48 seeds are composed and the best kept; any hard failure vetoes the candidate outright</li></ul>",
                 llms: ['—'], tools: ['kids_music_theory.compose_best', 'kids_music_theory.score_plan'] }},
      ]},
      { id: 'render', name: 'Render', cards: [
        { prompt: 'Score Render', agent: 'libfluidsynth + MuseScore_General.sf3',
          meta: { description: "<p><strong>The composed arrangement, played exactly as written.</strong></p><ul><li>Four-track MIDI (melody / chords / bass / nursery percussion) written with mido, then rendered offline through libfluidsynth</li><li>SoundFont is MuseScore_General.sf3, <b>MIT</b> — the system default TimGM6mb.sf2 is GPL-2 and is deliberately NOT used, because a SoundFont's samples end up in published audio</li><li>CPU-only and deterministic: this leg needs no GPU, so a song still ships while ComfyUI is busy with a video render</li></ul>",
                 llms: ['—'], tools: ['kids_music_service.write_midi', 'kids_music_service.render_soundfont'] }},
        { prompt: 'Measure Score Render', agent: 'librosa + ffmpeg',
          meta: { description: "<p><strong>Does the audio actually match the score?</strong></p><ul><li>Tempo by beat tracking (half- and double-time accepted as the octave errors they are, and reported as such)</li><li>Key by chroma against the Krumhansl-Kessler profiles</li><li>Integrated LUFS, sample peak, duration</li></ul>",
                 llms: ['—'], tools: ['kids_music_service.gate_audio'] }},
      ]},
      { id: 'produce', name: 'Produce', cards: [
        { prompt: 'Produced Track (ACE-Step)', agent: 'ACE-Step 1.5 (ComfyUI)',
          meta: { description: "<p><strong>The full production, conditioned on the same plan.</strong></p><ul><li>Its own workflow template (<code>ace_step_kidsong.json</code>) so <code>ace_step_service.py</code> and the documentary/storyteller beds stay untouched — the difference is that this one passes lyrics, bpm, keyscale and time signature through instead of hard-coding an instrumental bed</li><li>Same tempo, metre and key the score already fixed, so the two legs are one song rather than two songs about one topic</li><li>Best effort: a failed or unavailable generation is recorded and the run continues</li></ul>",
                 llms: ['—'], tools: ['_comfy_client.submit', 'ace_step_kidsong.json'] }},
        { prompt: 'Measure Produced Track', agent: 'librosa + CLAP',
          meta: { description: "<p><strong>A generative model is free to ignore what it was told; this is how we find out whether it did.</strong></p><ul><li>Same tempo / key / loudness measurements as the score render, compared against the plan</li><li>A key correlation under 0.60 is reported as <em>undetermined</em>, never as drift — below that the template is picking the least-bad of twenty-four poor fits</li><li>CLAP semantic check: does this sound like a cheerful children's song, or like something else?</li></ul>",
                 llms: ['—'], tools: ['kids_music_service.gate_audio', 'audio_qc.qc_clap'] }},
      ]},
      { id: 'deliver', name: 'Deliver', cards: [
        { prompt: 'Master & Deliver', agent: 'audio_mix.py',
          meta: { description: "<p><strong>−14 LUFS / −1 dBTP, and a manifest that says which leg shipped and why.</strong></p><ul><li>Gain and a limiter run BEFORE loudnorm: a sparse nursery arrangement lands near −24 LUFS, and asking loudnorm for +10 dB makes ffmpeg fall back to dynamic AGC and reshape the dynamics — measured on this workflow's first run</li><li>The produced track ships when it passes its hard gates; otherwise the score render does. A run always delivers something</li><li>Written to output/kidsmusic/&lt;job&gt;/ with the MIDI, the plan, the piano roll, the lyric and the licence note</li></ul>",
                 llms: ['—'], tools: ['kids_music_service.prelevel', 'audio_mix.master'] }},
      ]},
      { id: 'pictures', name: 'Pictures', cards: [
        { prompt: 'Storyboard', agent: 'kids_video_service.py',
          meta: { description: "<p><strong>Two pictures for every five seconds, laid out on the song's own beat grid.</strong></p><ul><li>The rate is enforced by construction — no picture may hold longer than 2.45 s, so every rolling five-second window contains at least two — and then measured anyway as the WORST window, because an average cannot see a ten-second still</li><li>Slot length is the largest musical unit that fits under that ceiling (one bar at 117 bpm, a half bar at 60), and boundaries snap to beats measured from the delivered audio with librosa</li><li>Pace follows the music: a chorus, or any section whose measured RMS is in the top third, runs at double rate; roughly one bar per 20 s becomes a BURST of one picture per beat</li><li>What each picture shows comes from the lyric first and from a motif deck second — counting runs, shape and colour parades, a toy box, an animal parade, weather, dancing, a seed growing. The counting motifs are placed on the bursts, so the number advances with the beat</li></ul>",
                 llms: ['qwen3.5:9b (local, think:false)'], tools: ['kids_video_service.plan_slots', 'kids_video_service.assign_ideas', 'librosa.beat'] }},
        { prompt: 'Illustrate', agent: 'HiDream-O1 8B (ComfyUI :8189) · klein fallback',
          meta: { description: "<p><strong>One flat cartoon picture per slot — never photorealistic.</strong></p><ul><li>klein 4B is the only image family here, and the reason is licensing: DynaVision XL and Juggernaut both classify UNKNOWN in the registry (unread Civitai permission flags) and this channel is monetised, while klein's Apache-2.0 grant is on the BFL repo itself</li><li>One style sentence is prefixed to every prompt in a song, so thirty pictures read as one film</li><li>Keeping the models resident is the whole cost story: 63.8 s an image with the default per-slot VRAM release, 15.6 s with the weights held — measured on this box</li><li>When ComfyUI is down every slot still gets a picture: a flat cartoon card drawn with PIL. The manifest says how many frames were drawn rather than generated</li></ul>",
                 llms: ['—'], tools: ['comfy_generation_service.generate_still', 'klein_txt2img.json', 'kids_video_service._draw_card'] }},
        { prompt: 'Measure Frames', agent: 'open_clip + RapidOCR',
          meta: { description: "<p><strong>Cartoon, joyful, and free of lettering — measured, not asserted.</strong></p><ul><li>CLIP as a CONTRAST between competing captions, not a bare similarity: a raw 0.31 means nothing, but \"which of these does this picture look more like\" does</li><li>Calibrated against a null — the photoreal stills already on this box score 0.0007–0.34 on the cartoon contrast while klein cartoon renders score 0.925–0.986, so the 0.75 threshold sits in the empty space between them</li><li>A measurement that could not run reports <em>null</em>, never <em>fail</em>: 'did not look' and 'looked and refused' are different verdicts</li><li>OCR from 0.4 % of frame up, because line art reads as stray glyphs below that</li></ul>",
                 llms: ['—'], tools: ['kids_video_service.gate_frames', 'typography_ocr.read_lettering'] }},
        { prompt: 'Animate', agent: 'LTX-2.5 22B distilled (ComfyUI :8189)',
          meta: { description: "<p><strong>Every picture becomes a short motion clip — the channel ships no stills.</strong></p><ul><li>Each frame (generated or drawn) is the first frame of an LTX-2.5 image-to-video run: two-stage, 8 distilled steps, about 15 s for a 3 s clip measured on this box; the clip is cut to its slot plus the xfade that follows it</li><li>The motion prompt keeps the flat cartoon style and forbids adding or removing anything, so a counting card still counts; the camera stays still so cuts keep landing on the beat</li><li>A clip that fails is retried once with a new seed; a slot that still has none ships as a still with a Ken Burns move and the manifest reports <code>kenburns &gt; 0</code> — the contract is motion_coverage 1.0, never hidden</li><li>Both ComfyUI servers share the GPU under one submit lock: the production weights are evicted before the leg and the 40 GB LTX residency is unloaded after it</li></ul>",
                 llms: ['—'], tools: ['kids_video_service.animate_frames', 'ltx_hidream_service.ltx_i2v', 'ltx25_i2v.json'] }},
        { prompt: 'Assemble Video', agent: 'PIL + ffmpeg xfade',
          meta: { description: "<p><strong>Gentle motion, smooth joins, and a length that lands exactly on the song.</strong></p><ul><li>There is no hard cut in the vocabulary at all — every join is an xfade, sized to the pace: 0.45 s between held pictures, 0.14 s inside a burst, a playful wipe on a section change. <code>fadeblack</code> is absent on purpose</li><li>Each picture gets a gentle Ken Burns move plus a 1.5 % zoom pulse on the bar downbeat, so a still picture breathes with the music</li><li>xfade OVERLAPS its inputs, so each clip is encoded at its slot length PLUS the transition that follows it — without that compensation the video finishes short of the song by the sum of every transition</li><li>Muxed with the delivered master, video stream copied</li></ul>",
                 llms: ['—'], tools: ['kids_video_service.build_video', 'ffmpeg xfade'] }},
      ]},
    ],
  };
})(TEMPLATES);

// ── 2D Character Basics blueprints (2026-09-16) ──────────────────────────────
// Four Blueprints menu entries. 'I' is the only designed board; II/III/IV are
// EMPTY placeholders (no columns) so the menu entry resolves to its own board
// instead of silently falling back to Documentary in _buildFromTemplate.
// Card `prompt` strings are JOIN KEYS with pipeline_char2d.STAGES — a title the
// runner never emits sits at 'queued' for the whole run, which is exactly how
// the Second Ledger board once looked permanently stalled. Byte-exact only.
// MUST be registered before TEMPLATES_SDXL clones TEMPLATES, or the SDXL family
// (the default view) would not have these keys at all.
(function _addChar2dTemplates(T) {
  T.char2d_basics_1 = {
    name: '2D Character Basics I',
    label: '[ 2D CHARACTER BASICS I ]',
    blueprint: true,
    columns: [
      { id: 'brief', name: 'Brief', cards: [
        { prompt: 'Character Brief', agent: 'char2d_service.py',
          meta: { description: '<p><strong>One typed sentence becomes the brief JSON every later stage reads.</strong></p><ul><li>Fields: name, gender (0.0 female \u2026 1.0 male, the MPFB macro axis), age in years, height in metres</li><li>Four colours as RGB: skin, hair, top, bottom \u2014 the top/bottom pair is what the tights helper is painted with</li><li>Hair cut is one of <code>bob</code> | <code>short</code> | <code>long</code>; the cut decides where the hair hull is trimmed, not which mesh is used</li><li>Anything the operator leaves out gets a default that cannot contradict the body macro</li></ul>',
                 llms: ['\u2014'], tools: ['char2d_service.py'] }},
      ]},
      { id: 'model', name: 'Model', cards: [
        { prompt: 'MPFB Body Build', agent: 'blender_scripts/char2d_build.py',
          meta: { description: '<p><strong>A real posable body, not a drawing \u2014 MPFB 2.0.17 on the CC0 basemesh.</strong></p><ul><li><code>HumanService.create_human(detailed_helpers=True)</code> with the macro dict from the brief (gender / age / height / weight / muscle)</li><li>Rig is the built-in <code>default</code>: 163 bones including jaw, neck01-03, spine01-05 and <b>15 finger bones per hand</b> \u2014 which is what makes hands posable by construction rather than by luck</li><li>The tights helper (2674 verts) is a full body suit incl. feet and neck; it is the clothing, split top/bottom by z</li><li>The hair helper is a long-hair hull that covers the face \u2014 faces are trimmed by z to make the requested cut</li></ul>',
                 llms: ['\u2014'], tools: ['Blender 4.3.2 (--background --python)', 'bl_ext.user_default.mpfb HumanService', 'MPFB TargetService macro dict', 'blender_scripts/char2d_build.py'] }},
        { prompt: 'Cel Shader + Ink Lines', agent: 'Blender EEVEE Next + Freestyle',
          meta: { description: '<p><strong>Two tones and an ink line \u2014 the whole 2D look, done in the renderer.</strong></p><ul><li>Material: Diffuse BSDF \u2192 ShaderToRGB \u2192 ColorRamp (CONSTANT, 2 stops) \u2192 Emission, so light lands as a hard shadow edge instead of a gradient</li><li>Freestyle ink: silhouette + crease + border + contour at 2.5 px, near-black</li><li>The lineset\u2019s linestyle is created explicitly \u2014 in background mode a lineset without one kills the render with <em>NoneType has no attribute use_chaining</em></li><li><code>film_transparent</code> is on: every view ships as RGBA so sprites composite without a matte pass</li></ul>',
                 llms: ['\u2014'], tools: ['Blender EEVEE Next', 'ShaderToRGB + ColorRamp (CONSTANT)', 'Freestyle lineset (silhouette/crease/border/contour)', 'film_transparent'] }},
      ]},
      { id: 'turnaround', name: 'Turnaround', cards: [
        { prompt: 'Six-View Render', agent: 'Blender camera rig (6 yaws)',
          meta: { description: '<p><strong>Six yaws that cover every angle a 2D character is ever drawn from.</strong></p><ul><li>0 front, 45 front three-quarter left, 315 front three-quarter right, 90 left profile, 270 right profile, 180 back</li><li>85 mm lens at 4.5 m, camera height 0.9 m \u2014 long enough that the face keeps its proportions across views</li><li>RGBA PNG 1024\u00d71536 per view, one filename per yaw so downstream stages can join on the view name</li></ul>',
                 llms: ['\u2014'], tools: ['Blender 4.3.2 (headless)', 'blender_scripts/char2d_build.py (camera rig)', 'EEVEE Next'] }},
        { prompt: 'Turnaround Sheet', agent: 'PIL',
          meta: { description: '<p><strong>The six views stitched into one reviewable sheet.</strong></p><ul><li>Single contact sheet with the yaw labelled under each view</li><li>Alpha preserved \u2014 the sheet is a review artefact, the individual PNGs stay the deliverable</li></ul>',
                 llms: ['\u2014'], tools: ['Pillow (PIL)'] }},
      ]},
      { id: 'mouth', name: 'Mouth', cards: [
        { prompt: 'Mouth Anchors', agent: 'bpy_extras.world_to_camera_view',
          meta: { description: '<p><strong>Where the mouth actually is, in every view, measured from the mesh.</strong></p><ul><li>The lip band is the front-most vertices in the z window between the chin and the jaw bone head \u2014 read off the posed body, not guessed from the image</li><li><code>world_to_camera_view(scene, cam, point)</code> projects the band centre into each view\u2019s 2D image space</li><li>Result is one anchor (x, y, scale) per view, which is what makes a sprite land on the mouth at a three-quarter angle instead of in the middle of the cheek</li></ul>',
                 llms: ['\u2014'], tools: ['bpy_extras.object_utils.world_to_camera_view', 'MPFB jaw / chin landmarks'] }},
        { prompt: 'Mouth Sprites', agent: 'PIL',
          meta: { description: '<p><strong>Three anime mouth shapes per view \u2014 closed, mid, open.</strong></p><ul><li>Drawn flat to match the cel look, with the ink weight of the render</li><li>Profile variants for the views where the mouth sits on the face edge (90 / 270), because a front sprite pasted on a profile reads as a floating shape</li><li>Three shapes is the target, not a compromise: it is what 2D animation actually uses, and it is what the timing stage quantises to</li></ul>',
                 llms: ['\u2014'], tools: ['Pillow (PIL)'] }},
        { prompt: 'Lip-Sync Timing (Rhubarb)', agent: 'Rhubarb Lip Sync 1.14.0 (MIT)',
          meta: { description: '<p><strong>Audio \u2192 mouth shapes, then deliberately made coarser.</strong></p><ul><li>Rhubarb emits shapes A\u2013H plus X; those nine are collapsed onto the three sprites that exist</li><li>Holds are quantised to a minimum of <b>6 frames at 24 fps</b>, so no more than about four mouth changes a second \u2014 above that a 2D mouth flickers instead of talks</li><li>MIT-licensed and local: no audio leaves the box for the timing pass</li></ul>',
                 llms: ['\u2014'], tools: ['Rhubarb Lip Sync 1.14.0 (MIT)', 'shape collapse A-H,X \u2192 closed/mid/open', '6-frame hold quantiser @ 24 fps'] }},
        { prompt: 'Talking Clip', agent: 'ffmpeg overlay',
          meta: { description: '<p><strong>The proof that the mouth set and the timing agree.</strong></p><ul><li>The chosen view is held while the mouth sprite is overlaid at its anchor, one sprite per quantised hold</li><li>Muxed against the source audio so a drift of even a few frames is visible rather than argued about</li></ul>',
                 llms: ['\u2014'], tools: ['ffmpeg overlay', 'sprite anchors from Mouth Anchors'] }},
      ]},
      { id: 'hands', name: 'Hands', cards: [
        { prompt: 'Gesture Keyframes', agent: 'data/char2d/gestures/*.json',
          meta: { description: '<p><strong>Ten gestures, 2\u20134 keys each, posed on the rig and checked against joint limits.</strong></p><ul><li>Finger curl is a local X rotation on finger1-1\u2026finger5-3; the thumb is finger1 and carries its own CMC/MCP/IP limits</li><li>Range-of-motion validation: MCP 0\u201390\u00b0, PIP 0\u2013110\u00b0, DIP 0\u201380\u00b0, abduction \u00b120\u00b0 \u2014 a key that asks for more is rejected, so a hand cannot bend backwards</li><li>Keys live as JSON in <code>data/char2d/gestures/</code>: the gesture ladder is data, not code, and can be extended without touching the pipeline</li></ul>',
                 llms: ['\u2014'], tools: ['Blender pose bones (rotation_mode XYZ)', 'data/char2d/gestures/*.json', 'joint range-of-motion validator'] }},
        { prompt: 'Hand Anatomy Gate', agent: 'anatomy_qc.qc_hands_frame',
          meta: { description: '<p><strong>Five fingers by construction, and measured anyway.</strong></p><ul><li>The rig has exactly five digits per hand, so the generative failure mode (six fingers, fused fingers) cannot occur \u2014 that is the point of modelling the hand instead of prompting it</li><li>MediaPipe hand landmarker (Apache-2.0) reads the rendered frame back and confirms a hand is legible where one was posed</li><li>A measurement that could not run reports <em>null</em>, never <em>fail</em></li></ul>',
                 llms: ['\u2014'], tools: ['anatomy_qc.qc_hands_frame', 'MediaPipe hand landmarker (Apache-2.0)'] }},
        { prompt: 'Gesture Clips', agent: 'ffmpeg',
          meta: { description: '<p><strong>Each gesture as a short clip, at the pace a 2D hand actually moves.</strong></p><ul><li>Keys are held 6\u201312 frames \u2014 two to four changes a second, the same ceiling the mouth uses</li><li>One clip per gesture, so the ladder can be reviewed as a set rather than as a single reel</li></ul>',
                 llms: ['\u2014'], tools: ['ffmpeg', 'gesture keyframe JSON'] }},
      ]},
      { id: 'deliver', name: 'Deliver', cards: [
        { prompt: 'Sprite Manifest', agent: 'sprites.json',
          meta: { description: '<p><strong>One file that tells a consumer everything the character can do.</strong></p><ul><li>Views (yaw \u2192 PNG), mouth anchors per view, the mouth sets, and the gesture ladders</li><li>Written to the run\u2019s output tree next to the assets it indexes, so the manifest and the files cannot drift apart</li></ul>',
                 llms: ['\u2014'], tools: ['char2d_service.py (manifest writer)'] }},
        { prompt: 'Demo Reel', agent: 'ffmpeg',
          meta: { description: '<p><strong>demo.mp4 \u2014 the talking clip plus all ten gestures, in one pass.</strong></p><ul><li>What ships for review: if the reel is right, the sprite set is right</li><li>Assembled from the clips the earlier stages already proved, so the reel adds no new failure mode of its own</li></ul>',
                 llms: ['\u2014'], tools: ['ffmpeg concat', 'output/char2d/&lt;job&gt;/demo.mp4'] }},
      ]},
    ],
  };
  T.char2d_basics_2 = {
    name: '2D Character Basics II',
    label: '[ 2D CHARACTER BASICS II ]',
    blueprint: true,
    placeholder: true,
    columns: [],
  };
  T.char2d_basics_3 = {
    name: '2D Character Basics III',
    label: '[ 2D CHARACTER BASICS III ]',
    blueprint: true,
    placeholder: true,
    columns: [],
  };
  T.char2d_basics_4 = {
    name: '2D Character Basics IV',
    label: '[ 2D CHARACTER BASICS IV ]',
    blueprint: true,
    placeholder: true,
    columns: [],
  };
})(TEMPLATES);

// ── Remix board (2026-08-05): channel-watch → clip → narrate → split-screen. ──
// Card `prompt` strings are the EXACT join keys with KANBAN_STAGE_MAP['remix']
// in bp_pipeline_api.py — one character of drift leaves a card queued forever.
(function _addRemixTemplate(T) {
  T.remix = {
    name: 'Remix',
    label: '[ REMIX — CLIPS & COMPILATIONS ]',
    columns: [
      { id: 'intake', name: 'Intake', cards: [
        { prompt: 'Watch Channels', agent: 'REMIX-Watcher',
          meta: { description: '<p>RSS-polls the registered YouTube channels (cache-busted UULF feeds, Shorts excluded). Manage the list at <b>/remix</b>. Fresh uploads and last-10-day outliers become candidates.</p>', llms: ['—'], tools: ['remix_ingest.py', 'bp_remix.py'] }},
        { prompt: 'Score Candidates', agent: 'REMIX-Watcher',
          meta: { description: '<p>viewCount snapshots → 10-day windowed views → channel-normalized velocity (outlier ×). Fresh uploads rank first; search.list is never used (~1-2% of API quota).</p>', llms: ['—'], tools: ['videos.list', 'remix_stats.json'] }},
      ]},
      { id: 'fetch', name: 'Fetch', cards: [
        { prompt: 'Download Source', agent: 'REMIX-Fetcher',
          meta: { description: '<p>yt-dlp ≤1080p with cookie + node JS-challenge ladder. FAIL-CLOSED disk gate (≥100 GB free, remix tree ≤ cap). Source is deleted the moment clips are delivered.</p>', llms: ['—'], tools: ['yt-dlp', 'disk gate'] }},
        { prompt: 'Transcribe', agent: 'REMIX-ASR',
          meta: { description: '<p>YouTube captions for content; faster-whisper large-v3 word timestamps when the GPU is free (fail-closed comfy_is_sampling gate — never squeezes a render).</p>', llms: ['—'], tools: ['zyg_whisper.py', 'youtube_transcript_api'] }},
      ]},
      { id: 'cut', name: 'Cut', cards: [
        { prompt: 'Select Moments', agent: 'REMIX-Editor',
          meta: { description: '<p>Fused score/second: detrended Most-Replayed heatmap (0.35) + comment-timestamp density (0.25) + local-LLM transcript read (0.25) + audio RMS (0.15), renormalized when a signal is absent. Windows snap to sentence + silence midpoints, pad 0.6s in / 0.8s out.</p>', llms: ['qwen3.5:9b'], tools: ['heatmap', 'silencedetect'] }},
        { prompt: 'Write Narration', agent: 'REMIX-Narrator',
          meta: { description: '<p>The transformation layer: LLM writes hook + insight(s) + outro (never quoting the source), IndexTTS-2 clones a seed-pool voice and speaks them, content ducks under narration. Coverage is measured against the operator floor (default 12%).</p>', llms: ['qwen3.5:9b'], tools: ['IndexTTS-2 (Chatterbox fallback)', 'sidechaincompress'] }},
      ]},
      { id: 'render', name: 'Render', cards: [
        { prompt: 'Split-Screen Render', agent: 'REMIX-Renderer',
          meta: { description: '<p>Fused cut+stack+encode in ONE ffmpeg pass (no edit-list pre-roll, no A/V desync): 1080×1920, content top / self-recorded GameSim Minecraft below. Compilations: 1920×1080, panes 700/380, narrated intro/transitions/outro, concat, 8-30 min. NVENC-first (Semaphore 4), two-pass −14 LUFS.</p>', llms: ['—'], tools: ['ffmpeg vstack', 'h264_nvenc'] }},
        { prompt: 'QC Gates', agent: 'REMIX-QC',
          meta: { description: '<p>Geometry/SAR/fps=30, hidden-preroll (editlist) equality, both-panes-alive (per-pane blackdetect + YAVG variance — catches half-black renders), duration, loudness. Failures are quarantined, never delivered.</p>', llms: ['—'], tools: ['ffprobe', 'blackdetect', 'ebur128'] }},
      ]},
      { id: 'deliver', name: 'Deliver', cards: [
        { prompt: 'Deliver', agent: 'REMIX-Delivery',
          meta: { description: '<p>data/output/remix/&lt;job&gt;/ — *_final.mp4 + matching .srt + attribution.json (source, ranges, narration script, permission basis). Download links on /remix. Never lands in output/clips (auto-uploader stays blind to it).</p>', llms: ['—'], tools: ['attribution.json'] }},
        { prompt: 'Cleanup', agent: 'REMIX-Cleaner',
          meta: { description: '<p>Source download + work dir deleted at clip creation; finished clips auto-delete after 72 h (upload window). Library metadata survives for compilations + dedupe.</p>', llms: ['—'], tools: ['retention_sweep'] }},
      ]},
    ],
  };
})(TEMPLATES);

(function _addRemixAiTemplate(T) {
  // Card `prompt` values are joined to KANBAN_STAGE_MAP_REMIXAI in
  // bp_pipeline_api.py by EXACT match — every title below must stay byte-for-byte
  // identical to a key in that map, or the card never leaves QUEUED.
  T.remix_ai = {
    name: 'Remix Ai',
    label: '[ REMIX AI — STUDY A FORMAT, BUILD AN ORIGINAL ]',
    columns: [
      { id: 'discover', name: 'Discover', cards: [
        { prompt: 'Source Sweep', agent: 'REMIXAI-Scout',
          meta: { description: '<p>Keyword sweep over the operator term list (<b>/remix-ai</b>) via yt-dlp <code>ytsearch</code> — zero API quota, where <code>search.list</code> would cost 100 units a call. Ranked by <b>view velocity</b> (views/hour since publish), not raw views: raw views rank a four-year-old evergreen above everything current. Every hit is scored for AI provenance (named generator = strong, bare &quot;ai video&quot; = weak) and anything under the floor is dropped, because a video <i>about</i> AI is not an AI-<i>generated</i> video. A dedupe ledger means no source is ever studied twice.</p>', llms: ['—'], tools: ['remixai_ingest.sweep', 'yt-dlp ytsearch'] }},
        { prompt: 'Source Download', agent: 'REMIXAI-Fetcher',
          meta: { description: '<p>yt-dlp ≤1080p as a subprocess. FAIL-CLOSED disk gate (≥100 GB free, remix_ai tree ≤ cap). A <code>&lt;id&gt;_transcript.json</code> sidecar is written beside the download so the inspection Videos tab excludes it in both modes — source material never appears as a deliverable. The file is deleted at the end of analysis, and again on every exception path.</p>', llms: ['—'], tools: ['yt-dlp', 'disk gate'] }},
      ]},
      { id: 'analyse', name: 'Analyse', cards: [
        { prompt: 'Frame Analysis', agent: 'REMIXAI-Eye',
          meta: { description: '<p>Eight frames sampled across the source (first/last 5% skipped — intro cards and end screens describe the channel, not the content). A VLM reads each for <b>treatment</b>: shot, lighting, palette, setting, aesthetic. The per-frame reads are then fused into one <b>style contract</b> every generated image obeys, so the output reads as a single piece instead of N unrelated stills. This is the half that is deliberately detailed — matching an aesthetic is the goal, and a style is not ownable.</p>', llms: ['qwen3.5:9b (vision)'], tools: ['remixai_analyze.describe_frames', 'ffmpeg'] }},
        { prompt: 'Transcript Analysis', agent: 'REMIXAI-Reader',
          meta: { description: '<p>Captions first (zero GPU), local ASR when they are missing and the GPU is free. The LLM returns a <b>structural brief</b> only: topic, angle, beat labels, hook type, register, pacing, standalone facts. It returns <b>no sentences from the source</b> — and any beat label that comes back long enough to be lifted prose is stripped before the function returns. This is what the new script is written from.</p>', llms: ['qwen3.5:9b'], tools: ['youtube_transcript_api', 'zyg_whisper'] }},
        { prompt: 'Soundtrack Analysis', agent: 'REMIXAI-Ear',
          meta: { description: '<p>CLAP text-audio similarity ranks the bed against a genre list and a mood list, and reports the <b>margin</b> on each. A thin margin means the read is ambiguous, and the replacement search widens rather than trusting a confidently-wrong genre label. <b>The source is deleted here</b> — analysis is complete and nothing downstream reads it again.</p>', llms: ['—'], tools: ['audio_qc.qc_clap', 'CLAP htsat-fused'] }},
      ]},
      { id: 'regenerate', name: 'Regenerate', cards: [
        { prompt: 'Script Regeneration', agent: 'REMIXAI-Writer',
          meta: { description: '<p>The brief — and nothing else — becomes a <b>new script</b>: same subject, same beat shape, same hook type, written fresh. <code>regenerate_script()</code> takes the abstract brief and has no parameter through which source wording could reach it, so this cannot degrade into a reworded copy. Length is set from the source’s own words-per-minute against the target duration.</p>', llms: ['qwen3.5:9b (Haiku fallback, off by default)'], tools: ['remixai_analyze.regenerate_script'] }},
        { prompt: 'Title Regeneration', agent: 'REMIXAI-Writer',
          meta: { description: '<p>The source title is read for its <b>format</b> — hook device, capitalisation, length, whether it carries a number — and a new title is written into that format for our topic. Formats are not ownable; sentences are. A similarity guard (Jaccard ≥ 0.6 over content words, or any shared 5-word run) rejects a generated title that leaned on the source’s actual wording and falls back to the topic.</p>', llms: ['qwen3.5:9b'], tools: ['remixai_analyze.regenerate_title'] }},
        { prompt: 'AI Image Generation', agent: 'REMIXAI-Painter',
          meta: { description: '<p>One still per script beat: the beat’s own visual line + the nearest source frame’s shot/lighting language + the fused style suffix. <b>klein (FLUX.2 klein-4B, Apache-2.0)</b> by default — the channel is monetised, so FLUX.1-dev is not reachable from this department. Image size is the ~1 MP diffusion-friendly neighbour of the output canvas; Ken Burns upscales 2× and crops back, so 1 MP is sharp at delivery. A beat whose still fails borrows its neighbour’s rather than dropping the line.</p>', llms: ['—'], tools: ['comfy_generation_service.generate_still', 'klein t2i'] }},
      ]},
      { id: 'produce', name: 'Produce', cards: [
        { prompt: 'TTS Narration', agent: 'REMIXAI-Voice',
          meta: { description: '<p><b>IndexTTS-2</b> clones a seed-pool voice and speaks each beat as its own wav (Chatterbox fallback on a VRAM-starved GPU). One call per beat, so a picture is on screen for exactly the audio that belongs to it.</p>', llms: ['—'], tools: ['tts_service._tts_shared', 'IndexTTS-2'] }},
        { prompt: 'Ken Burns Animation', agent: 'REMIXAI-Motion',
          meta: { description: '<p>Each still becomes a clip as long as its narration + lead-in + tail. <code>zoompan</code> runs on a 2×-upscaled frame so the crop never softens the picture, capped at 1.08 — past that the crop eats enough of every edge to clip anything composed near the border. The drift direction alternates by beat index; all-one-direction reads as a mechanical slideshow.</p>', llms: ['—'], tools: ['ffmpeg zoompan', 'libx264'] }},
        { prompt: 'Video Assembly', agent: 'REMIXAI-Editor',
          meta: { description: '<p>Every segment is encoded identically, then joined with <code>-c copy</code> — no re-encode, no drift, no A/V desync. Canvas <b>matches the source’s shape</b> (operator decision): a vertical short in gives a vertical short out, 16:9 gives 16:9. The format is part of what is working, so normalising it away would discard it.</p>', llms: ['—'], tools: ['ffmpeg concat', '-c copy'] }},
      ]},
      { id: 'finish', name: 'Finish', cards: [
        { prompt: 'Soundtrack Replacement', agent: 'REMIXAI-Scorer',
          meta: { description: '<p>A <b>different</b> track of the <b>same</b> genre, from our own licensed library through the audio_service tiers, mixed under the narration. The CLAP reading maps to the mood vocabulary audio_service understands; when CLAP was ambiguous the genre is dropped and mood alone drives the pick. A failed pick delivers narration-only rather than blocking the episode.</p>', llms: ['—'], tools: ['audio_service.get_music_for_topic', 'mix_bgm_into_video'] }},
        { prompt: 'Subtitle Burn', agent: 'REMIXAI-Subs',
          meta: { description: '<p>SRT from the beat timings, burned in at 3% of canvas height. <b>Subtitles use DIGITS</b> — converted in the subtitle writer only, never in the TTS source, because the synthesiser reads spelled-out numerals correctly and bare digits inconsistently. A sibling <code>.vtt</code> is written beside the mp4, which is what puts Captions in the inspection player’s menu.</p>', llms: ['—'], tools: ['ffmpeg subtitles', 'WebVTT'] }},
        { prompt: 'Delivery', agent: 'REMIXAI-Delivery',
          meta: { description: '<p><code>data/output/remix_ai/&lt;job&gt;/</code> — FINAL mp4 + .vtt + .srt + manifest.json + an operator <b>upload sheet</b> (title, alternates, and a provenance block recording that the source was deleted and that the script/title/images are generated). Its own subtab in the inspection Videos tab. Nothing auto-publishes: a human reads the sheet first. Work dirs are removed; deliverables age out on the retention TTL.</p>', llms: ['—'], tools: ['manifest.json', 'upload_sheet.txt'] }},
      ]},
    ],
  };
})(TEMPLATES);

// ── Channel boards ────────────────────────────────────────────────────────────
// Empty content-production boards (5 columns, no cards) for every channel and
// sub-channel from Creator Nexus. Added to TEMPLATES before TEMPLATES_SDXL is
// cloned so channel boards appear in both family views automatically.
(function _addChannelTemplates(T) {
  function _ch(name, label) {
    return {
      name,
      label: label || ('[ ' + name.toUpperCase() + ' ]'),
      columns: [
        { id: 'ideas',      name: 'Ideas',      cards: [] },
        { id: 'scripting',  name: 'Scripting',  cards: [] },
        { id: 'production', name: 'Production', cards: [] },
        { id: 'editing',    name: 'Editing',    cards: [] },
        { id: 'published',  name: 'Published',  cards: [] },
      ],
    };
  }

  // ── shared tail columns for both briefing families ───────────────────────
  // Split out because the four post-script stages are byte-identical across all
  // twelve boards; duplicating them twelve times is twelve places to drift.
  function _briefingTail(agentPrefix, deliverPath) {
    return [
      { id: 'visuals', name: 'Visuals', cards: [
        { prompt: 'Build Charts', agent: agentPrefix + '-Charts',
          meta: { description: '<p>Every chart is drawn <b>locally</b> with matplotlib at 1920×1080 in the channel\'s own theme — no chart is ever screenshotted from a data provider. The opening board lists every item researched this episode and is the first thing on screen.</p>', llms: ['—'], tools: ['briefing_video.render_board', 'matplotlib Agg'] }},
      ]},
      { id: 'voice', name: 'Narration', cards: [
        { prompt: 'Narrate', agent: agentPrefix + '-Voice',
          meta: { description: '<p><b>IndexTTS-2</b> clones this channel\'s fixed seed-pool voice (Chatterbox fallback). One TTS call per panel, so a panel is on screen for exactly the audio that describes it. Each channel owns a different voice — set it on <b>' + deliverPath + '</b>.</p>', llms: ['—'], tools: ['tts_service._tts_shared', 'voice_seeds/pool'] }},
      ]},
      { id: 'render', name: 'Render', cards: [
        { prompt: 'Render Episode', agent: agentPrefix + '-Renderer',
          meta: { description: '<p>One clip per panel, all encoded identically, joined with <code>-c copy</code> (no re-encode, no drift). NVENC-first. Two-pass EBU R128 to −14 LUFS. Chapter metadata is muxed into the container as well as written to the description.</p>', llms: ['—'], tools: ['ffmpeg concat', 'h264_nvenc', 'loudnorm'] }},
        { prompt: 'QC Gates', agent: agentPrefix + '-QC',
          meta: { description: '<p>Fail-closed: 1920×1080 geometry, video + audio streams present, duration within 5% of plan, ≥3 minutes, <b>≥3 chapters starting at 0:00 and strictly ascending</b> (YouTube drops the whole chapter list otherwise), narration audible (mean &gt; −45 dB) and no 4-second black hole. A failure quarantines the file instead of delivering it.</p>', llms: ['—'], tools: ['ffprobe', 'volumedetect', 'blackdetect'] }},
      ]},
      { id: 'deliver', name: 'Deliver', cards: [
        { prompt: 'Deliver', agent: agentPrefix + '-Delivery',
          meta: { description: '<p><code>' + deliverPath + '</code> — the mp4, a <b>description.txt carrying the <code>mm:ss</code> chapter list</b> that becomes the segmented YouTube playbar, the chapters file, the spoken script and episode.json. Own folder per channel; nothing lands in output/clips.</p>', llms: ['—'], tools: ['description.txt', 'episode.json'] }},
        { prompt: 'Ice Box', agent: agentPrefix + '-IceBox',
          meta: { description: '<p>The picks that were researched but deliberately <b>kept off the episode</b>, parked with a ready-to-paste telegram/X post. Operator spec: always keep some on ice. Copy them from the console.</p>', llms: ['—'], tools: ['icebox_add', 'social_text'] }},
        { prompt: 'Cleanup', agent: agentPrefix + '-Cleaner',
          meta: { description: '<p>The work dir goes at delivery; the finished episode <b>auto-deletes after 72 h</b> (operator\'s 3-day rule) so the folder never congests. Metadata survives in the history file.</p>', llms: ['—'], tools: ['retention_sweep'] }},
      ]},
    ];
  }

  // ── Stockmarket / Cryptodaily ────────────────────────────────────────────
  function _briefingBoard(name, label, prefix, o) {
    return {
      name, label,
      columns: [
        { id: 'research', name: 'Research', cards: [
          { prompt: 'Collect Market Data', agent: prefix + '-Screener',
            meta: { description: '<p>Pulls daily OHLCV for the whole universe — <b>' + o.universe + '</b> — through a provider chain (<code>' + o.provider + '</code>) with an 8-hour disk cache. Yahoo hard-429s this host and Stooq now sits behind a JS challenge; neither is in the chain.</p>', llms: ['—'], tools: ['market_ingest.fetch_bars', 'market_cache/'] }},
          { prompt: 'Score & Rank', agent: prefix + '-Analyst',
            meta: { description: '<p>Decides <b>rise or fall</b> and <b>short-term trade vs long-term investment</b> from the bars alone. <code>long_score</code> reads the 60–200-day structure (trend stack, six-month momentum, 52-week position); <code>short_score</code> reads 5–20 days (recent momentum, MACD turn, RSI, ATR stretch, volume surge). The larger one sets the horizon, so the split is measured, not labelled. Ships a <code>drivers</code> list where every claim carries its number. The board is balanced so an episode is never seven identical breakouts.</p>', llms: ['—'], tools: ['indicators()', 'score_symbol()'] }},
        ]},
        { id: 'script', name: 'Script', cards: [
          { prompt: 'Write Script', agent: prefix + '-Writer',
            meta: { description: '<p>The local LLM turns the measured <code>drivers</code> into spoken English — it never decides anything. Anything it writes is then scanned for figures that appear in <b>none</b> of the source facts; if it invented a number, the copy is discarded and the measured facts are spoken verbatim. A hallucinated price target on a finance channel is not a style problem.</p>', llms: ['qwen3.5:9b'], tools: ['llm_invented_numbers()', 'ollama'] }},
        ]},
      ].concat(_briefingTail(prefix, 'data/output/' + (prefix === 'CRYPTO' ? 'crypto' : 'stocks') + '/&lt;job&gt;/')),
    };
  }

  // ── TokiToki / Arena sub-channels ──────────────────────────────────────
  function _bettingBoard(name, label, chan, catLabel, catKey) {
    const prefix = chan.toUpperCase() + '-' + catLabel.toUpperCase();
    return {
      name, label,
      columns: [
        { id: 'research', name: 'Research', cards: [
          { prompt: 'Collect Fixtures', agent: prefix + '-Scout',
            meta: { description: '<p>Every <b>' + catLabel + '</b> fixture on the whole local calendar day <b>two days out</b> (the operator\'s D+2 rule — always ≥24 h and ≤72 h away). Only whitelisted tier-1 competitions; Asian and African leagues are excluded at the source and cross-continental entrants are dropped again by country. <b>/events costs 0 API credits</b>, so leagues with nothing on never spend one.</p>', llms: ['—'], tools: ['The Odds API /events', 'window_for()'] }},
          { prompt: 'Price & Select Bets', agent: prefix + '-Modeller',
            meta: { description: '<p>De-vigs every bookmaker, keeps only outcomes quoted by at least half of them (1xBet prices a "Draw" on two-man MMA fights and it used to bias every event), anchors fair probability on the sharp books and exchanges, and excludes the book offering the best price from judging its own price. Edge = fair probability × best price − 1. Selections are labelled <b>VALUE BET</b> or <b>CONFIDENCE PICK</b> on air — a channel that calls every pick +EV is a channel nobody can check. Stake is quarter-Kelly, capped at 2%.</p>', llms: ['—'], tools: ['price_event()', 'score_event()', 'The Odds API /odds'] }},
        ]},
        { id: 'assets', name: 'Artwork', cards: [
          { prompt: 'Pull Team Art', agent: prefix + '-Artwork',
            meta: { description: '<p>Badges (' + (catKey === 'mma' || catKey === 'tennis' ? 'fighter/player cutouts' : 'club crests') + ') from TheSportsDB, cached on disk and composited <b>unmodified with aspect preserved</b> — their terms require trademarked logos to be used as-is. Credited in every description. Anything that will not resolve falls back to a locally drawn initials card rather than a wrong photo.</p>', llms: ['—'], tools: ['TheSportsDB', 'sports_art/'] }},
        ]},
        { id: 'script', name: 'Script', cards: [
          { prompt: 'Write Script', agent: prefix + '-Writer',
            meta: { description: '<p>Three spoken parts per match — introduce the fixture and the price, argue <b>for</b> the selection, then the counter-case and the stake — so the side being talked about is the side on screen. The LLM only rephrases measured facts and is number-checked; invented figures mean the measured facts are spoken instead.</p>', llms: ['qwen3.5:9b'], tools: ['llm_invented_numbers()', 'ollama'] }},
        ]},
      ].concat(_briefingTail(prefix, 'data/output/' + chan.toLowerCase() + '/' + catKey + '/&lt;job&gt;/')),
    };
  }
  // ── Main channels ──
  T.ch_benchmark   = _ch('Benchmark');
  T.ch_cars        = _ch('Cars');
  T.ch_financials  = _ch('Financials');
  T.ch_news        = _ch('News');
  T.ch_storyteller = _ch('Storyteller Channel');
  T.ch_arena     = _ch('Arena');
  T.ch_tokitoki    = _ch('TokiToki');
  T.ch_luxury      = _ch('Luxury');
  T.ch_traveling   = _ch('Traveling');
  T.ch_clipped = {
    name:  'Clipped',
    label: '[ CLIPPED PIPELINE ]',
    columns: [
      // ── Stage 1: Discovery ────────────────────────────────────────────────
      { id: 'discovery', name: 'Discovery', cards: [
        { prompt: 'Source Scanner', agent: 'CLIPFARM-Source-Scanner-Agent', meta: {
          description: '<p><strong>Scans YouTube RSS feeds and the Data API for trending content on approved channels.</strong></p><ul><li>Reads approved channels from <code>clipfarm_channels.json</code> (<code>clipping_permission: true</code>)</li><li>Checks YouTube Data API for new uploads, view counts, and engagement metrics</li><li>Skips livestreams and upcoming premieres (yt-dlp cannot download them)</li><li>Returns candidate video URLs with: title, view count, publish date, duration</li></ul>',
          llms: ['—'], tools: ['YouTube Data API v3', 'YouTube RSS feeds', 'clipfarm_channels.json', 'yt-dlp (metadata only)'],
        }},
      ]},
      // ── Stage 2: Analysis ─────────────────────────────────────────────────
      { id: 'analysis', name: 'Analysis', cards: [
        { prompt: 'Metrics Agent', agent: 'CLIPFARM-Metrics-Agent', meta: {
          description: '<p><strong>Calculates engagement metrics to score each candidate video.</strong></p><ul><li>View-to-subscriber ratio, like/view ratio, comment density</li><li>Compares against 30-day channel baseline</li><li>Flags viral outliers (&gt;2× baseline views) as priority</li><li>Output: per-video engagement score 0.0–1.0</li></ul>',
          llms: ['—'], tools: ['YouTube Data API v3', 'Engagement calculator', 'Channel baseline stats'],
        }},
        { prompt: 'Trend Detector', agent: 'CLIPFARM-Trend-Detector-Agent', meta: {
          description: '<p><strong>Detects trending signals to prioritise content riding current waves.</strong></p><ul><li>Cross-references video topics against Google Trends</li><li>Identifies trending keywords in titles and descriptions</li><li>Boosts score for videos touching trending topics by up to 0.35×</li></ul>',
          llms: ['—'], tools: ['Google Trends API', 'Keyword extractor', 'Trend scoring model'],
        }},
        { prompt: 'Research Agent', agent: 'CLIPFARM-Research-Agent', meta: {
          description: '<p><strong>Researches the topic of each candidate to inform hook writing and commentary.</strong></p><ul><li>Web search for background context on the video topic</li><li>Identifies related viral clips on the same topic (cross-channel)</li><li>Outputs a research brief used by Hook Generator and Commentary Agent downstream</li></ul>',
          llms: ['Ollama qwen3.6:35b-a3b (local)'], tools: ['Web search', 'Ollama /api/chat', 'Topic summariser'],
        }},
        { prompt: 'Overview Agent', agent: 'CLIPFARM-Overview-Agent', meta: {
          description: '<p><strong>Builds a per-channel content overview to inform assignment strategy.</strong></p><ul><li>Summarises recent upload cadence and content themes per channel</li><li>Flags channels going cold (&lt;1 upload/week) or heating up (&gt;3/week)</li><li>Output feeds Stage 6 Assignment Agent — matches clips to the right sub-channels</li></ul>',
          llms: ['Ollama gpt-oss:20b (local)'], tools: ['Channel feed parser', 'Ollama /api/chat', 'Cadence tracker', 'Theme classifier'],
        }},
        { prompt: 'Compliance Check', agent: 'CLIPFARM-Compliance-Agent', meta: {
          description: '<p><strong>Verifies each candidate against clipping and monetization policy.</strong></p><ul><li>Checks <code>clipfarm_channels.json</code> for explicit <code>clipping_permission: true</code></li><li>Reads yt-dlp metadata for license type (standard_youtube vs creativeCommon)</li><li>Flags Content ID claims or age restrictions</li><li>Any video failing compliance is hard-blocked — never reaches Stage 3</li></ul>',
          llms: ['—'], tools: ['clipfarm_channels.json', 'yt-dlp --dump-json', 'YouTube Data API v3 (license field)'],
        }},
      ]},
      // ── Stage 3: Selection ────────────────────────────────────────────────
      { id: 'selection', name: 'Selection', cards: [
        { prompt: 'Selection Agent', agent: 'CLIPFARM-Selection-Agent', meta: {
          description: '<p><strong>Scores and ranks compliance-cleared candidates into the final approved clip list.</strong></p><ul><li>Pure Python: view/age ratio scoring, Shorts filter, live-stream filter</li><li>Applies per-channel quota (max 2 clips per channel per run)</li><li>Selects top N long-form candidates — Shorts and livestreams are hard-blocked</li><li>Output: <code>approved_clips</code> list with ranked video IDs and metadata</li></ul>',
          llms: ['—'], tools: ['Score aggregator (pure Python)', 'Per-channel quota enforcer', 'approved_clips state writer'],
        }},
        { prompt: 'Deduplication', agent: 'CLIPFARM-Deduplication-Agent', meta: {
          description: '<p><strong>Removes videos already processed in recent runs to prevent repeat clips.</strong></p><ul><li>Reads <code>clipped_video_ids.json</code> (last 50 processed IDs)</li><li>Removes matching IDs from the approved list</li><li>If a channel has no unclipped videos left, resets dedup for that channel only</li><li>Updated ID list written back after run completes</li></ul>',
          llms: ['—'], tools: ['clipped_video_ids.json', 'Dedup hash store', 'Per-channel reset logic'],
        }},
      ]},
      // ── Stage 4a: Fetch ───────────────────────────────────────────────────
      { id: 'fetch', name: 'Fetch', cards: [
        { prompt: 'Transcript Fetch', agent: 'CLIPFARM-Transcript-Fetch-Agent', meta: {
          description: '<p><strong>Downloads the transcript/captions for each approved video.</strong></p><ul><li>First tries YouTube auto-captions (free, fast) via <code>yt-dlp --write-auto-subs</code></li><li>Falls back to local Whisper STT (openai-whisper <code>base</code>) if captions are unavailable or non-English</li><li>Output: .srt file per video in the pipeline output directory</li><li>Whisper runs on GPU when available; CPU fallback adds ~5× time</li></ul>',
          llms: ['Whisper base (STT fallback)'], tools: ['yt-dlp --write-auto-subs', 'openai-whisper base', 'SRT parser'],
        }},
        { prompt: 'Video Download', agent: 'CLIPFARM-Video-Fetch-Agent', meta: {
          description: '<p><strong>Downloads the source video for each approved clip.</strong></p><ul><li>Uses yt-dlp with <code>bestvideo+bestaudio</code>, prefers MP4 container</li><li>Falls back to .webm/.mkv if MP4 unavailable (remuxed post-download)</li><li>Supports <code>youtube_cookies.txt</code> for bot-block bypass</li><li>Progress streamed to pipeline log (% every 30 KB)</li></ul>',
          llms: ['—'], tools: ['yt-dlp', 'ffmpeg (remux)', 'youtube_cookies.txt (optional)'],
        }},
        { prompt: 'Rights Check', agent: 'CLIPFARM-Rights-Check-Agent', meta: {
          description: '<p><strong>Verifies the download succeeded and no rights blocks are active on the file.</strong></p><ul><li>Checks downloaded file is non-zero and playable (ffprobe)</li><li>Re-verifies license from yt-dlp at download time (Content ID status can change)</li><li>Hard-blocks files that fail playability or license check — not passed to Stage 4b</li></ul>',
          llms: ['—'], tools: ['ffprobe', 'yt-dlp --dump-json', 'File integrity checker'],
        }},
        { prompt: 'Content Indexer', agent: 'CLIPFARM-Content-Indexer-Agent', meta: {
          description: '<p><strong>Indexes downloaded content into the pipeline state for downstream agents.</strong></p><ul><li>Writes <code>video_path</code>, <code>transcript_path</code>, metadata to <code>pipeline_state.json</code></li><li>Extracts video duration, resolution, fps, audio channels via ffprobe</li><li>Registers <code>vid_id → channel_id</code> mapping for Stage 6 channel assignment</li></ul>',
          llms: ['—'], tools: ['ffprobe', 'pipeline_state.json writer', 'vid_id → channel_id registry'],
        }},
      ]},
      // ── Stage 4b: Processing ──────────────────────────────────────────────
      { id: 'processing', name: 'Processing', cards: [
        { prompt: 'Moment Detection', agent: 'CLIPFARM-Moment-Detection-Agent', meta: {
          description: '<p><strong>Identifies the best clip segment using keyword scoring, motion analysis, and GPT-4o director intelligence.</strong></p><ul><li>Keyword scorer: counts viral/emotional keyword hits per 30-second transcript window</li><li>Motion scorer: ffmpeg scene-change analysis across 12 parallel chunks</li><li>GPT-4o Director (GitHub Models, free tier): reads full transcript + audio energy map — returns PEAK MOMENT, KEEP/CUT decisions per segment, SFX plan, reaction clip plan, intro text</li><li>Ollama qwen3.6:35b-a3b fallback when <code>GITHUB_TOKEN</code> not set</li><li>Target clip duration: 45–90 seconds for YouTube Shorts / TikTok</li></ul>',
          llms: ['GPT-4o via GitHub Models (free tier)', 'Ollama qwen3.6:35b-a3b (local fallback)'], tools: ['Keyword transcript scorer', 'MotionScorerTool (ffmpeg, 12 parallel chunks)', 'GitHub Models API (GPT-4o)', 'Ollama /api/chat (qwen3.6:35b-a3b fallback)', 'ffmpeg (cut)'],
        }},
        { prompt: 'Variant Generator', agent: 'CLIPFARM-Variant-Generator-Agent', meta: {
          description: '<p><strong>Generates clip variants for A/B testing — different cut points and durations.</strong></p><ul><li>Up to 3 variants: short (30s), standard (60s), extended (90s)</li><li>Each variant re-runs Moment Detection with a different window width</li><li>Variants ranked by beat confidence; top variant is the primary upload</li></ul>',
          llms: ['—'], tools: ['NarrativeBeatClassifier', 'ffmpeg (segment cut)', 'Variant ranker'],
        }},
        { prompt: 'Hook Generator', agent: 'CLIPFARM-Hook-Generator-Agent', meta: {
          description: '<p><strong>Writes the intro hook for the opening of the clip.</strong></p><ul><li>Hook text comes from the GPT-4o Director output parsed in Stage 4b (INTRO: line)</li><li>Falls back to <code>_pick_narrator_intro()</code> pool — 20 pre-written sardonic host lines — when director output is empty</li><li>Hook is burned as text overlay OR spoken as TTS narrator intro</li></ul>',
          llms: ['Ollama qwen3.6:35b-a3b (local, CrewAI agent)'], tools: ['GPT-4o Director INTRO output (Stage 4b)', '_pick_narrator_intro() fallback pool', 'Hook template library'],
        }},
        { prompt: 'Commentary Agent', agent: 'CLIPFARM-Commentary-Agent', meta: {
          description: '<p><strong>Adds an optional narrator commentary line over the clip intro or outro.</strong></p><ul><li>GPT-4o (GitHub Models, free tier): generates 1 punchy reaction sentence given the clip title/transcript context</li><li>Ollama qwen3.6:35b-a3b fallback when <code>GITHUB_TOKEN</code> not set</li><li>Static pool of 20 sardonic host lines as final fallback (no API cost)</li><li>Rendered as TTS voice-over and merged into the clip audio</li><li>Only activates when <code>commentary_mode=True</code> in workflow overrides</li></ul>',
          llms: ['GPT-4o via GitHub Models (free tier)', 'Ollama qwen3.6:35b-a3b (local fallback)', 'Static pool (zero-cost final fallback)'], tools: ['GitHub Models API (GPT-4o)', 'Ollama /api/chat (fallback)', 'IndexTTS-2 via tts_service (optional)', 'ffmpeg audio merge'],
        }},
        { prompt: 'Subtitle Generator', agent: 'CLIPFARM-Subtitle-Generator-Agent', meta: {
          description: '<p><strong>Burns subtitles into the clip for accessibility and silent-view engagement.</strong></p><ul><li>Reads the .srt from Stage 4a, trims to clip start/end times, re-timestamps relative to the clip start</li><li>Burns with ffmpeg subtitles filter: bold white text, black outline, bottom-centered</li><li>Profanity bleep: <code>_bleep_audio_in_clip()</code> replaces flagged words with audio bleep + asterisks in subtitles</li></ul>',
          llms: ['—'], tools: ['ffmpeg subtitles filter', '_bleep_audio_in_clip()', 'SRT trimmer and re-timestamper'],
        }},
        { prompt: 'Sound Effects', agent: 'CLIPFARM-Sound-Effects-Agent', meta: {
          description: '<p><strong>Adds intro/outro SFX matched to the clip\'s emotional beat.</strong></p><ul><li>Revelation beat → whoosh; Conflict → tension sting; Triumph → fanfare</li><li>SFX auto-downloaded from asset library if missing (soundbible.com fallback)</li><li>Only activates when <code>sfx_mode=True</code> in workflow overrides</li></ul>',
          llms: ['—'], tools: ['ffmpeg amix', 'SFX asset library', 'soundbible.com downloader'],
        }},
        { prompt: 'Thumbnail Agent', agent: 'CLIPFARM-Thumbnail-Agent', meta: {
          description: '<p><strong>Extracts the most impactful frame from the clip to use as a thumbnail.</strong></p><ul><li>Samples frames around the beat peak timestamp from Moment Detection</li><li>Picks highest-contrast frame using <code>ffmpeg select=gt(scene,0.3)</code></li><li>Optionally overlays hook text + channel branding via PIL</li><li>Output: 1280×720 .jpg thumbnail saved alongside the video</li></ul>',
          llms: ['—'], tools: ['ffmpeg (frame extraction + scene filter)', 'PIL/Pillow (text overlay)', 'Thumbnail branding templates'],
        }},
        { prompt: 'Library Agent', agent: 'CLIPFARM-Library-Agent', meta: {
          description: '<p><strong>Registers all processed clip assets into the pipeline library.</strong></p><ul><li>Records: clip_path, thumbnail_path, transcript_path, variant_paths, metadata</li><li>Writes to <code>pipeline_state.json</code> under <code>processed_clips[]</code></li><li>Enables Stage 6 to find all assets by video_id without filesystem scanning</li></ul>',
          llms: ['—'], tools: ['pipeline_state.json writer', 'Asset manifest builder', 'processed_clips registry'],
        }},
      ]},
      // ── Stage 5: QC & Adapt ───────────────────────────────────────────────
      { id: 'qc', name: 'QC & Adapt', cards: [
        { prompt: 'QC Agent', agent: 'CLIPFARM-QC-Agent', meta: {
          description: '<p><strong>Quality-checks every processed clip before platform adaptation.</strong></p><ul><li>Verifies: non-zero file, duration in target range (30–90s), audio present, fps ≥ 24</li><li>Checks subtitle sync: first subtitle within the first 5 seconds</li><li>Flags clips below threshold for manual review or re-processing</li></ul>',
          llms: ['—'], tools: ['ffprobe', 'Duration validator', 'Audio channel check', 'Subtitle sync verifier'],
        }},
        { prompt: 'Error Detection', agent: 'CLIPFARM-Error-Detection-Agent', meta: {
          description: '<p><strong>Scans pipeline logs for encoding errors, download failures, and anomalies.</strong></p><ul><li>Reads pipeline log for ERROR and WARNING markers</li><li>Correlates errors to specific video IDs</li><li>Clips with unresolved errors are quarantined — not uploaded</li></ul>',
          llms: ['—'], tools: ['Pipeline log scanner', 'Error correlation engine', 'Quarantine registry'],
        }},
        { prompt: 'Platform Adapter', agent: 'CLIPFARM-Platform-Adapter-Agent', meta: {
          description: '<p><strong>Adapts each clip to target platform format requirements.</strong></p><ul><li>YouTube Shorts: 9:16 vertical (1080×1920), max 60s, AAC, H.264 ≤ 50 Mbps</li><li>Landscape clips center-cropped to 9:16 — face-tracking crop when MediaPipe is available</li><li>TikTok: same spec, 3-second silence pad stripped from end, extended variants up to 3 min</li></ul>',
          llms: ['—'], tools: ['ffmpeg (crop, scale, re-encode)', 'MediaPipe (face-tracking crop, optional)', 'Platform spec table'],
        }},
      ]},
      // ── Stage 6: Publish ──────────────────────────────────────────────────
      { id: 'publish', name: 'Publish', cards: [
        { prompt: 'Assignment Agent', agent: 'CLIPFARM-Assignment-Agent', meta: {
          description: '<p><strong>Assigns each clip to the correct output channel based on topic and source.</strong></p><ul><li>Reads channel overview from Stage 2 to match clip topic to channel theme</li><li>Enforces per-channel daily upload quota (default: 3 clips/day/channel)</li><li>Writes clip → channel assignment to pipeline state for Upload Agent</li></ul>',
          llms: ['Ollama gpt-oss:20b (local)'], tools: ['Channel theme matcher', 'Ollama /api/chat', 'Daily quota enforcer', 'Assignment registry'],
        }},
        { prompt: 'YouTube Scheduler', agent: 'YouTube-Scheduling-Agent', meta: {
          description: '<p><strong>Determines the optimal publish time for each clip on YouTube.</strong></p><ul><li>Reads channel audience analytics to find peak engagement windows</li><li>Spaces uploads 4+ hours apart on the same channel</li><li>Queues scheduled publish times via YouTube Data API v3 (status: scheduled)</li></ul>',
          llms: ['—'], tools: ['YouTube Data API v3 (analytics)', 'Schedule optimizer', 'Upload queue builder'],
        }},
        { prompt: 'Upload Scheduler', agent: 'CLIPFARM-Upload-Schedule-Agent', meta: {
          description: '<p><strong>Builds the master upload schedule across all platforms and channels.</strong></p><ul><li>Merges YouTube and TikTok schedules into a single ordered queue</li><li>Applies global rate limits (YouTube: 50 uploads/day/API key)</li><li>Writes <code>upload_queue.json</code> consumed by Upload Agent</li></ul>',
          llms: ['—'], tools: ['upload_queue.json writer', 'Cross-platform rate limiter', 'Schedule merger'],
        }},
        { prompt: 'Upload Agent', agent: 'CLIPFARM-Upload-Agent', meta: {
          description: '<p><strong>Executes the uploads — sends each clip to its target platform.</strong></p><ul><li>YouTube: <code>videos.insert</code> with OAuth 2.0 (<code>token.pickle</code>)</li><li>Sets title, description (with source attribution), tags, category, privacy (scheduled)</li><li>Retries up to 3× on quota errors with exponential backoff</li><li>Logs upload result (video_id, url, status) to pipeline_state.json</li></ul>',
          llms: ['—'], tools: ['YouTube Data API v3 (videos.insert)', 'token.pickle (OAuth 2.0)', 'Upload retry handler', 'Source attribution formatter'],
        }},
        { prompt: 'Air Time Agent', agent: 'CLIPFARM-Air-Time-Agent', meta: {
          description: '<p><strong>Confirms clips went live at the scheduled time and logs actual air times.</strong></p><ul><li>Polls YouTube Data API (<code>videos.list</code>) to verify status: "scheduled" → "public"</li><li>Logs <code>actual_air_time</code> to pipeline_state.json for analytics</li><li>Surfaces any upload failures that need operator action</li></ul>',
          llms: ['—'], tools: ['YouTube Data API v3 (videos.list)', 'Status poller', 'Air time logger'],
        }},
      ]},
    ],
  };
  T.ch_crime       = _ch('Crime');
  T.ch_docudocu    = _ch('DocuDocu');
  T.ch_religion    = _ch('Religion');
  // ── Benchmark sub-channels ──
  T.ch_benchmark_phones   = _ch('Phones',               '[ BENCHMARK › PHONES ]');
  T.ch_benchmark_gpus_cpus= _ch('GPUS & CPUS',          '[ BENCHMARK › GPUS & CPUS ]');
  T.ch_benchmark_cars     = _ch('Cars (Benchmark)',      '[ BENCHMARK › CARS ]');
  T.ch_benchmark_llm      = _ch('Large language models', '[ BENCHMARK › LLM ]');
  // ── Cars sub-channels ──
  T.ch_cars_future    = _ch('Future Cars',   '[ CARS › FUTURE CARS ]');
  T.ch_cars_oldtimers = _ch('Oldtimers',     '[ CARS › OLDTIMERS ]');
  T.ch_cars_mechanics = _ch('Car Mechanics', '[ CARS › CAR MECHANICS ]');
  // ── Financials sub-channels ──
  T.ch_fin_wyscamus    = _ch('wyscamus',                          '[ FINANCIALS › WYSCAMUS ]');
  // ── Stockmarket + Cryptodaily: live pipeline boards (2026-08-06) ──────────
  // Card `prompt` strings are the EXACT join keys with KANBAN_STAGE_MAP for
  // dept 'stocks' / 'crypto' in bp_pipeline_api.py — one character of drift
  // leaves a card queued forever.
  T.ch_fin_stockmarket = _briefingBoard('Stockmarket', '[ FINANCIALS › STOCKMARKET ]', 'MARKET', {
    universe: 'S&amp;P 500 ∪ Nasdaq-100 (517 names)',
    provider: 'twelvedata → stockanalysis → nasdaq → alphavantage',
    asset: 'stock', console: '/markets',
  });
  T.ch_fin_crypto      = _briefingBoard('Cryptodaily', '[ FINANCIALS › CRYPTODAILY ]', 'CRYPTO', {
    universe: 'CoinGecko top-120, stablecoins and wrappers removed',
    provider: 'binance → coinbase → kraken → coingecko',
    asset: 'coin', console: '/markets',
  });
  T.ch_fin_history     = _ch('Future and past financial events',  '[ FINANCIALS › FIN. HISTORY ]');
  T.ch_fin_housing     = _ch('Housing',                           '[ FINANCIALS › HOUSING ]');
  T.ch_fin_landplots   = _ch('Developmental Landplots',           '[ FINANCIALS › LANDPLOTS ]');
  // ── News sub-channels ──
  T.ch_news_world = _ch('Impactfull Worldnews',     '[ NEWS › WORLD ]');
  T.ch_news_ru    = _ch('Daily News Russian',        '[ NEWS › RUSSIAN ]');
  T.ch_news_en    = _ch('Daily News Western',        '[ NEWS › WESTERN ]');
  T.ch_news_eu    = _ch('Daily News Europe',         '[ NEWS › EUROPE ]');
  T.ch_news_cn    = _ch('Daily News China',          '[ NEWS › CHINA ]');
  T.ch_news_sa    = _ch('Daily News South America',  '[ NEWS › SOUTH AMERICA ]');
  // ── Storyteller sub-channels ──
  T.ch_story_her    = _ch('Her Stories',    '[ STORYTELLER › HER STORIES ]');
  T.ch_story_his    = _ch('His Stories',    '[ STORYTELLER › HIS STORIES ]');
  T.ch_story_madeup = _ch('Made up stories','[ STORYTELLER › MADE UP STORIES ]');
  // ── Arena + TokiToki sub-channels: live pipeline boards (2026-08-06) ────
  // Every sub-channel runs the SAME pipeline (pipeline_sports) with a different
  // category, so every board carries the same cards — operator spec: "all their
  // subchannels need to be build in the same way, then we can modify them a tiny
  // bit later". Board key ↔ category mapping lives in bp_pipeline_api.py
  // (basketball→nba, mma→ufc; soccer/tennis/nfl are 1:1).
  T.ch_arena_soccer = _bettingBoard('ArenaSoccer', '[ ARENA › SOCCER ]', 'Arena', 'Soccer', 'soccer');
  T.ch_arena_nba    = _bettingBoard('ArenaNBA',    '[ ARENA › NBA ]',    'Arena', 'Basketball', 'basketball');
  T.ch_arena_ufc    = _bettingBoard('ArenaUFC',    '[ ARENA › UFC ]',    'Arena', 'MMA', 'mma');
  T.ch_arena_tennis = _bettingBoard('ArenaTennis', '[ ARENA › TENNIS ]', 'Arena', 'Tennis', 'tennis');
  T.ch_arena_nfl    = _bettingBoard('Arena|NFL',   '[ ARENA › NFL ]',    'Arena', 'NFL', 'nfl');
  T.ch_tokitoki_soccer = _bettingBoard('TokiTokiSoccer', '[ TOKITOKI › SOCCER ]', 'TokiToki', 'Soccer', 'soccer');
  T.ch_tokitoki_nba    = _bettingBoard('TokiTokiNBA',    '[ TOKITOKI › NBA ]',    'TokiToki', 'Basketball', 'basketball');
  T.ch_tokitoki_ufc    = _bettingBoard('TokiTokiUFC',    '[ TOKITOKI › UFC ]',    'TokiToki', 'MMA', 'mma');
  T.ch_tokitoki_tennis = _bettingBoard('TokiTokiTennis', '[ TOKITOKI › TENNIS ]', 'TokiToki', 'Tennis', 'tennis');
  T.ch_tokitoki_nfl    = _bettingBoard('TokiTokiNFL',    '[ TOKITOKI › NFL ]',    'TokiToki', 'NFL', 'nfl');
})(TEMPLATES);

// SDXL Stage 1d preview card on the base FLUX template too (status only lights for sdxl runs).
(function _injectSdxlPreviewCard(tmplRoot) {
  try {
    const cols = (tmplRoot.character_creation || {}).columns || [];
    const loraCol = cols.find(c => c.id === 'lora');
    if (loraCol && Array.isArray(loraCol.cards)) {
      if (!loraCol.cards.some(c => c.prompt === 'SDXL Preview Render')) {
        loraCol.cards.unshift({
          prompt: 'SDXL Preview Render',
          agent: 'SDXL (Juggernaut XL v9)',
          meta: {
            description: '<p><strong>Stage 1d — SDXL previews only (lights when <code>model_family=sdxl</code>).</strong></p><ul><li>Canonical files: <code>preview_sdxl_*.png</code></li></ul>',
            llms: ['SDXL DynaVision XL / aligned base 1.0 / Juggernaut XL v9 (local)'],
            tools: ['sdxl_character_locked', 'sdxl_txt2img', 'sdxl_character_instantid', 'sdxl_img2img'],
          },
        });
      }
    }
  } catch {}
})(TEMPLATES);

// ── Melodies (2026-09-06) ────────────────────────────────────────────────────
// "Children's Music" used to be one flat item in the Pipelines list.  It is now
// the MELODIES category — the live composer board plus a board for every melody
// style — so it hangs off a chevron the way Benchmark, News and Financials do.
//
// ONE TABLE, TWO CONSUMERS.  MELODY_FAMILIES below registers the TEMPLATES entry
// for every style AND builds the flyout (_buildMelodyMenu).  The other groups
// keep their <div>s hand-written in kanban.html, which is fine at four
// sub-channels and is not fine at 127: a second copy of this list is either a
// menu entry whose board does not exist (_buildFromTemplate falls back to
// Documentary, silently) or a board nothing can navigate to.
//
// WIRED: CHILDREN + CINEMATIC (2026-09-06).  The eleven children keys in MELODY_WIRED are
// shelves in the Melodies library (kanban_server._KM_FAMILIES) AND styles the
// composer can actually write, so each of their boards is a DEEP CLONE of the
// live composer board (T.kidsmusic): the same six columns and the same twelve
// cards, with the card `prompt` strings byte-identical — those strings are the
// join keys with KANBAN_STAGE_MAP in bp_pipeline_api.py, and a clone that
// renames one of them is a card no stage can ever light.  Only two things
// differ per style: the Song Brief description names the style and its three
// voices, and the Score Render agent names the sampled-instrument path.
//
// 'children/dance' is EXCLUDED by operator decision (MELODY_EXCLUDED).  It is
// not a library shelf and no composer style produces it; its menu row is dimmed
// and inert rather than deleted, so the absence reads as a decision instead of
// a lost entry.
//
// Every OTHER family's style board stays an EMPTY board, the same shape _ch()
// gives an unbuilt channel, because pipeline_kidsmusic is still the only melody
// runner that exists; giving 116 more boards cards no stage can ever light
// would make them look permanently stalled — the exact failure the Second
// Ledger board once had.  Those empty columns are already pipeline_kidsmusic's
// own stage ids (brief · compose · render · produce · deliver), so wiring one
// later is filling cards in, not re-cutting the board.
//
// `1` in the third slot marks a style that is ALREADY a shelf in the Melodies
// library (kanban_server._KM_FAMILIES) — the boards a runner could file into
// today.  Style names repeat across families on purpose: the library already
// carries 'Storytime' under two families and addresses a shelf only ever as
// (family, shelf), and 'Sonata' is both a Cinematic shelf and a classical form.
const MELODY_FAMILIES = [
  { key: 'children', name: "Children's Music", short: "Children's Music", styles: [
    ['playtime',   'Playtime', 1],
    ['sleeptime',  'Sleeptime', 1],
    ['storytime',  'Storytime', 1],
    ['learning',   'Learning', 1],
    ['lullaby',    'Lullaby', 1],
    ['nursery',    'Nursery Rhyme', 1],
    ['counting',   'Counting & Alphabet', 1],
    ['dance',      'Action & Dance-along', 0, 'excluded'],
    ['singalong',  'Sing-along', 1],
    ['animals',    'Animal Songs', 1],
    ['seasons',    'Seasons & Holidays', 1],
    ['bedtime',    'Bath & Bedtime Routine', 1],
  ]},
  { key: 'cinematic', name: 'Cinematic', short: 'Cinematic', styles: [
    ['cheerful',  'Cheerful', 1],
    ['sad',       'Sad', 1],
    ['heroic',    'Heroic', 1],
    ['tavern',    'Tavern', 1],
    ['storytime', 'Storytime', 1],
    ['sonata',    'Sonata', 1],
    ['suspense',  'Suspense', 1],
    ['romance',   'Romance', 1],
    ['wonder',    'Wonder & Discovery', 1],
    ['mystery',   'Mystery', 1],
    ['chase',     'Chase', 1],
    ['melancholy','Melancholy', 1],
    ['triumph',   'Triumphant Finale', 1],
  ]},
  { key: 'cue', name: 'Soundtrack Cues', short: 'Soundtrack', styles: [
    ['theme',      'Main Theme', 1],
    ['opening',    'Opening', 1],
    ['underscore', 'Underscore', 1],
    ['tension',    'Tension', 1],
    ['action',     'Action', 1],
    ['closing',    'Closing', 1],
    ['montage',    'Montage'],
    ['endtitles',  'End Titles'],
    ['stinger',    'Stinger'],
    ['bumper',     'Bumper / Transition'],
  ]},
  { key: 'classical', name: 'Classical Forms', short: 'Classical', styles: [
    ['sonata',      'Sonata'],
    ['sonatina',    'Sonatina'],
    ['nocturne',    'Nocturne'],
    ['waltz',       'Waltz'],
    ['etude',       'Étude'],
    ['prelude',     'Prelude'],
    ['fugue',       'Fugue'],
    ['canon',       'Canon'],
    ['minuet',      'Minuet'],
    ['rondo',       'Rondo'],
    ['scherzo',     'Scherzo'],
    ['serenade',    'Serenade'],
    ['ballade',     'Ballade'],
    ['mazurka',     'Mazurka'],
    ['polonaise',   'Polonaise'],
    ['barcarolle',  'Barcarolle'],
    ['impromptu',   'Impromptu'],
    ['toccata',     'Toccata'],
    ['variations',  'Theme & Variations'],
    ['bagatelle',   'Bagatelle'],
    ['arabesque',   'Arabesque'],
    ['intermezzo',  'Intermezzo'],
    ['elegy',       'Elegy'],
    ['march',       'March'],
    ['chorale',     'Chorale'],
    ['reverie',     'Rêverie'],
    ['fantasia',    'Fantasia'],
    ['overture',    'Overture'],
  ]},
  { key: 'folk', name: 'Folk & World', short: 'Folk', styles: [
    ['jig',       'Celtic Jig'],
    ['reel',      'Reel'],
    ['shanty',    'Sea Shanty'],
    ['tango',     'Tango'],
    ['flamenco',  'Flamenco'],
    ['bolero',    'Bolero'],
    ['tarantella','Tarantella'],
    ['klezmer',   'Klezmer'],
    ['gamelan',   'Gamelan'],
    ['raga',      'Raga-inspired'],
    ['andean',    'Andean Panpipe'],
    ['bossa',     'Bossa Nova'],
    ['samba',     'Samba'],
    ['fado',      'Fado'],
    ['balkan',    'Balkan Brass'],
    ['highland',  'Highland Pipes'],
    ['polka',     'Polka'],
    ['hoedown',   'Hoedown / Bluegrass'],
  ]},
  { key: 'ambient', name: 'Ambient & Functional', short: 'Ambient', styles: [
    ['meditation',   'Meditation'],
    ['focus',        'Focus & Study'],
    ['deepsleep',    'Deep Sleep'],
    ['yoga',         'Yoga & Breathwork'],
    ['spa',          'Spa & Massage'],
    ['nature',       'Nature Soundscape'],
    ['drone',        'Drone'],
    ['minimalpiano', 'Minimal Piano'],
    ['hold',         'Waiting / Hold Music'],
    ['lofi',         'Lo-fi Beats'],
  ]},
  { key: 'game', name: 'Game Music', short: 'Game', styles: [
    ['title',     'Title Screen'],
    ['overworld', 'Overworld'],
    ['town',      'Town & Village'],
    ['battle',    'Battle'],
    ['boss',      'Boss Battle'],
    ['dungeon',   'Dungeon'],
    ['shop',      'Shop / Inn'],
    ['victory',   'Victory Fanfare'],
    ['gameover',  'Game Over'],
    ['puzzle',    'Puzzle'],
    ['stealth',   'Stealth'],
    ['chiptune',  'Chiptune 8-bit'],
  ]},
  { key: 'ceremony', name: 'Ceremonial & Seasonal', short: 'Ceremonial', styles: [
    ['fanfare',    'Fanfare'],
    ['anthem',     'Anthem'],
    ['hymn',       'Hymn'],
    ['carol',      'Christmas Carol'],
    ['halloween',  'Halloween'],
    ['wedding',    'Wedding Processional'],
    ['birthday',   'Birthday'],
    ['graduation', 'Graduation'],
    ['memorial',   'Memorial / Requiem'],
    ['newyear',    'New Year'],
  ]},
  { key: 'popular', name: 'Popular Forms', short: 'Popular', styles: [
    ['ballad',    'Pop Ballad'],
    ['hook',      'Pop Hook'],
    ['rockriff',  'Rock Riff'],
    ['blues',     'Blues'],
    ['jazz',      'Jazz Standard'],
    ['swing',     'Swing'],
    ['ragtime',   'Ragtime'],
    ['gospel',    'Gospel'],
    ['country',   'Country'],
    ['reggae',    'Reggae'],
    ['synthwave', 'Synthwave'],
    ['edm',       'EDM Anthem'],
    ['hiphop',    'Hip-hop Instrumental'],
    ['funk',      'Funk Groove'],
  ]},
];

// Styles a runner can actually produce today, per family. A key listed here gets
// the live composer board; everything else gets the empty board. Keep it in step
// with kanban_server._KM_FAMILIES and bp_pipeline_api._MEL_WIRED_CHILDREN — the
// three lists are the same contract seen from the menu, the library and the
// status feed.
const MELODY_WIRED = {
  children: ['playtime', 'sleeptime', 'storytime', 'learning', 'lullaby',
             'nursery', 'counting', 'singalong', 'animals', 'seasons',
             'bedtime'],
  // CINEMATIC IS INSTRUMENTAL (2026-09-06). Same live composer board, minus two
  // things that do not exist for a cinematic cue: the Pictures column (there is
  // no picture leg — that is the children's-video pipeline) and the Lyrics card
  // (nothing is sung, so no syllable budget is written and no lyric is passed
  // to ACE-Step). Everything else — the card `prompt` strings above all — stays
  // byte-identical to T.kidsmusic, because those strings are the join keys with
  // KANBAN_STAGE_MAP in bp_pipeline_api.py. The picture stages simply never
  // match a card on these boards, which is the intended no-op.
  cinematic: ['cheerful', 'sad', 'heroic', 'tavern', 'storytime', 'sonata',
              'suspense', 'romance', 'wonder', 'mystery', 'chase',
              'melancholy', 'triumph'],
};
// '<family>/<style>' → why it is not there. Dimmed and inert in the flyout.
const MELODY_EXCLUDED = {
  'children/dance': 'Action & Dance-along — excluded by operator decision 2026-09-06',
};
// lead / pad / bass, per wired children's style — the sampled instruments the
// composer voices that style with. Named on the Song Brief card so the board
// says which arrangement is coming before a note is written.
// MIRROR OF kids_music_theory.STYLES[key]['voices']. It is duplicated here
// rather than fetched because the board draws the brief card before any run
// exists to ask; the cost of that is that a voice changed there must be changed
// here in the same commit, or the board names an arrangement nobody plays.
// Four entries moved 2026-09-06 (sleeptime, learning, lullaby, nursery) to clear
// the sampler mix gate — see tools/measure_style_margins.py.
const MELODY_CHILD_VOICES = {
  playtime:  ['xylophone',     'guitar_nylon', 'double_bass_pizz'],
  sleeptime: ['recorder_alto', 'harp',         'cello_pizz'],
  storytime: ['recorder',      'guitar_nylon', 'double_bass_pizz'],
  learning:  ['xylophone',     'guitar_nylon', 'double_bass_pizz'],
  lullaby:   ['hand_chimes',   'strings_sus',  'cello_pizz'],
  nursery:   ['ukulele',       'piano',        'cello_pizz'],
  counting:  ['marimba',       'guitar_steel', 'bass_electric'],
  singalong: ['harmonica',     'guitar_steel', 'double_bass_pizz'],
  animals:   ['clarinet',      'guitar_nylon', 'tuba'],
  seasons:   ['flute',         'harp',         'cello'],
  bedtime:   ['vibraphone',    'piano',        'double_bass_pizz'],
};
// lead / pad / bass / extra, per cinematic style — four voices rather than the
// children's three, because with no sung line carrying the tune the arrangement
// has to. Named on the Song Brief card for the same reason as the children's
// table: the board says which orchestration is coming before a note is written.
const MELODY_CINE_VOICES = {
  cheerful:   ['flute',        'strings_pizz',  'double_bass_pizz',  'glockenspiel'],
  sad:        ['cello',        'strings_sus',   'double_bass',       'piano'],
  heroic:     ['french_horn',  'strings_sus',   'double_bass',       'trumpet'],
  tavern:     ['recorder_alto','lute',          'cello_pizz',        'harpsichord'],
  storytime:  ['oboe',         'harp',          'cello',             'piano'],
  sonata:     ['grand_piano',  'grand_piano',   'grand_piano',       'violin'],
  suspense:   ['cello',        'strings_sus_low','contrabass_pizz',   'vibraphone'],
  romance:    ['violin',       'strings_sus',   'cello',             'piano'],
  wonder:     ['glockenspiel', 'harp',          'strings_sus_low',   'flute'],
  mystery:    ['oboe',         'harpsichord',   'contrabass_pizz',   'vibraphone'],
  chase:      ['trumpet',      'strings_spic',  'contrabass_pizz',   'marimba'],
  melancholy: ['piano',        'strings_sus',   'cello',             'oboe'],
  triumph:    ['trumpet',      'organ_full',    'tuba',              'strings_sus'],
};

function _melodyKey(famKey, styleKey) { return 'mel_' + famKey + '_' + styleKey; }

(function _addMelodyTemplates(T) {
  // Empty board, pipeline_kidsmusic's stage ids so a wired runner's stage
  // strings land on the right column without the board being re-cut.
  function _mel(name, label) {
    return {
      name, label,
      columns: [
        { id: 'brief',   name: 'Brief',   cards: [] },
        { id: 'compose', name: 'Compose', cards: [] },
        { id: 'render',  name: 'Render',  cards: [] },
        { id: 'produce', name: 'Produce', cards: [] },
        { id: 'deliver', name: 'Deliver', cards: [] },
      ],
    };
  }
  // A wired style's board IS the live composer board. Deep-cloned, never shared:
  // applyPipelineStatus stamps card status onto the built board's objects, so a
  // shared card object would leak one style's run onto every other style.
  // Nothing but the two per-style lines below is touched — above all not a card
  // `prompt`, which is the join key with bp_pipeline_api's KANBAN_STAGE_MAP.
  function _melLive(name, label, styleKey, styleLabel) {
    const b = JSON.parse(JSON.stringify(T.kidsmusic));
    b.name = name;
    b.label = label;
    const v = MELODY_CHILD_VOICES[styleKey] || [];
    b.columns.forEach(function(col) {
      (col.cards || []).forEach(function(card) {
        if (card.prompt === 'Song Brief' && v.length) {
          const li = '<li>Style: ' + styleLabel + ' \u2014 voices ' + v.join('/')
                   + ' from the sampled instruments library</li>';
          const d = String((card.meta || {}).description || '');
          const i = d.lastIndexOf('</ul>');
          card.meta.description = i < 0 ? d + '<ul>' + li + '</ul>'
                                        : d.slice(0, i) + li + d.slice(i);
        } else if (card.prompt === 'Score Render') {
          card.agent = 'melody_sampler.py + instruments library '
                     + '(SoundFont for percussion and ACE conditioning)';
        }
      });
    });
    return b;
  }
  // A cinematic style's board is the same live composer board with the two
  // sung/illustrated parts CUT, not renamed: the Pictures column and the Lyrics
  // card. Cutting rather than blanking is the point — a card that can never
  // light is indistinguishable from a stalled run, which is why the empty
  // boards exist as empty boards instead of stalled clones.
  const _CINE_COLS = ['brief', 'compose', 'render', 'produce', 'deliver'];
  function _melCine(name, label, styleKey, styleLabel) {
    const b = JSON.parse(JSON.stringify(T.kidsmusic));
    b.name = name;
    b.label = label;
    b.columns = (b.columns || []).filter(
      c => _CINE_COLS.indexOf(c.id) >= 0);
    const v = MELODY_CINE_VOICES[styleKey] || [];
    b.columns.forEach(function(col) {
      col.cards = (col.cards || []).filter(c => c.prompt !== 'Lyrics');
      col.cards.forEach(function(card) {
        if (card.prompt === 'Song Brief' && v.length) {
          const li = '<li>Style: ' + styleLabel + ' \u2014 instrumental; voices '
                   + v.slice(0, 3).join('/') + ' + ' + v[3] + '</li>';
          const d = String((card.meta || {}).description || '');
          const i = d.lastIndexOf('</ul>');
          card.meta.description = i < 0 ? d + '<ul>' + li + '</ul>'
                                        : d.slice(0, i) + li + d.slice(i);
        } else if (card.prompt === 'Produced Track (ACE-Step)') {
          // ACE-Step is handed a caption and no lyric on these boards; say so
          // where the operator reads what the produce leg is about to do.
          const d = String((card.meta || {}).description || '');
          card.meta.description = d.replace(
            '<li>', '<li>Instrumental caption \u2014 no lyrics are passed; ');
        }
      });
    });
    return b;
  }
  MELODY_FAMILIES.forEach(function(fam) {
    const wired = MELODY_WIRED[fam.key] || [];
    const build = fam.key === 'cinematic' ? _melCine : _melLive;
    fam.styles.forEach(function(s) {
      const name  = fam.short + ' — ' + s[1];   // cinematic: 'Cinematic — <label>'
      const label = '[ MELODIES › ' + fam.name.toUpperCase() + ' › '
                  + s[1].toUpperCase() + ' ]';
      T[_melodyKey(fam.key, s[0])] = wired.indexOf(s[0]) >= 0
        ? build(name, label, s[0], s[1])
        : _mel(name, label);
    });
  });
})(TEMPLATES);

// ── Model-family specific Kanban templates ────────────────────────────────────
// We keep FLUX as the historical baseline (TEMPLATES) and build an SDXL variant
// by cloning and overriding only the stages that differ (image generation + any
// FLUX-only continuity steps).
function _deepClone(obj) { return JSON.parse(JSON.stringify(obj)); }

const TEMPLATES_SDXL = (function() {
  const t = _deepClone(TEMPLATES);

  // DOCUMENTARY pipeline: swap the FLUX still generation card to SDXL (Juggernaut).
  try {
    const cols = (t.documentary || {}).columns || [];
    cols.forEach(col => {
      (col.cards || []).forEach(card => {
        if (card.prompt === 'FLUX.1-schnell Image Generation') {
          card.prompt = 'SDXL Image Generation';
          card.agent  = 'SDXL (Juggernaut XL v9)';
          card.meta = {
            description: '<p><strong>Generates one cinematic keyframe image per scene using SDXL (Juggernaut XL).</strong></p><ul><li>Checkpoint: Juggernaut XL v9 (SDXL)</li><li>Workflow: <code>sdxl_txt2img</code> via ComfyUI</li><li>Goal: more reliable photoreal human rendering</li></ul>',
            llms:  ['SDXL Juggernaut XL v9 (local)'],
            tools: ['ComfyUI SDXL workflow (sdxl_txt2img)', 'CheckpointLoaderSimple', 'KSampler (DPM++ 2M Karras)', 'VAE Decode'],
          };
        }
      });
    });
  } catch {}

  // VIDEO pipeline: swap the FLUX still generation card to SDXL (Juggernaut).
  try {
    const cols = (t.video || {}).columns || [];
    cols.forEach(col => {
      (col.cards || []).forEach(card => {
        if (card.prompt === 'Qwen-2512 Image Generation') {
          card.prompt = 'SDXL Image Generation';
          card.agent  = 'SDXL (Juggernaut XL v9)';
          card.meta = {
            description: '<p><strong>Generates one keyframe image per scene using SDXL (Juggernaut XL).</strong></p><ul><li>Checkpoint: Juggernaut XL v9 (SDXL)</li><li>Workflow: <code>sdxl_txt2img</code> via ComfyUI</li><li>Purpose: more reliable photoreal human rendering vs FLUX (at the cost of a slower stack)</li><li>Identity: InstantID (<code>sdxl_character_instantid</code>) when enabled in the bible, or a staged character SDXL LoRA (<code>sdxl_character_locked</code>); PuLID/IPAdapter remain FLUX-only</li></ul>',
            llms:  ['SDXL Juggernaut XL v9 (local)'],
            tools: ['ComfyUI (CheckpointLoaderSimple + KSampler + VAE Decode)', 'SDXL checkpoint (models/checkpoints)', 'CUDA VRAM manager'],
          };
        }
        if (card.prompt === 'FLUX img2img Scene Chaining') {
          card.prompt = 'SDXL Scene Chaining (not enabled)';
          card.agent  = '—';
          card.meta = {
            description: '<p><strong>Scene chaining is currently implemented with FLUX img2img.</strong></p><ul><li>In SDXL mode this card is a placeholder until an SDXL img2img chaining workflow is added.</li><li>The pipeline will still run without chaining (stitched scenes).</li></ul>',
            llms: ['—'],
            tools: ['—'],
          };
        }
      });
    });
  } catch {}

  // MANGA pipeline: swap FLUX panel card to SDXL when viewing SDXL family board.
  try {
    const cols = (t.manga || {}).columns || [];
    cols.forEach(col => {
      (col.cards || []).forEach(card => {
        if (card.prompt === 'Qwen-2512 Image Generation') {
          card.prompt = 'SDXL Image Generation';
          card.agent  = 'SDXL (Juggernaut XL v9)';
        }
      });
    });
  } catch {}

  // STORYTELLER pipeline: swap the scene still generation card to SDXL.
  try {
    const cols = (t.storyteller || {}).columns || [];
    cols.forEach(col => {
      (col.cards || []).forEach(card => {
        if (card.prompt === 'FLUX + Character LoRA') {
          card.prompt = 'SDXL Image Generation';
          card.agent  = 'SDXL (Juggernaut XL v9)';
          card.meta = {
            description: '<p><strong>Generates one still image per story scene using SDXL.</strong></p><ul><li>Checkpoint: aligned to the character LoRA — SDXL base 1.0, or DynaVision XL for animated characters (Juggernaut XL v9 only for LoRA-less photoreal renders)</li><li>Workflow: <code>sdxl_character_locked</code> when a character SDXL LoRA is staged, else <code>sdxl_txt2img</code> via ComfyUI</li><li>Note: FLUX-trained character LoRAs do not apply to SDXL — identity lock is the trained <code>character_sdxl_lora</code>, with InstantID (<code>sdxl_character_instantid</code>) as opt-in fallback.</li></ul>',
            llms:  ['SDXL base 1.0 / DynaVision XL / Juggernaut XL v9 (local)'],
            tools: ['ComfyUI SDXL workflow', 'CheckpointLoaderSimple', 'KSampler (DPM++ 2M Karras)', 'VAE Decode'],
          };
        }
        if (card.prompt === 'IPAdapter Face Injection (LoRA fallback)') {
          card.prompt = 'InstantID Identity Lock (optional)';
          card.agent  = 'ComfyUI InstantID';
          card.meta = {
            description: '<p><strong>Optional identity lock for SDXL scenes.</strong></p><ul><li>Uses InstantID nodes (<code>sdxl_character_instantid</code>) when <code>instantid_enabled</code> is set in the character bible and the nodes are available on ComfyUI.</li><li>PuLID has no SDXL code path in this stack (FLUX-only).</li><li>Stronger face consistency than prompt-only generation.</li></ul>',
            llms: ['—'],
            tools: ['ComfyUI_InstantID', 'InsightFace (onnxruntime-gpu)'],
          };
        }
      });
    });
  } catch {}

  // CHARACTER CREATION (SDXL board): clarify FLUX LoRA vs SDXL previews.
  try {
    const cols = (t.character_creation || {}).columns || [];
    const loraCol = cols.find(c => c.id === 'lora');
    if (loraCol && Array.isArray(loraCol.cards)) {
      loraCol.cards.forEach(card => {
        if (card.prompt === 'SimpleTuner FLUX LoRA Training') {
          card.prompt = 'SimpleTuner SDXL LoRA Training';
          card.agent  = 'SimpleTuner on DynaVision XL (SDXL)';
          card.meta = {
            description: '<p><strong>Stage 1c — SDXL LoRA on your Blender dataset (~7–10 min).</strong></p><ul><li>Trains <code>character_sdxl_lora</code> via SimpleTuner on the pinned DynaVision XL train base (<code>ZYG_SDXL_TRAIN_CHECKPOINT</code>; reverts to SDXL base 1.0 when <code>ZYG_SDXL_ANIMATED=0</code>)</li><li>Stage 1d previews and SDXL story stills use this LoRA (+ InstantID when enabled)</li></ul>',
            llms: ['SDXL DynaVision XL (training base)'],
            tools: ['lora_trainer_service.py', 'SimpleTuner (train.py)', 'model_family=sdxl'],
          };
        }
      });
      const hasSdxlPrev = loraCol.cards.some(c => c.prompt === 'SDXL Preview Render');
      if (!hasSdxlPrev) {
        loraCol.cards.unshift({
          prompt: 'SDXL Preview Render',
          agent: 'SDXL (Juggernaut XL v9)',
          meta: {
            description: '<p><strong>Stage 1d — SDXL previews only (~seconds).</strong></p><ul><li>Outputs <code>preview_sdxl_front.png</code> + <code>preview_sdxl_face.png</code> (legacy copies as <code>preview_flux_*.png</code>)</li><li>InstantID or img2img reference when enabled in bible</li><li>Animated style uses illustration-tuned prompts (not photoreal Juggernaut defaults)</li></ul>',
            llms: ['SDXL DynaVision XL / aligned base 1.0 / Juggernaut XL v9 (local)'],
            tools: ['sdxl_character_locked', 'sdxl_txt2img', 'sdxl_character_instantid', 'sdxl_img2img', 'generate_character_preview_still'],
          },
        });
      }
    }
  } catch {}

  return t;
})();

function _getSelectedFamily() {
  const el = document.getElementById('kb-model-family-select');
  const v = (el && el.value ? el.value : '').toLowerCase();
  return (v === 'flux') ? 'flux' : 'sdxl';
}

function _getTemplatesForFamily(family) {
  return family === 'flux' ? TEMPLATES : TEMPLATES_SDXL;
}

let _activeTemplate = 'documentary'; // what the live pipeline is
let _viewedTemplate = 'documentary'; // what's rendered (may differ)
let _activeModelFamily = '';         // flux | sdxl for the live pipeline
let _viewPinned     = false;         // true = user manually selected a template
let _viewedFamily   = 'sdxl';        // default view: SDXL
let _familyPinned   = false;         // user manually selected FLUX/SDXL

/* Build mutable STAGES + JOBS arrays from a template key */
const STAGES = [];
const JOBS   = [];

function _buildFromTemplate(key) {
  // Medusa is a fully-isolated, FLUX-only workflow controlled solely by the Medusa
  // app — the shared model-family (FLUX/SDXL) view must never change or drive it.
  const family = (key === 'medusa')
    ? 'flux' : (_viewedFamily || _getSelectedFamily());
  const famTemplates = _getTemplatesForFamily(family);
  // `|| TEMPLATES[key]` before the documentary fallbacks: family-independent boards
  // (second_ledger is Wan2.1+VACE, neither FLUX nor SDXL) exist only in the base
  // TEMPLATES, and without this they silently render as the documentary board.
  const tmpl = famTemplates[key] || TEMPLATES[key] || famTemplates.documentary || TEMPLATES.documentary;
  STAGES.length = 0;
  JOBS.length   = 0;
  tmpl.columns.forEach(col => {
    STAGES.push({ id: col.id, name: col.name });
    col.cards.forEach(card => {
      JOBS.push({
        id:       randId(),
        stage:    col.id,
        prompt:   card.prompt,
        status:   'queued',
        agent:    card.agent,
        meta:     card.meta || null,
        progress: 0,
        /* Filled from the poll's card_times; null until the server reports a
           timeline row for this card.  These replaced `created`/`duration`,
           which were initialised to 0 and never written by applyPipelineStatus,
           so the card dialog always read "0s ago" and "0s". */
        since_s:   null,
        elapsed_s: null,
        started_at: null,
        gpu:      '—',
        logs:     generateLogs('queued'),
      });
    });
  });
  const labelEl = document.getElementById('kb-pipeline-label');
  // innerHTML, not textContent: _romanHtml escapes the label and then wraps a
  // trailing roman numeral in .kb-roman so '[ 2D CHARACTER BASICS I ]' gets the
  // steel numeral. Every other label is unchanged text.
  if (labelEl) labelEl.innerHTML = _romanHtml(tmpl.label);
}

function _syncDropdown() {
  const sel = document.getElementById('kb-template-select');
  if (sel) sel.value = _viewedTemplate;
  const badge    = document.getElementById('kb-live-badge');
  const badgeName = document.getElementById('kb-live-badge-name');
  const famTmpl = _getTemplatesForFamily(_viewedFamily || _getSelectedFamily());
  const activeName = ((famTmpl[_activeTemplate] && famTmpl[_activeTemplate].name)
    || (TEMPLATES[_activeTemplate] && TEMPLATES[_activeTemplate].name)
    || _activeTemplate);
  if (badge) badge.style.display = (_viewedTemplate !== _activeTemplate && !_pipelineIdle) ? '' : 'none';
  if (badgeName) badgeName.textContent = activeName;
  // Sync custom channel picker label + active highlight
  const chLabel = document.getElementById('kb-ch-label');
  if (chLabel) {
    const viewName = (famTmpl[_viewedTemplate] && famTmpl[_viewedTemplate].name)
      || (TEMPLATES[_viewedTemplate] && TEMPLATES[_viewedTemplate].name)
      || _viewedTemplate;
    chLabel.innerHTML = _romanHtml(viewName);
  }
  document.querySelectorAll('#kb-ch-menu [data-key]').forEach(function(el) {
    el.classList.toggle('active', el.dataset.key === _viewedTemplate);
  });
  _char2dRunVisible();
}

/* 2026-09-16: the Run button belongs to ONE board. Both entry points into a
   view (_selectTemplate for a click, _syncDropdown for a deep link / the
   auto-follow of the live pipeline) end by calling this, so the button cannot
   be left visible on a board that has no runner. */
function _char2dRunVisible() {
  const b = document.getElementById('kb-char2d-run');
  if (b) b.style.display = (_viewedTemplate === 'char2d_basics_1') ? '' : 'none';
}

/* POSTs a one-line character brief to :8899, which forwards it to the :5000
   pipeline API. The parse of the line happens server-side — the GUI stays a
   dumb courier so the accepted syntax lives in one place. */
function _char2dRun() {
  const brief = prompt('Character brief — name, gender (0 female … 1 male), age, height m, hair cut (bob|short|long), colours as hex skin/hair/top/bottom; e.g.\nMika, 0.2, 19, 1.68, bob, #f5cfb5 #2a1a12 #3b5fa3 #2b2f3a',
    'Mika, 0.2, 19, 1.68, bob, #f5cfb5 #2a1a12 #3b5fa3 #2b2f3a');
  if (!brief) return;
  fetch('/inspect/api/char2d/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ directive: brief }),
  })
    .then(r => r.json().then(d => ({ ok: r.ok, d })))
    .then(res => {
      alert(res.ok ? ('Started job ' + (res.d.job_id || res.d.pipeline_id))
                   : ('Could not start: ' + (res.d.error || 'unknown')));
    })
    .catch(e => alert('Could not start: ' + e));
}

function _goToActiveBoard() {
  if (_pipelineIdle || !_activeTemplate) return;
  _viewedTemplate = _activeTemplate;
  _viewPinned = false;
  if (_activeModelFamily === 'flux' || _activeModelFamily === 'sdxl') {
    _viewedFamily = _activeModelFamily;
    const famSel = document.getElementById('kb-model-family-select');
    if (famSel) famSel.value = _activeModelFamily;
  }
  const tplSel = document.getElementById('kb-template-select');
  if (tplSel) tplSel.value = _viewedTemplate;
  _buildFromTemplate(_viewedTemplate);
  _ltLastCards = {};
  _syncDropdown();
  pollPipeline();
}

let _isTestRun = false;
function _updateTestBadge(isTest) {
  const el = document.getElementById('kb-test-badge');
  if (!el) return;
  _isTestRun = !!isTest;
  el.style.display = _isTestRun ? '' : 'none';
}

function generateLogs(status) {
  const lines = [];
  lines.push({ cls: 'log-info', text: '[00:00.000] Job received — queued for dispatch' });
  lines.push({ cls: 'log-info', text: '[00:01.230] Worker assigned — checking GPU headroom' });
  if (status !== 'queued') {
    lines.push({ cls: 'log-info', text: '[00:02.100] Stage started — loading model weights' });
    lines.push({ cls: 'log-warn', text: '[00:04.800] VRAM allocation — offloading layer 12→CPU' });
  }
  if (status === 'done') {
    lines.push({ cls: 'log-done', text: '[00:38.400] Inference complete — 42 steps' });
    lines.push({ cls: 'log-done', text: '[00:39.100] Output saved — /outputs/job_xyz.mp4' });
    lines.push({ cls: 'log-done', text: '[00:39.200] ✓ Job completed successfully' });
  } else if (status === 'running') {
    lines.push({ cls: 'log-info', text: '[00:18.300] Inference in progress — step 24/42' });
    lines.push({ cls: 'log-warn', text: '[00:18.900] Throughput: 1.8 it/s (target 2.0)' });
  } else if (status === 'error') {
    lines.push({ cls: 'log-error', text: '[00:11.200] CUDA OOM — retry attempt 1/3' });
    lines.push({ cls: 'log-error', text: '[00:12.800] CUDA OOM — retry attempt 2/3' });
    lines.push({ cls: 'log-error', text: '[00:14.300] ✗ Fatal: out of memory — job aborted' });
  }
  return lines;
}

/* ── Telemetry circles — silver/white style matching Clipfarm workflow chart ─── */
const TELEM = [
  /* val is CAPACITY used, not NVML's utilization.gpu. utilization.gpu is a duty
     cycle — the share of the sample window with a kernel resident — so it reads
     high on an idle card that has downclocked to 210 MHz of 3105. val scales it
     by the clock ratio; the raw duty cycle is kept in .duty for the hover panel. */
  { id: 'gpu',  name: 'GPU',  val: 0,  temp: 0,  fan: 0,
    duty: 0, clk: null, clkMax: null, clkPct: null,
    powerW: null, powerCapW: null, procs: [], stale: false,
    row1: () => `${TELEM[0].temp.toFixed(1)}°C`,
    row2: () => `${TELEM[0].fan}% Fan` },
  { id: 'cpu',  name: 'CPU',  val: 0,  temp: 0,  ghz: 0,  cpuMax: 100,
    row1: () => `${TELEM[1].temp.toFixed(1)}°C`,
    row2: () => `${TELEM[1].ghz.toFixed(2)} GHz` },
  { id: 'vram', name: 'VRAM', val: 0,  usedG: 0, totalG: 48,
    row1: () => `${TELEM[2].usedG.toFixed(1)}/${TELEM[2].totalG}G`,
    row2: () => `${TELEM[2].val.toFixed(1)}%` },
  { id: 'ram',  name: 'RAM',  val: 0,  usedG: 0, totalG: 64,
    row1: () => `${TELEM[3].usedG.toFixed(1)}/${TELEM[3].totalG}G`,
    row2: () => `${TELEM[3].val.toFixed(1)}%` },
];
const R    = 44;
const CIRC = 2 * Math.PI * R;

/* Cyan accent gradient for telemetry rings (Creator Nexus navy theme) */
function silverGradDefs(id) {
  return `<defs>
    <linearGradient id="sg-${id}" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%"   stop-color="#4a7ab5"/>
      <stop offset="45%"  stop-color="#6dc6ff"/>
      <stop offset="100%" stop-color="#89dbff"/>
    </linearGradient>
  </defs>`;
}

function mainLabel(t) {
  if (t.id === 'vram') return `${t.usedG.toFixed(1)}/${t.totalG}G`;
  if (t.id === 'ram')  return `${t.usedG.toFixed(1)}/${t.totalG}G`;
  if (t.id === 'cpu')  return `${t.val.toFixed(1)}/${t.cpuMax}%`;
  return `${t.val.toFixed(1)}%`;
}

/** Snap psutil total (~62.6 GB on a 64 GB box) to nearest standard DIMM size. */
function ramTotalGBFromMb(totalMb) {
  if (!totalMb || totalMb <= 0) return 64;
  const gb = totalMb / 1024;
  const standard = [8, 16, 24, 32, 48, 64, 96, 128, 192, 256, 512];
  let best = Math.round(gb);
  let bestDiff = Infinity;
  for (const s of standard) {
    const diff = Math.abs(s - gb);
    if (diff < bestDiff) { bestDiff = diff; best = s; }
  }
  return bestDiff <= 8 ? best : Math.round(gb);
}

function buildTelemetry() {
  const bar = document.getElementById('kb-telemetry');
  bar.innerHTML = TELEM.map(t => {
    const offset = CIRC * (1 - t.val / 100);
    return `
      <div class="kb-telem-item">
        <div class="kb-telem-pop" id="telem-pop-${t.id}"></div>
        <div class="kb-telem-ring">
          <svg width="108" height="108" viewBox="0 0 108 108">
            ${silverGradDefs(t.id)}
            <circle class="kb-telem-bg"    cx="54" cy="54" r="53"/>
            <circle class="kb-telem-track" cx="54" cy="54" r="${R}"/>
            <circle class="kb-telem-fill"
              id="telem-fill-${t.id}"
              cx="54" cy="54" r="${R}"
              stroke="url(#sg-${t.id})"
              stroke-dasharray="${CIRC.toFixed(2)}"
              stroke-dashoffset="${offset.toFixed(2)}"/>
          </svg>
          <div class="kb-telem-val">
            <span class="kb-telem-name">${t.name}</span>
            <span class="kb-telem-main" id="telem-main-${t.id}">${mainLabel(t)}</span>
            <span class="kb-telem-row"  id="telem-r1-${t.id}">${t.row1()}</span>
            <span class="kb-telem-row"  id="telem-r2-${t.id}">${t.row2()}</span>
          </div>
        </div>
      </div>`;
  }).join('');
}

/* ── Hover breakdowns — "where is it going?" for every ring ─────────────────
   The GPU panel answers the two numbers that disagree (the duty cycle the driver
   reports and the capacity that actually implies) and the per-process split
   behind it. CPU, RAM and VRAM answer the same question from the process table
   the backend samples every 3 s. Pure CSS handles show/hide on hover; these
   only fill the content on each telemetry tick. */
let TELEM_RAW = null;          // newest /api/telemetry payload, for the panels

function fmtVram(mb) {
  if (mb == null || mb <= 0) return '—';
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
}

function _popNum(v, dp = 1) {
  return (v == null || isNaN(v)) ? '—' : Number(v).toFixed(dp);
}

function _popEsc(v) {
  return String(v == null ? '' : v).replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function _popTable(head, rows, emptyMsg) {
  if (!rows.length) return `<div class="kb-pop-dim">${_popEsc(emptyMsg)}</div>`;
  return `<table class="kb-pop-table"><thead><tr>${
    head.map(h => `<th>${_popEsc(h)}</th>`).join('')}</tr></thead><tbody>${
    rows.join('')}</tbody></table>`;
}

function _popUnreachable(el, title) {
  el.innerHTML = `<div class="kb-pop-title">${title}</div>
    <div class="kb-pop-note">Telemetry unreachable — the ring is showing a fallback.</div>`;
}

/* CPU: the figure is on the 0–<threads>00 scale (2400% on this box), so the
   panel says outright what the ceiling is and how many cores that means. */
function renderCpuBreakdown() {
  const el = document.getElementById('telem-pop-cpu');
  if (!el) return;
  const t = TELEM[1];
  const d = TELEM_RAW;
  if (!d) { _popUnreachable(el, "CPU — where it's going"); return; }
  const max = d.cpu_pct_max || t.cpuMax;
  const cores = d.cpu_count || Math.round(max / 100);
  const la = d.load_avg || [];
  const rows = (d.cpu_procs || []).map(p => `
    <tr>
      <td class="kb-pop-proc" title="pid ${_popEsc(p.pid)}">${_popEsc(p.label)}</td>
      <td class="kb-pop-num">${_popNum(p.cpu_pct)}%</td>
      <td class="kb-pop-num">${fmtVram(p.rss_mb)}</td>
    </tr>`).join('');
  el.innerHTML = `
    <div class="kb-pop-title">CPU — where it's going</div>
    <dl class="kb-pop-stats">
      <dt>In use</dt><dd class="kb-pop-strong">${_popNum(d.cpu_pct)}% of ${max}%</dd>
      <dt>Cores busy</dt><dd>${_popNum((d.cpu_pct || 0) / 100)} of ${cores} threads${
        d.cpu_count_physical ? ` <span class="kb-pop-dim">(${d.cpu_count_physical} physical)</span>` : ''}</dd>
      <dt>Load average</dt><dd>${la.length
        ? `${la.map(v => _popNum(v, 2)).join(' / ')} <span class="kb-pop-dim">1 / 5 / 15 min</span>`
        : '—'}</dd>
      <dt>Temperature</dt><dd>${d.cpu_temp_c != null ? `${_popNum(d.cpu_temp_c)} °C` : '—'}</dd>
      <dt>Clock</dt><dd>${d.cpu_freq_mhz != null ? `${_popNum(d.cpu_freq_mhz / 1000, 2)} GHz` : '—'}</dd>
    </dl>
    ${_popTable(['Process', 'CPU', 'RAM'], rows ? [rows] : [],
      d.cpu_procs ? 'Nothing above 0.5% — the box is idle.' : 'Sampling the process table…')}
    <div class="kb-pop-note">${cores} threads is ${max}%. Agent work is pinned to cores 0–19
      (2000% between all of it); the services keep all ${cores}.</div>`;
}

function renderRamBreakdown() {
  const el = document.getElementById('telem-pop-ram');
  if (!el) return;
  const d = TELEM_RAW;
  if (!d) { _popUnreachable(el, "RAM — where it's going"); return; }
  const rows = (d.ram_procs || []).map(p => `
    <tr>
      <td class="kb-pop-proc" title="pid ${_popEsc(p.pid)}">${_popEsc(p.label)}</td>
      <td class="kb-pop-num">${fmtVram(p.rss_mb)}</td>
      <td class="kb-pop-num">${_popNum(p.cpu_pct)}%</td>
    </tr>`).join('');
  el.innerHTML = `
    <div class="kb-pop-title">RAM — where it's going</div>
    <dl class="kb-pop-stats">
      <dt>In use</dt><dd class="kb-pop-strong">${_popNum(d.ram_pct)}%</dd>
      <dt>Used</dt><dd>${_popNum((d.ram_used_mb || 0) / 1024)} / ${
        _popNum((d.ram_total_mb || 0) / 1024)} GB</dd>
      <dt>Processes</dt><dd>${d.proc_count != null ? d.proc_count : '—'}</dd>
    </dl>
    ${_popTable(['Process', 'Resident', 'CPU'], rows ? [rows] : [],
      d.ram_procs ? 'No process is holding memory.' : 'Sampling the process table…')}
    <div class="kb-pop-note">Resident set size per process. It double-counts shared pages, so
      the rows add up to more than the total in use.</div>`;
}

/* VRAM: the same NVML process list as the GPU panel, ordered by memory held —
   a model parked in VRAM shows here with no SM load at all. */
function renderVramBreakdown() {
  const el = document.getElementById('telem-pop-vram');
  if (!el) return;
  const t = TELEM[0];
  const d = TELEM_RAW;
  const g = d && d.gpus && d.gpus[0];
  if (!g) { _popUnreachable(el, 'VRAM — who is holding it'); return; }
  const procs = (g.processes || []).slice().sort((a, b) => (b.vram_mb || 0) - (a.vram_mb || 0));
  const rows = procs.map(p => `
    <tr>
      <td class="kb-pop-proc" title="pid ${_popEsc(p.pid)}">${_popEsc(p.label)}</td>
      <td class="kb-pop-num">${fmtVram(p.vram_mb)}</td>
      <td class="kb-pop-num">${_popEsc(p.kind || '—')}</td>
    </tr>`).join('');
  const used = g.memory_used_mb, total = g.memory_total_mb;
  el.innerHTML = `
    <div class="kb-pop-title">VRAM — who is holding it</div>
    <dl class="kb-pop-stats">
      <dt>In use</dt><dd class="kb-pop-strong">${fmtVram(used)} / ${fmtVram(total)}</dd>
      <dt>Share</dt><dd>${(used != null && total) ? `${_popNum(used / total * 100)}%` : '—'}</dd>
      <dt>Free</dt><dd>${(used != null && total) ? fmtVram(total - used) : '—'}</dd>
      ${d.comfy_vram_mb ? `<dt>ComfyUI</dt><dd>${fmtVram(d.comfy_vram_mb)}</dd>` : ''}
    </dl>
    ${_popTable(['Process', 'VRAM', 'Kind'], rows ? [rows] : [], 'No process is holding VRAM.')}
    <div class="kb-pop-note">A model parked in VRAM still shows here with no SM load — that is
      idle residency, not work.</div>`;
}

function renderTelemBreakdowns() {
  renderGpuBreakdown();
  renderCpuBreakdown();
  renderRamBreakdown();
  renderVramBreakdown();
}

function renderGpuBreakdown() {
  const el = document.getElementById('telem-pop-gpu');
  if (!el) return;
  const t = TELEM[0];
  if (t.stale) {
    el.innerHTML = `<div class="kb-pop-title">GPU — where it's going</div>
      <div class="kb-pop-note">Telemetry unreachable — the ring is showing a fallback.</div>`;
    return;
  }
  const clkTxt = (t.clk != null && t.clkMax)
    ? `${t.clk} / ${t.clkMax} MHz` : '—';
  const pwrTxt = (t.powerW != null)
    ? `${t.powerW.toFixed(1)} / ${t.powerCapW != null ? Math.round(t.powerCapW) : '?'} W` : '—';

  /* The gap that confuses everyone: a high duty cycle at idle clocks. */
  const idleClocks = (t.clkPct != null && t.clkPct < 25 && t.duty >= 10);

  const rows = (t.procs || []).map(p => `
    <tr>
      <td class="kb-pop-proc" title="pid ${p.pid}">${p.label}</td>
      <td class="kb-pop-num">${p.sm_pct > 0 ? p.sm_pct + '%' : '—'}</td>
      <td class="kb-pop-num">${p.dec_pct > 0 ? p.dec_pct + '%' : '—'}</td>
      <td class="kb-pop-num">${fmtVram(p.vram_mb)}</td>
    </tr>`).join('');

  el.innerHTML = `
    <div class="kb-pop-title">GPU — where it's going</div>
    <dl class="kb-pop-stats">
      <dt>Capacity used</dt><dd class="kb-pop-strong">${t.val.toFixed(1)}%</dd>
      <dt>Duty cycle</dt><dd>${t.duty.toFixed(1)}% <span class="kb-pop-dim">time with a kernel resident</span></dd>
      <dt>SM clock</dt><dd>${clkTxt}${t.clkPct != null ? ` <span class="kb-pop-dim">(${t.clkPct.toFixed(1)}% of max)</span>` : ''}</dd>
      <dt>Power</dt><dd>${pwrTxt}</dd>
    </dl>
    ${idleClocks ? `<div class="kb-pop-note">Card is at idle clocks. The duty cycle reads
      high because work at ${t.clk} MHz occupies more of each sample window — capacity
      used is ${t.val.toFixed(1)}%.</div>` : ''}
    <table class="kb-pop-table">
      <thead><tr><th>Process</th><th>SM</th><th>Dec</th><th>VRAM</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="4" class="kb-pop-dim">No process is holding the GPU.</td></tr>'}</tbody>
    </table>`;
}

function updateTelemetry() {
  fetch(`${FLASK_BASE}/api/telemetry`)
    .then(r => r.ok ? r.json() : null)
    .then(d => {
      if (!d) return;
      const gpu     = d.gpus && d.gpus[0];
      /* capacity_pct = duty cycle x (current SM clock / max SM clock). Falls back to
         the raw duty cycle on an older backend that does not send it. */
      const gpuPct  = gpu
        ? Math.round((gpu.capacity_pct != null ? gpu.capacity_pct : gpu.utilization_pct) * 10) / 10
        : TELEM[0].val;
      const gpuTemp = gpu && gpu.temperature_c != null ? gpu.temperature_c : TELEM[0].temp;
      const gpuFan  = gpu && gpu.fan_pct != null ? gpu.fan_pct : TELEM[0].fan;

      const cpuPct  = Math.round((d.cpu_pct || 0) * 10) / 10;
      const cpuTemp = d.cpu_temp_c != null ? d.cpu_temp_c : TELEM[1].temp;
      const cpuGhz  = d.cpu_freq_mhz != null ? d.cpu_freq_mhz / 1000 : TELEM[1].ghz;
      /* Ceiling comes from the backend's real thread count (2400% on this box).
         The old aggregate/per-core ratio guessed it, and guessed 100 whenever the
         box was idle enough for the ratio to be 0/0. The ratio stays as the only
         fallback for a backend that predates cpu_pct_max. */
      const cpuRaw  = d.cpu_pct_raw || 0;
      const coreCount = (cpuPct > 0 && cpuRaw > 0)
        ? Math.round(Math.round(cpuPct / cpuRaw) / 4) * 4
        : TELEM[1].cpuMax / 100;
      const cpuMax  = d.cpu_pct_max || Math.max(100, coreCount * 100);

      const usedMB  = gpu ? (gpu.memory_used_mb || 0) : 0;
      const totalMB = gpu ? (gpu.memory_total_mb || 24576) : 24576;
      const vramPct = Math.min(100, usedMB / totalMB * 100);
      const vramGB  = totalMB / 1024;

      const ramTotalMB = d.ram_total_mb || (TELEM[3].totalG * 1024);
      const ramTotalGB = ramTotalGBFromMb(ramTotalMB);
      const ramUsedGB  = d.ram_used_mb ? d.ram_used_mb / 1024 : 0;
      const ramPct     = ramTotalMB > 0
        ? Math.min(100, (d.ram_used_mb || 0) / ramTotalMB * 100)
        : (d.ram_pct || TELEM[3].val);

      /* Update TELEM state */
      TELEM[0].val = gpuPct; TELEM[0].temp = gpuTemp; TELEM[0].fan = gpuFan;
      TELEM[0].duty      = gpu && gpu.utilization_pct != null ? gpu.utilization_pct : gpuPct;
      TELEM[0].clk       = gpu ? gpu.clock_sm_mhz : null;
      TELEM[0].clkMax    = gpu ? gpu.clock_sm_max_mhz : null;
      TELEM[0].clkPct    = gpu ? gpu.clock_pct : null;
      TELEM[0].powerW    = gpu ? gpu.power_w : null;
      TELEM[0].powerCapW = gpu ? gpu.power_limit_w : null;
      TELEM[0].procs     = (gpu && gpu.processes) || [];
      TELEM[0].stale     = false;
      TELEM_RAW = d;
      renderTelemBreakdowns();
      TELEM[1].val = cpuPct; TELEM[1].temp = cpuTemp; TELEM[1].ghz = cpuGhz; TELEM[1].cpuMax = cpuMax;
      TELEM[2].val = vramPct; TELEM[2].usedG = usedMB/1024; TELEM[2].totalG = Math.round(totalMB/1024);
      TELEM[3].val = ramPct;  TELEM[3].usedG = ramUsedGB;   TELEM[3].totalG = ramTotalGB;

      /* Render updates */
      TELEM.forEach(t => {
        /* For CPU, arc fill = val/cpuMax*100 so it still fills 0–100% of the circle */
        const arcPct = (t.id === 'cpu') ? (t.val / t.cpuMax * 100) : t.val;
        const offset = CIRC * (1 - arcPct / 100);
        const fill  = document.getElementById(`telem-fill-${t.id}`);
        const main  = document.getElementById(`telem-main-${t.id}`);
        const r1    = document.getElementById(`telem-r1-${t.id}`);
        const r2    = document.getElementById(`telem-r2-${t.id}`);
        if (fill) fill.style.strokeDashoffset = offset.toFixed(2);
        if (main) main.textContent = mainLabel(t);
        if (r1)   r1.textContent = t.row1();
        if (r2)   r2.textContent = t.row2();
      });
      DBG.telemetryOk = true; DBG.telemetryAt = new Date().toLocaleTimeString();
      DBG.telemetryRaw = { gpu: d.gpus?.[0], cpu_pct: d.cpu_pct, ram_pct: ramPct, ram_total_mb: d.ram_total_mb, ram_used_mb: d.ram_used_mb };
      renderLiveTailTelem();
    })
    .catch(() => {
      DBG.telemetryOk = false;
      TELEM[0].stale = true;
      TELEM_RAW = null;
      renderTelemBreakdowns();
      /* Fallback: random walk if API unreachable */
      TELEM.forEach(t => {
        t.val = Math.min(t.id === 'cpu' ? t.cpuMax * 0.98 : 98, Math.max(8, t.val + randInt(-4, 4)));
        if (t.temp !== undefined) t.temp = Math.min(88, Math.max(38, t.temp + (Math.random()-0.5)*1.5));
        if (t.fan  !== undefined) t.fan  = Math.min(100, Math.max(20, t.fan + randInt(-2,2)));
        if (t.ghz  !== undefined) t.ghz  = Math.min(9, Math.max(3, t.ghz + (Math.random()-0.5)*0.25));
        const arcPct = (t.id === 'cpu') ? (t.val / t.cpuMax * 100) : t.val;
        const offset = CIRC * (1 - arcPct / 100);
        const fill  = document.getElementById(`telem-fill-${t.id}`);
        const main  = document.getElementById(`telem-main-${t.id}`);
        const r1    = document.getElementById(`telem-r1-${t.id}`);
        const r2    = document.getElementById(`telem-r2-${t.id}`);
        if (fill) fill.style.strokeDashoffset = offset.toFixed(2);
        if (main) main.textContent = mainLabel(t);
        if (r1)   r1.textContent = t.row1();
        if (r2)   r2.textContent = t.row2();
      });
    });
}

/* ── Dialog ─────────────────────────────────────────────────────────────────── */
const FLASK_BASE = 'http://' + location.hostname + ':5000';

/* ── Pipeline activity messages — cycle through cards during active pipeline ── */
const PIPELINE_MESSAGES = [
  'Finding monkeys to harvest bananas.',
  'Do not underestimate the trolley problem analysis.',
  'Proper prior planning prevents piss poor performance.',
  'Where 10 men fight, karen is responsible.',
  'Monkeys are eating harvested bananas.',
  'Its not the water surrounding the boat that makes the boat sink,\nits the water that gets in.',
  'Enforce monkeys to deliver harvested bananas.',
  'We all know it can happen, nobody believes it will happen,\nbut it does happen.\n\n"A black Swan Event"',
  'Harvested bananas delivered, organizing stocks.',
  'Progression is like driving backwards on the highway.\n\n"Levi Harley"',
  'Fear not the man who practiced 10.000 kicks once,\nFear the man who has practiced one kick 10.000 times\n\n"Bruce Lee"',
  'Your production is complete.\nWe lost 2 monkeys.',
];
// ms each message stays (60s each, #11 stays until pipeline done)
const MSG_DURATION_MS = 60000;
let _msgIndex = 0;
let _msgTimer = null;
let _pipelineWasRunning = false;
let _pipelineFinished = false;

function _startMessageCycle() {
  _msgIndex = 0;
  _pipelineFinished = false;
  _advanceMessage();
}

function _advanceMessage() {
  clearTimeout(_msgTimer);
  // Message 11 (index 10) = Bruce Lee quote — stays until pipeline finishes
  if (_msgIndex === 10 && !_pipelineFinished) {
    // Keep showing #11, check again in 5s
    _msgTimer = setTimeout(_advanceMessage, 5000);
    return;
  }
  // Message 12 = completion — show once, then stop cycling
  if (_msgIndex >= PIPELINE_MESSAGES.length) return;
  _renderPipelineMessage(PIPELINE_MESSAGES[_msgIndex]);
  const next = _msgIndex + 1;
  if (next < PIPELINE_MESSAGES.length) {
    _msgIndex = next;
    if (next === 10) {
      // Will be held at #11 until pipeline done
      _msgTimer = setTimeout(_advanceMessage, MSG_DURATION_MS);
    } else if (next === 11) {
      // #12 (completion) — advance immediately only when pipeline just finished
      _msgTimer = null;
    } else {
      _msgTimer = setTimeout(_advanceMessage, MSG_DURATION_MS);
    }
  }
}

function _renderPipelineMessage(msg) {
  // Show message in every running/queued card's prompt area
  document.querySelectorAll('.kb-card-prompt span').forEach(promptEl => {
    promptEl.style.whiteSpace = 'pre-line';
    promptEl.textContent = msg;
  });
}

function _stopMessageCycle() {
  clearTimeout(_msgTimer);
  _msgTimer = null;
  // Restore original prompts
  JOBS.forEach(job => {
    const card = document.querySelector(`.kb-card[data-id="${job.id}"]`);
    if (card) {
      const promptEl = card.querySelector('.kb-card-prompt span');
      if (promptEl) {
        promptEl.style.whiteSpace = '';
        promptEl.textContent = job.prompt;
      }
    }
  });
}

/* ── Dialog tabs ─────────────────────────────────────────────────────────────── */
document.querySelectorAll('.dlg-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.dlg-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.dlg-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('dlg-panel-' + btn.dataset.tab).classList.add('active');
  });
});

function openDialog(job) {
  // Stop any previous live-update timer
  if (_dialogIntervalId) { clearInterval(_dialogIntervalId); _dialogIntervalId = null; }
  _openDialogJob = job;

  const stageName = STAGES.find(s => s.id === job.stage)?.name || job.stage;
  const logHtml   = job.logs.map(l => `<div class="${l.cls}">${l.text}</div>`).join('');

  document.getElementById('dlg-title').textContent = job.prompt;
  document.getElementById('dlg-stage').textContent = stageName;

  /* Reset tabs to Overview */
  document.querySelectorAll('.dlg-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.dlg-panel').forEach(p => p.classList.remove('active'));
  document.querySelector('.dlg-tab[data-tab="overview"]').classList.add('active');
  document.getElementById('dlg-panel-overview').classList.add('active');

  /* Overview tab — IDs on live fields so the interval can refresh them */
  document.getElementById('dlg-panel-overview').innerHTML = `
    <div class="kb-detail-row">
      <span class="kb-detail-label">Status</span>
      <span id="dlg-detail-status" class="kb-status-pill pill-${job.status}">${job.status.toUpperCase()}</span>
    </div>
    <div class="kb-detail-row">
      <span class="kb-detail-label">Agent</span>
      <span class="kb-detail-val">${job.agent}</span>
    </div>
    <div class="kb-detail-row">
      <span class="kb-detail-label">Duration</span>
      <span id="dlg-detail-duration" class="kb-detail-val">${fmtDuration(job.elapsed_s)}</span>
    </div>
    <div class="kb-detail-row">
      <span class="kb-detail-label">GPU</span>
      <span id="dlg-detail-gpu" class="kb-detail-val">${job.gpu}</span>
    </div>
    <div class="kb-detail-row">
      <span class="kb-detail-label">Started</span>
      <span id="dlg-detail-started" class="kb-detail-val">${timeAgoOrDash(job.since_s)}</span>
    </div>
    <div class="kb-log">${logHtml}</div>`;

  /* Start live refresh every second while dialog is open */
  _dialogIntervalId = setInterval(_updateDialogTimer, 1000);

  /* ── Rich tabs: render from embedded meta if available, else fetch from API ── */
  if (job.meta) {
    const m = job.meta;
    document.getElementById('dlg-panel-function').innerHTML =
      `<div class="dlg-rich" style="color:#c9d1d9;line-height:1.6;">${m.description || '—'}</div>`;
    document.getElementById('dlg-panel-agents').innerHTML =
      `<ul><li><strong style="color:#111;">${job.agent}</strong></li></ul>`;
    document.getElementById('dlg-panel-llms').innerHTML = (m.llms && m.llms.length && m.llms[0] !== '—')
      ? '<ul>' + m.llms.map(l => `<li style="color:#222;">${l}</li>`).join('') + '</ul>'
      : '<span style="color:#777;">No LLM required — pure compute stage.</span>';
    document.getElementById('dlg-panel-tools').innerHTML = (m.tools && m.tools.length)
      ? '<ul>' + m.tools.map(t => `<li style="color:#222;">${t}</li>`).join('') + '</ul>'
      : '<span style="color:#777;">No external tools assigned.</span>';
    document.getElementById('kb-dialog-overlay').classList.add('open');
    return;
  }

  /* Set loading state for rich tabs (API path) */
  ['function','agents','llms','tools'].forEach(tab => {
    const el = document.getElementById('dlg-panel-' + tab);
    el.innerHTML = '<span class="dlg-loading">Loading…</span>';
  });

  document.getElementById('kb-dialog-overlay').classList.add('open');

  /* Fetch rich info from Flask API (documentary pipeline agent configs) */
  fetch(`${FLASK_BASE}/api/workflow/steps/agents?step=${encodeURIComponent(job.prompt)}&chart=workflow_clipfarm`)
    .then(r => r.ok ? r.json() : null)
    .then(data => {
      if (!data) {
        ['function','agents','llms','tools'].forEach(tab => {
          document.getElementById('dlg-panel-' + tab).innerHTML = '<span style="color:#777;">No data available.</span>';
        });
        return;
      }

      /* Function tab */
      let funcHtml = data.function || '';
      if (funcHtml) {
        let badges = '';
        if (data.is_execution_only) badges += '<span class="dlg-badge dlg-badge-exec">EXECUTION ONLY</span>';
        if (data.orchestrated_by)   badges += `<span class="dlg-badge dlg-badge-by">Orchestrated by: ${data.orchestrated_by}</span>`;
        if (data.agents && data.agents[0]) badges += `<span class="dlg-badge dlg-badge-orch">Executor: ${data.agents[0].name || '—'}</span>`;
        if (badges) funcHtml = `<div style="margin-bottom:10px;">${badges}</div>` + funcHtml;
      } else {
        funcHtml = '<p>Function details can be configured per deployment.</p>';
      }
      document.getElementById('dlg-panel-function').innerHTML = funcHtml;

      /* Agents tab */
      const agents = data.agents || [];
      if (agents.length) {
        document.getElementById('dlg-panel-agents').innerHTML =
          '<ul>' + agents.map(a => {
            const role = a.role_type ? ` <span style="font-size:11px;color:#555;">(${a.role_type})</span>` : '';
            const desc = a.role ? ` – <span style="color:#444;">${a.role}</span>` : '';
            return `<li><strong style="color:#111;">${a.name||'—'}</strong>${role}${desc}</li>`;
          }).join('') + '</ul>';
      } else {
        document.getElementById('dlg-panel-agents').innerHTML = '<span style="color:#777;">No agents assigned.</span>';
      }

      /* LLMs tab */
      const llms = data.llms || [];
      document.getElementById('dlg-panel-llms').innerHTML = llms.length
        ? '<ul>' + llms.map(m => `<li>${m}</li>`).join('') + '</ul>'
        : '<span style="color:#777;">No LLMs required.</span>';

      /* Tools tab */
      const tools = data.tools || [];
      document.getElementById('dlg-panel-tools').innerHTML = tools.length
        ? '<ul>' + tools.map(t => `<li>${t}</li>`).join('') + '</ul>'
        : '<span style="color:#777;">No tools assigned.</span>';
    })
    .catch(() => {
      ['function','agents','llms','tools'].forEach(tab => {
        document.getElementById('dlg-panel-' + tab).innerHTML = '<span style="color:#777;">Could not reach server.</span>';
      });
    });

  document.getElementById('kb-dialog-overlay').classList.add('open');
}

/* ── Dialog open/close + live timer ─────────────────────────────────────────── */
let _openDialogJob    = null;
let _dialogIntervalId = null;

function _updateDialogTimer() {
  if (!_openDialogJob) return;
  /* Both numbers are re-read from the job object, which pollPipeline rewrites
     from the server's card_times twice a second — the dialog never advances a
     clock of its own, so it cannot drift from the board. */
  const el = document.getElementById('dlg-detail-started');
  if (el) el.textContent = timeAgoOrDash(_openDialogJob.since_s);
  const du = document.getElementById('dlg-detail-duration');
  if (du) du.textContent = fmtDuration(_openDialogJob.elapsed_s);
  const gp = document.getElementById('dlg-detail-gpu');
  if (gp) gp.textContent = _openDialogJob.gpu;
  const st = document.getElementById('dlg-detail-status');
  if (st) {
    st.className = 'kb-status-pill pill-' + _openDialogJob.status;
    st.textContent = _openDialogJob.status.toUpperCase();
  }
}

function closeDialog() {
  document.getElementById('kb-dialog-overlay').classList.remove('open');
  if (_dialogIntervalId) { clearInterval(_dialogIntervalId); _dialogIntervalId = null; }
  _openDialogJob = null;
}

/* Close on Escape */
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDialog(); });

/* Click outside dialog box → close */
document.getElementById('kb-dialog-overlay').addEventListener('click', (e) => {
  if (e.target === document.getElementById('kb-dialog-overlay')) closeDialog();
});

/* ── Render ─────────────────────────────────────────────────────────────────── */
/* ── Multi-pipeline concurrent-run state ────────────────────────────────── */
// Hand-tuned palettes for the first 8 concurrent pipelines.
// Index 0 = primary (uses existing CSS vars). Indices 1-7 = alternates.
// Beyond index 7 the palette is DERIVED, not clamped — see pipelineColor().
// Clamping was the old behaviour and it lied: runs 8..N all painted as
// "RUN 8" in the same green, so a board running 40 pipelines looked like a
// board running 8 (operator, 2026-09-23).
const PIPELINE_COLORS = [
  { a:'#3d92f8', m:'#2878e8', b:'#1a58c4', border:'rgba(140,210,255,0.55)', peek:'#2878e8', label:'#42c8ff' },
  { a:'#10d9a8', m:'#0ab88b', b:'#07876a', border:'rgba(16,217,168,0.5)',   peek:'#0ab88b', label:'#0cd9a8' },
  { a:'#a78bfa', m:'#7c3aed', b:'#5b21b6', border:'rgba(167,139,250,0.5)', peek:'#7c3aed', label:'#a78bfa' },
  { a:'#fbbf24', m:'#d97706', b:'#b45309', border:'rgba(251,191,36,0.5)',  peek:'#d97706', label:'#fbbf24' },
  { a:'#fb7185', m:'#e11d48', b:'#be123c', border:'rgba(251,113,133,0.5)', peek:'#e11d48', label:'#fb7185' },
  { a:'#22d3ee', m:'#0891b2', b:'#0e7490', border:'rgba(34,211,238,0.5)',  peek:'#0891b2', label:'#22d3ee' },
  { a:'#a3e635', m:'#65a30d', b:'#4d7c0f', border:'rgba(163,230,53,0.5)', peek:'#65a30d', label:'#a3e635' },
  { a:'#f0abfc', m:'#c026d3', b:'#86198f', border:'rgba(240,171,252,0.5)', peek:'#c026d3', label:'#f0abfc' },
];


// Board ceiling: how many concurrent runs one card can show at once (the
// focused run's card + its peers). The API is capped to match.
const MAX_CONCURRENT_RUNS = 100;
// Up to this many runs in total, peers hang as full-width tabs under the card.
// More than this and they are packed into a grid instead, or a 100-run board
// would be ~1400px of tabs under every single card.
const PEEK_STACK_MAX = 9;

// Derived palette for pipeline indices past the hand-tuned eight. Golden-angle
// hue rotation keeps neighbouring run numbers visibly different instead of
// fading into one long gradient.
const _derivedColors = {};
function pipelineColor(idx) {
  if (idx < PIPELINE_COLORS.length) return PIPELINE_COLORS[idx];
  if (_derivedColors[idx]) return _derivedColors[idx];
  const hue = Math.round((idx * 137.508) % 360);
  const sat = 68 + ((idx * 7) % 18);          // 68-85%
  const c = {
    a:      `hsl(${hue},${sat}%,62%)`,
    m:      `hsl(${hue},${sat}%,46%)`,
    b:      `hsl(${hue},${sat}%,32%)`,
    border: `hsla(${hue},${sat}%,68%,0.5)`,
    peek:   `hsl(${hue},${sat}%,46%)`,
    label:  `hsl(${hue},${sat}%,70%)`,
  };
  _derivedColors[idx] = c;
  return c;
}

// All runs: [{pipeline_id, cards, colorIdx, user_name, topic}], index 0 = active/focused.
let _allRuns = [];
// pipeline_id of the run currently shown on top (null = use primary active job)
let _focusPipelineId = null;
// pipeline_id the operator pinned from an "also running" chip. _focusPipelineId
// stacks peers WITHIN one department's board; this one makes the server pick a
// different department's run as the board's subject entirely (2026-10-02).
let _pinnedRunId = null;
const KB_DEPT_LABEL = {scholarly:'Documentary', kidsmusic:"Children's Music",
  kidseries:"Kids Series", clipfarm:'Clipfarm', crime:'Crime', video:'Video',
  storyteller:'Storyteller', remix:'Remix', wardrobe:'Wardrobe', char2d:'2D Character',
  movement:'Movement', medusa:'Medusa'};

function _pinRun(pid) {
  _pinnedRunId = (_pinnedRunId === pid) ? null : pid;  // click again to unpin
  _focusPipelineId = null;
  if (typeof pollPipeline === 'function') pollPipeline();
}

function _renderOtherRuns(data) {
  const el = document.getElementById('kb-other-runs');
  if (!el) return;
  const runs = (data && data.other_runs) || [];
  if (!runs.length) { el.className = 'kb-other-runs'; el.innerHTML = ''; _pinnedRunId = null; return; }
  // If the pinned run finished it is no longer offered — drop the pin so the
  // board goes back to following the live one instead of freezing on a corpse.
  const focused = (data && data.focused_run) || '';
  if (_pinnedRunId && _pinnedRunId !== focused && !runs.some(r => r.pipeline_id === _pinnedRunId)) {
    _pinnedRunId = null;
  }
  el.className = 'kb-other-runs on';
  // data-pid + one delegated listener, never an inline onclick: the id would
  // otherwise be interpolated into a JS string inside an HTML attribute.
  let html = '<span class="kb-or-label">also running</span>';
  runs.forEach(function(r) {
    const dept  = KB_DEPT_LABEL[r.department] || (r.department || 'run');
    const stage = String(r.current_stage || r.status || '');
    const tip   = (r.topic ? r.topic + ' \u2014 ' : '') + String(r.pipeline_id || '').slice(0, 8) +
                  (stage ? ' \u00b7 ' + stage : '');
    html += '<span class="kb-or-chip" data-pid="' + _escHtml(r.pipeline_id) +
            '" title="' + _escHtml(tip) + '"><span class="kb-or-dot"></span>' + _escHtml(dept) +
            (stage ? ' \u00b7 ' + _escHtml(stage.length > 28 ? stage.slice(0, 28) + '\u2026' : stage) : '') +
            '</span>';
  });
  if (_pinnedRunId) {
    html += '<span class="kb-or-chip pinned" data-pid="">pinned \u2014 show live</span>';
  }
  el.innerHTML = html;
  el.querySelectorAll('.kb-or-chip').forEach(function(c) {
    c.addEventListener('click', function() { _pinRun(c.getAttribute('data-pid') || null); });
  });
}

function switchPipeline(pid) {
  if (_focusPipelineId === pid) return;
  _focusPipelineId = pid;
  // Apply the focused run's card statuses to JOBS
  const run = _allRuns.find(r => r.pipeline_id === pid);
  if (run) {
    JOBS.forEach(job => {
      const st = run.cards[job.prompt];
      job.status   = st || 'queued';
      job.progress = st === 'done' ? 100 : st === 'running' ? Math.max(job.progress, 5) : 0;
    });
  }
  renderBoard();
}

/* ── Medusa splash (2026-09-17) ───────────────────────────────────────────────
   The Medusa board is no longer a kanban board. Medusa is driven end to end
   from its own app on :5300 — these columns only ever mirrored a run that the
   operator was already watching over there — so the board area now shows the
   drawing, and the drawing itself carries the status: every snake in her hair
   is an independently masked layer, and they MOVE — each coil sliding along
   its own length on its own period — for exactly as long as a Medusa workflow
   is running. Idle, the drawing sits there perfectly still.

   2026-09-23: the movement replaced the drifting colours (operator's call).
   Nothing on this board is tinted now; the picture stays the grey drawing it
   was drawn as, and motion alone is the signal.

   "Running" means anything the Medusa app is doing on the operator's behalf: a
   character generation job, OR a request to Vicky or Victor inside that app —
   an assistant turn IS a Medusa workflow (operator, 2026-09-17). bp_medusa's
   /api/medusa/kanban_status reports both as `active`.

   The face is not a layer and never moves: the masks are baked by
   kanban_assets/medusa/bake_medusa_masks.py, which cuts the skin (and the eyes,
   brows and lips inside it) out before it labels anything. The movement is a
   CSS animation on each layer, so an idle board costs no JS and no repaint. */
const MDZ_DIR = 'kanban_assets/medusa/';
/* Bumped whenever bake_medusa_masks.py is re-run. The masks, sprites and
   manifest all keep their filenames across a bake, so without this a browser
   that has the board open keeps serving the previous bake's tongues out of
   its cache — the assets are read off disk with no restart, and a plain
   reload need not revalidate an image. */
const MDZ_V = '?v=3';

/* The rendered loop. Not one frame of it is model output: Wan2.2 I2V supplies
   the MOTION, measured out of it as optical flow, and the drawing itself is
   warped along that field — showing the render directly came back with the mane
   visibly re-drawn. See kanban_assets/medusa/README_loop.md. Served by a fixed
   route in kanban_server.py, NOT off MDZ_DIR: the static allowlist refuses .mp4
   on purpose and widening it would publish every mp4 under the crews source
   tree on 0.0.0.0. */
const MDZ_LOOP = '/medusa/loop.mp4';
let _mdzVideoOk = false;          // reset in _mdzWireVideo, i.e. once per DOM build
let _mdzActive = false;     // last known "a Medusa workflow is running"
let _mdzLabel  = '';

/* The region manifest is a .js assignment (window.MDZ_SNAKES), not JSON:
   kanban_server.py's static allowlist refuses .json on purpose, so a fetch
   would 404. Loaded on first sight of the board — every other board pays
   nothing for it. */
function _mdzLoadManifest(cb) {
  if (window.MDZ_SNAKES) { cb(window.MDZ_SNAKES); return; }
  let el = document.getElementById('mdz-manifest');
  if (!el) {
    el = document.createElement('script');
    el.id  = 'mdz-manifest';
    el.src = MDZ_DIR + 'snakes.js' + MDZ_V;
    document.head.appendChild(el);
  }
  // No masks -> the plain drawing, which is still the right picture.
  el.addEventListener('load', function () { if (window.MDZ_SNAKES) cb(window.MDZ_SNAKES); });
}

/* One deterministic pseudo-random draw per snake: same board on every reload,
   but no two snakes with the same walk. */
function _mdzRnd(i, salt) {
  const x = Math.sin((i + 1) * 12.9898 + salt * 78.233) * 43758.5453;
  return x - Math.floor(x);
}

/* ── How a flat drawing is made to curl ───────────────────────────────────────
   2026-09-23, second pass. The first one transformed each snake as a rigid
   patch — slide, tilt, and a scale-up that hid the footprint it left behind.
   The operator read that for what it was: the picture resizing here and there,
   not snakes moving. This one deforms each snake ALONG ITS OWN BODY.

   Every snake is cut out of the drawing once (its mask over the matching crop
   of medusa_base.jpg) and then, every frame, redrawn as a row of thin strips
   across its long axis, each strip displaced sideways by a sine wave that
   travels down the body. Strips are SHEARED, not just offset: each one carries
   the slope to its neighbour's displacement, so the strips meet exactly and the
   contour stays a smooth curve instead of a staircase. Nothing is ever scaled.

   The hole a moving cut-out leaves behind is solved once, at load, instead of
   being dodged every frame: the plate under the snakes is the drawing with the
   whole mane — the union of all 39 masks — replaced by a blurred, slightly
   darkened copy of itself. At rest the snakes cover that region exactly, so the
   plate is invisible and the canvas is the drawing, pixel for pixel; where a
   coil swings away, what shows through is soft dark mush, which is what the gap
   between two coils looks like in the drawing anyway.

   Amplitude scales with the snake's own thickness and is enveloped along the
   body: the end nearer the head is the root and barely moves, the free end
   swings. All 39 wave at once and none of them ever stops — a per-snake
   "breathe" factor bottoms out at 0.44, it never reaches zero. Measured: over a
   0.2 s step 37 of 39 snakes have pixels changing, over 0.5 s all 39.

   The tongues flick too (_mdzDrawTongue). They are baked the same way, but they
   could not be found the way a snake is — see the TONGUE_SEEDS block in
   bake_medusa_masks.py for why each one is seeded by hand. */
const MDZ_SLICE = 4;              // px of body per drawn strip

let _mdzScene = null;             // built once: plate, cut-outs, per-slice shape
let _mdzCtx   = null;
let _mdzRaf   = null;
let _mdzLastFrame = 0;

function _mdzCanvas(w, h) {
  const c = document.createElement('canvas');
  c.width = Math.max(1, w | 0); c.height = Math.max(1, h | 0);
  return c;
}

/* Loads the drawing and all 39 masks, then assembles. Everything is same-origin
   off :8899, so the masks can be read back with getImageData. */
function _mdzBuildScene(manifest, done) {
  const list  = (manifest && manifest.snakes) || [];
  const tlist = (manifest && manifest.tongues) || [];
  if (!list.length) return;
  const masks = new Array(list.length);
  const tspr  = new Array(tlist.length);
  const tpat  = new Array(tlist.length);
  const base  = new Image();
  let pending = list.length + tlist.length * 2 + 1, dead = false;
  function tick() {
    if (dead || --pending > 0) return;
    try { done(_mdzAssemble(manifest.w, manifest.h, list, base, masks, tlist, tspr, tpat)); }
    catch (e) { /* no scene -> the plain drawing, which is still the right picture */ }
  }
  function fail() { dead = true; }
  function load(src, into, i) {
    const im = new Image();
    into[i] = im;
    im.onload = tick; im.onerror = fail;
    im.src = src;
  }
  base.onload = tick; base.onerror = fail;
  base.src = MDZ_DIR + 'medusa_base.jpg' + MDZ_V;
  list.forEach(function (sn, i)  { load(MDZ_DIR + encodeURIComponent(sn.f) + MDZ_V, masks, i); });
  tlist.forEach(function (tn, i) { load(MDZ_DIR + encodeURIComponent(tn.f) + MDZ_V, tspr, i);
                                   load(MDZ_DIR + encodeURIComponent(tn.p) + MDZ_V, tpat, i); });
}

function _mdzAssemble(W, H, list, base, masks, tlist, tspr, tpat) {
  const uni = _mdzCanvas(W, H), ug = uni.getContext('2d');
  const snakes = [];
  list.forEach(function (sn, i) {
    const bx = Math.round(sn.x * W), by = Math.round(sn.y * H);
    const bw = Math.max(4, Math.round(sn.w * W)), bh = Math.max(4, Math.round(sn.h * H));
    ug.drawImage(masks[i], bx, by, bw, bh);                 // for the plate below
    const sp = _mdzCanvas(bw, bh), g = sp.getContext('2d');
    g.drawImage(base, bx, by, bw, bh, 0, 0, bw, bh);
    g.globalCompositeOperation = 'destination-in';
    g.drawImage(masks[i], 0, 0, bw, bh);
    snakes.push(_mdzShape(i, sp, masks[i], bx, by, bw, bh, W, H));
  });
  const plate = _mdzCanvas(W, H), pg = plate.getContext('2d');
  pg.drawImage(base, 0, 0, W, H);
  const fill = _mdzCanvas(W, H), fg = fill.getContext('2d');
  fg.filter = 'blur(3px) brightness(0.94)';
  fg.drawImage(base, 0, 0, W, H);
  fg.filter = 'none';
  fg.globalCompositeOperation = 'destination-in';
  fg.drawImage(uni, 0, 0);
  pg.drawImage(fill, 0, 0);
  // Each tongue's own rectangle, with the drawn tongue inpainted out of it
  // (baked by bake_medusa_masks.py). Stamped into the plate so that the ink
  // the page flicks is the only tongue in the picture — without this the
  // original would sit there under the moving one.
  const tongues = [];
  (tlist || []).forEach(function (tn, i) {
    if (!tspr[i] || !tspr[i].width) return;
    pg.drawImage(tpat[i], Math.round(tn.x * W), Math.round(tn.y * H));
    tongues.push(_mdzTongue(tn, tspr[i], i, W, H, snakes));
  });
  return { W: W, H: H, plate: plate, snakes: snakes, tongues: tongues };
}

/* A tongue flicks about the point where it leaves the mouth, along the axis the
   artist drew it on — both measured off the artwork at bake time: the anchor is
   the root of the drawn stroke pushed 5 px back under the lip, and the angle is
   the direction the stroke leaves the mouth on. It also rides whatever its own
   snake is doing: the tongue picks up its owner's wave displacement at the strip
   nearest the mouth, so a head that swings takes its tongue with it.

   The owner is baked (`tn.o`, an index into the snake list) rather than worked
   out here. Picking the snake whose BOX is nearest the anchor — what this did
   before — is wrong in a mane this dense: the boxes overlap several deep, and
   the nearest one is routinely a coil passing in front of the head, so a tongue
   rode a body that had nothing to do with it. The box search is kept only as a
   fallback for an older manifest with no `o`. */
function _mdzTongue(tn, sprite, i, W, H, snakes) {
  const ax = tn.ax * W, ay = tn.ay * H;
  let own = (tn.o >= 0 && tn.o < snakes.length) ? snakes[tn.o] : null;
  if (!own) {
    let od = 1e9;
    for (const S of snakes) {
      const dx = Math.max(S.bx - ax, 0, ax - (S.bx + S.bw));
      const dy = Math.max(S.by - ay, 0, ay - (S.by + S.bh));
      const d = dx * dx + dy * dy;
      if (d < od) { od = d; own = S; }
    }
  }
  let slice = 0;
  if (own) {
    const along = own.horiz ? (ax - own.bx) : (ay - own.by);
    slice = Math.max(0, Math.min(own.n - 1, Math.round(along / MDZ_SLICE)));
  }
  const rx = Math.round(tn.x * W), ry = Math.round(tn.y * H);
  const ang = tn.ang * Math.PI / 180;
  // How far the tongue reaches along its own axis — the furthest corner of its
  // rectangle, projected onto that axis. That is how far it has to be pushed
  // back to be completely inside the mouth.
  let len = 1;
  for (const c of [[rx, ry], [rx + sprite.width, ry],
                   [rx, ry + sprite.height], [rx + sprite.width, ry + sprite.height]]) {
    len = Math.max(len, (c[0] - ax) * Math.cos(ang) + (c[1] - ay) * Math.sin(ang));
  }
  const period = 2.8 + _mdzRnd(i, 7) * 2.6;   // 2.8-5.4 s between flicks
  return {
    sprite: sprite, ax: ax, ay: ay, rx: rx, ry: ry, ang: ang, len: len + 4,
    own: own, slice: slice,
    period: period,
    win:    0.95 / period,              // ~0.95 s of flick, whatever the period
    phase:  _mdzRnd(i, 8),
  };
}

/* A tongue SLIDES out of the mouth and is snapped back in: it is clipped at the
   mouth and pushed back along its own axis, so what is not out yet is inside
   the head. The first cut scaled the sprite against the anchor instead, which
   squashed the fork flat as it retracted and faded it in and out like a ghost —
   the "unnatural" the operator saw. Nothing is scaled and nothing fades now.

   Out for about 0.95 s at a time, twice within that (a snake flicks in pairs),
   and then in for the rest of a 2.8-5.4 s cycle. Across eight tongues on their own
   phases that is one or two out at any moment, which is how a mane of snakes
   actually looks. The tongue also turns with its own head: it picks up both the
   displacement and the TILT of the strip its mouth sits on. */
function _mdzDrawTongue(ctx, T, t) {
  const ph = (t / T.period + T.phase) % 1;
  if (ph >= T.win) return;
  const u = ph / T.win;
  const base = Math.pow(Math.sin(Math.PI * u), 0.35);       // fast out, fast back
  const ext  = base * (0.80 + 0.20 * Math.cos(4 * Math.PI * u));
  if (ext <= 0.01) return;
  let dx = 0, dy = 0, tilt = 0;
  if (T.own && T.own.off) {
    const o = T.own.off, i = T.slice;
    const here = o[i] || 0;
    const sl = ((o[i + 1] === undefined ? here : o[i + 1]) - here) / MDZ_SLICE;
    if (T.own.horiz) { dy = here; tilt =  Math.atan(sl); }
    else             { dx = here; tilt = -Math.atan(sl); }
  }
  const sway = 0.09 * Math.sin(Math.PI * 2 * u);            // one gentle arc, no jitter
  ctx.save();
  ctx.translate(T.ax + dx, T.ay + dy);
  ctx.rotate(tilt + T.ang);                                 // +x now runs down the tongue
  ctx.beginPath();
  ctx.rect(-2, -T.len - 20, T.len + 24, 2 * T.len + 40);    // the mouth cuts it off
  ctx.clip();
  ctx.rotate(sway);
  ctx.translate(-(1 - ext) * T.len, 0);                     // slide it out of the mouth
  ctx.rotate(-T.ang);
  ctx.translate(-T.ax, -T.ay);
  ctx.drawImage(T.sprite, T.rx, T.ry);
  ctx.restore();
}

/* Per-strip centre line and thickness, read straight off the mask's alpha. A
   strip where the coil doubles back reads as one thick strip, which is right:
   both runs then travel together. */
function _mdzShape(i, sprite, mask, bx, by, bw, bh, W, H) {
  const mc = _mdzCanvas(bw, bh), mg = mc.getContext('2d');
  mg.drawImage(mask, 0, 0, bw, bh);
  const d = mg.getImageData(0, 0, bw, bh).data;
  const horiz = bw >= bh;
  const len = horiz ? bw : bh, cross = horiz ? bh : bw;
  const n = Math.max(2, Math.ceil(len / MDZ_SLICE));
  const thick = new Float32Array(n);
  const solid = [];
  for (let s = 0; s < n; s++) {
    const a0 = s * MDZ_SLICE, a1 = Math.min(len, a0 + MDZ_SLICE);
    let lo = 1e9, hi = -1;
    for (let a = a0; a < a1; a++) {
      for (let c = 0; c < cross; c++) {
        const x = horiz ? a : c, y = horiz ? c : a;
        if (d[(y * bw + x) * 4 + 3] > 110) { if (c < lo) lo = c; if (c > hi) hi = c; }
      }
    }
    thick[s] = hi < 0 ? 0 : (hi - lo + 1);
    if (thick[s] > 0) solid.push(thick[s]);
  }
  solid.sort(function (a, b) { return a - b; });
  const median = solid.length ? solid[solid.length >> 1] : 12;
  // Where the body narrows behind a head. A head is a bulge followed by a
  // thinner neck, so walking in from each end and stopping where the profile
  // has fallen to 80 % of the widest thing seen so far lands on the neck. The
  // strips beyond it are carried rigidly (see _mdzDrawSnake) — bending a head
  // is what made the snouts morph.
  const sm = new Float32Array(n);
  for (let s = 0; s < n; s++) {
    let acc = 0, cnt = 0;
    for (let k = -1; k <= 1; k++) {
      const j = s + k;
      if (j >= 0 && j < n && thick[j] > 0) { acc += thick[j]; cnt++; }
    }
    sm[s] = cnt ? acc / cnt : 0;
  }
  const stiff = Math.round(1.5 * median / MDZ_SLICE);   // strips a head occupies
  function neckFrom(fromStart) {
    const lim = Math.max(4, Math.round(n * 0.45));
    let peak = 0;
    for (let i = 0; i < lim; i++) {
      const v = sm[fromStart ? i : n - 1 - i];
      if (v <= 0) continue;
      if (v > peak) peak = v;
      if (i >= 3 && peak > 0 && v < peak * 0.80) return i;
    }
    return Math.min(6, Math.max(2, n >> 3));      // no head here: a short stiff tip
  }
  // The mane radiates from the head: whichever end of the body is nearer the
  // crown is the rooted one, and the far end is the one with a head on it.
  const ax = W / 2, ay = H * 0.40;
  const e0 = horiz ? [bx, by + bh / 2] : [bx + bw / 2, by];
  const e1 = horiz ? [bx + bw, by + bh / 2] : [bx + bw / 2, by + bh];
  const dist = function (e) { return (e[0] - ax) * (e[0] - ax) + (e[1] - ay) * (e[1] - ay); };
  return {
    sprite: sprite, bx: bx, by: by, bw: bw, bh: bh,
    horiz: horiz, len: len, n: n, thick: thick,
    rootAtStart: dist(e0) <= dist(e1),
    off: new Float32Array(n + 1),       // this frame's displacement, per strip;
                                        // the snake's tongue reads it too

    // Shallow and long. The first cut of this (0.30 of the thickness, up to two
    // waves at once) bent every body far enough to expose the plate behind it
    // and short enough to visibly deform the drawing; half that amplitude over
    // roughly one wave reads as a coil swaying, which is what a snake does.
    // A long thin coil can sway; a stubby piece is mostly head and barely moves.
    //
    // 2026-09-23, asked for more movement. The lever taken is SPEED and wave
    // count, not swing: a wave that crosses a body in 2.4-4.6 s instead of
    // 4.0-7.4 s, and 0.75-1.3 waves on it at once, is plainly livelier at a
    // glance, while displacement — the thing that exposes the plate behind a
    // coil and got 0.30 rejected — rises only from 0.16 to 0.22 of a body's
    // thickness (5.5 px ceiling -> 7.0).
    amp:    Math.min(7.0, Math.max(3.0, median * 0.22))
            * Math.max(0.50, Math.min(1.1, (len / Math.max(6, median)) / 4.2)),
    waves:  0.75 + _mdzRnd(i, 1) * 0.55,        // full waves down the body
    period: 2.4 + _mdzRnd(i, 2) * 2.2,          // seconds for one to travel it
    // Rigid ends. The neck is used when the profile shows one, but a region
    // that is ALL head (measured: the top-right head is a 140x39 piece, so no
    // 80 % narrowing exists inside it) has no neck to find, and that head was
    // the one still melting. A head is about one and a half body thicknesses
    // long, so that is the floor — never more than 45 % of the body each side.
    capA:   Math.min(Math.max(neckFrom(true),  stiff), Math.round(n * 0.45)),
    capB:   n - 1 - Math.min(Math.max(neckFrom(false), stiff), Math.round(n * 0.45)),
    phase:  _mdzRnd(i, 3) * Math.PI * 2,
    bRate:  0.50 + _mdzRnd(i, 4) * 0.45,        // the slow swell of the stroke
    bPhase: _mdzRnd(i, 5) * Math.PI * 2,
    // A second, shorter wave running at a different speed. One sine alone is a
    // metronome: every coil repeats the same arc on the same beat and the mane
    // reads as a mechanism. Two that do not share a period never quite repeat,
    // which is most of what "moving more" looks like — and it costs no extra
    // displacement, because the pair is normalised back to the same peak.
    phase2: _mdzRnd(i, 6) * Math.PI * 2,
  };
}

function _mdzDrawSnake(ctx, S, t) {
  const k = 2 * Math.PI * S.waves / S.n;
  const w = 2 * Math.PI / S.period;
  // Never zero: every snake is always moving, so a glance at the board always
  // catches the whole mane alive rather than a couple of twitching coils. The
  // floor is high (0.84) because a coil that all but stops for a few seconds is
  // exactly what "they hardly move" looks like.
  const breathe = 0.84 + 0.16 * Math.sin(t * S.bRate + S.bPhase);
  const k2 = k * 1.7, w2 = w * 1.45;            // the second wave: see _mdzShape
  const off = S.off;
  for (let s = 0; s <= S.n; s++) {
    const u = S.rootAtStart ? s / S.n : 1 - s / S.n;
    const wave = (Math.sin(k * s - w * t + S.phase)
                  + 0.38 * Math.sin(k2 * s - w2 * t + S.phase2)) / 1.38;
    off[s] = S.amp * breathe * (0.24 + 0.76 * u * u) * wave;
  }
  // Past the neck the displacement is continued as a straight line instead of a
  // curve: a constant slope across a run of strips is a uniform tilt, so the
  // head rides the neck and turns with it but never bends. Curving through a
  // head stretches the snout and smears the eye.
  const a = S.capA, b = S.capB;
  if (a > 0 && a < S.n) {
    const sl = off[a + 1] - off[a];
    for (let s = 0; s < a; s++) off[s] = off[a] - sl * (a - s);
  }
  if (b > 0 && b < S.n) {
    const sl = off[b] - off[b - 1];
    for (let s = b + 1; s <= S.n; s++) off[s] = off[b] + sl * (s - b);
  }
  for (let s = 0; s < S.n; s++) {
    if (S.thick[s] <= 0) continue;
    const a0 = s * MDZ_SLICE;
    const aw = Math.min(MDZ_SLICE + 1, S.len - a0);
    if (aw <= 0) continue;
    // Shear, not offset: the strip carries the slope to its neighbour, so the
    // two meet at exactly the same displacement and the body reads as one
    // curve. Offsetting alone leaves a 1-2 px staircase along every contour.
    const slope = (off[s + 1] - off[s]) / MDZ_SLICE;
    if (S.horiz) {
      const x0 = S.bx + a0;
      ctx.setTransform(1, slope, 0, 1, 0, off[s] - slope * x0);
      ctx.drawImage(S.sprite, a0, 0, aw, S.bh, x0, S.by, aw, S.bh);
    } else {
      const y0 = S.by + a0;
      ctx.setTransform(1, 0, slope, 1, off[s] - slope * y0, 0);
      ctx.drawImage(S.sprite, 0, a0, S.bw, aw, S.bx, y0, S.bw, aw);
    }
  }
  ctx.setTransform(1, 0, 0, 1, 0, 0);
}

function _mdzFrame(now) {
  _mdzRaf = requestAnimationFrame(_mdzFrame);
  if (document.hidden || !_mdzScene || !_mdzCtx) return;
  if (now - _mdzLastFrame < 32) return;          // 30 fps is plenty for a slow curl
  _mdzLastFrame = now;
  const sc = _mdzScene, t = now / 1000;
  _mdzCtx.setTransform(1, 0, 0, 1, 0, 0);
  _mdzCtx.clearRect(0, 0, sc.W, sc.H);
  _mdzCtx.drawImage(sc.plate, 0, 0);
  for (let i = 0; i < sc.snakes.length; i++) _mdzDrawSnake(_mdzCtx, sc.snakes[i], t);
  for (let i = 0; i < sc.tongues.length; i++) _mdzDrawTongue(_mdzCtx, sc.tongues[i], t);
}

/* The canvas is only ever painted while a workflow is live: idle, it is faded
   out and the untouched <img> under it is the board. Nothing runs. */
function _mdzAnimate(on) {
  if (on && !_mdzRaf && _mdzScene) { _mdzLastFrame = 0; _mdzRaf = requestAnimationFrame(_mdzFrame); }
  else if (!on && _mdzRaf) { cancelAnimationFrame(_mdzRaf); _mdzRaf = null; }
}

/* The video is the board's mane now; the canvas is what happens when it is not
   there. Any failure — 404, a codec this browser will not decode, a route that
   went away — drops back to the 39 cut-outs rather than leaving a dead board. */
function _mdzVideoFail(err) {
  // A play() aborted by our own pause() is not a failure: _mdzSetLive races it
  // on every idle edge and the promise rejects with AbortError.
  if (err && err.name === 'AbortError') return;
  _mdzVideoOk = false;
  const st = document.getElementById('mdz-stage');
  if (st) st.classList.remove('mdz-has-video');
  const v = document.getElementById('mdz-video');
  if (v) { try { v.pause(); } catch (e) {} v.style.display = 'none'; }
  _mdzAnimate(_mdzActive);
}

function _mdzWireVideo() {
  const v = document.getElementById('mdz-video');
  _mdzVideoOk = false;            // the stage may have been destroyed and rebuilt
  if (!v) return;
  v.muted = true;                 // the PROPERTY, not just the attribute: without
                                  // it play() rejects under the autoplay policy
  v.addEventListener('error', function () { _mdzVideoFail(v.error); });
  v.addEventListener('canplaythrough', function () {
    _mdzVideoOk = true;
    const st = document.getElementById('mdz-stage');
    if (st) st.classList.add('mdz-has-video');
    _mdzAnimate(false);           // the canvas has nothing left to do
    if (_mdzActive) { const p = v.play(); if (p && p.catch) p.catch(_mdzVideoFail); }
  }, { once: true });
}

/* "An idle board costs no JS and no repaint" has to keep holding. The canvas
   checks document.hidden every frame; a <video> does not, it just keeps
   decoding in a background tab. */
document.addEventListener('visibilitychange', function () {
  const v = document.getElementById('mdz-video');
  if (!v || !_mdzVideoOk) return;
  if (document.hidden) { try { v.pause(); } catch (e) {} }
  else if (_mdzActive) { const p = v.play(); if (p && p.catch) p.catch(_mdzVideoFail); }
});

function _mdzPaintSnakes(manifest) {
  const cv = document.getElementById('mdz-canvas');
  if (!cv || !manifest) return;
  cv.width = manifest.w; cv.height = manifest.h;
  _mdzCtx = cv.getContext('2d');
  _mdzBuildScene(manifest, function (scene) {
    _mdzScene = scene;
    _mdzFrame(performance.now());        // a first frame, so the fade has something
    // This callback is async — a <script> fetch plus ~47 image decodes — and it
    // usually lands AFTER the video's canplaythrough. Without the guard it
    // restarts the 30 fps canvas loop behind a playing video, for ever.
    _mdzAnimate(_mdzVideoOk ? false : _mdzActive);
  });
}

function _mdzSetLive(on, label) {
  _mdzActive = !!on;
  _mdzLabel  = label || '';
  const stage = document.getElementById('mdz-stage');
  if (!stage) return;
  stage.classList.toggle('is-live', _mdzActive);
  // Two clocks drive this — the ~2 s board render and the pipeline poll — so it
  // has to stay idempotent. Paused is zero decode, which is the idle contract.
  const vid = document.getElementById('mdz-video');
  if (vid && _mdzVideoOk) {
    if (_mdzActive) { const p = vid.play(); if (p && p.catch) p.catch(_mdzVideoFail); }
    else { vid.pause(); vid.currentTime = 0; }
  }
  _mdzAnimate(_mdzVideoOk ? false : _mdzActive);   // idle: the snakes settle back
  const chip = document.getElementById('mdz-status');
  if (chip) chip.classList.toggle('is-live', _mdzActive);
  const txt = document.getElementById('mdz-status-txt');
  if (txt) {
    txt.textContent = _mdzActive
      ? (_mdzLabel || 'Medusa workflow running')
      : 'Idle — no Medusa workflow running';
  }
  const badge = document.getElementById('total-badge');
  if (badge) badge.textContent = _mdzActive ? 'medusa · running' : 'medusa · idle';
}

/* Draws the splash into #kb-board. Called from renderBoard on every poll, so it
   builds the DOM once and then only touches the live state: rebuilding would
   restart all 39 hue animations from zero every two seconds. */
/* The stage fills everything under the header, so the blurred backdrop reaches
   the top and bottom edges instead of leaving bands of empty desk. Measured
   rather than hard-coded: the header's height moves with the zoom factor, and
   both readings below are in layout px (the zoom shim in kanban.html divides
   the screen-px ones back). */
function _mdzFit() {
  const stage = document.getElementById('mdz-stage');
  if (!stage) return;
  const top = stage.getBoundingClientRect().top;
  stage.style.height = Math.max(360, window.innerHeight - top) + 'px';
}
window.addEventListener('resize', _mdzFit);

/* Page mode: the blurred drawing spreads over the whole page, header included.
   Inside the dashboard (:5000/workflows) the frame goes transparent and the
   dashboard paints the backdrop under its own left tab list too — it only
   knows to because this page tells it. Cross-origin (:8899 in :5000), so it
   has to be a postMessage; the message carries nothing but on/off. */
const _mdzFramed = (window.self !== window.top);
function _mdzPageMode(on) {
  const root = document.documentElement;
  root.classList.toggle('mdz-page', !!on);
  root.classList.toggle('mdz-solo', !!on && !_mdzFramed);
  if (on && !document.getElementById('mdz-status')) {
    const chip = document.createElement('span');
    chip.id = 'mdz-status';
    chip.className = 'mdz-status';
    chip.innerHTML = '<i></i><span id="mdz-status-txt">Idle</span>';
    const pick = document.getElementById('kb-ch-picker-wrap');
    if (pick && pick.parentNode) pick.parentNode.insertBefore(chip, pick.nextSibling);
  }
  if (_mdzFramed) {
    try { window.parent.postMessage({ type: 'zyg_medusa_bg', on: !!on }, '*'); } catch (e) {}
  }
}

// A reloaded frame starts on some other board, and the dashboard would otherwise
// keep painting the backdrop from before the reload. Say "off" once up front;
// if the first board is Medusa, its render says "on" right after (in order).
if (_mdzFramed) {
  try { window.parent.postMessage({ type: 'zyg_medusa_bg', on: false }, '*'); } catch (e) {}
}

function _renderMedusaSplash() {
  _mdzPageMode(true);
  const board = document.getElementById('kb-board');
  const telem = document.getElementById('kb-telemetry');
  if (telem) telem.style.display = 'none';     // the picture gets the full width
  // The board's own title is the picture; the '[ MEDUSA — ... ]' strap line goes.
  const lbl = document.getElementById('kb-pipeline-label');
  if (lbl) lbl.style.display = 'none';
  board.classList.add('kb-board-medusa');
  if (!document.getElementById('mdz-stage')) {
    board.innerHTML =
        '<div class="mdz-stage" id="mdz-stage">'
      +   '<div class="mdz-pic">'
      +     '<img src="' + MDZ_DIR + 'medusa_base.jpg' + MDZ_V + '" alt="Medusa">'
      +     '<video class="mdz-video" id="mdz-video" muted loop playsinline'
      +           ' preload="auto" disablepictureinpicture'
      +           ' src="' + MDZ_LOOP + MDZ_V + '"></video>'
      +     '<canvas class="mdz-canvas" id="mdz-canvas"></canvas>'
      +   '</div>'
      + '</div>';
    _mdzWireVideo();                    // once per DOM build, not once per poll
    _mdzLoadManifest(_mdzPaintSnakes);  // kept: the canvas is the video's fallback
  }
  _mdzFit();
  _mdzSetLive(_mdzActive, _mdzLabel);
}

function renderBoard() {
  // Medusa is controlled solely by the Medusa app: hide the shared model-family
  // selector whenever its board is shown (covers reload / persisted-view too).
  var _mfs = document.getElementById('kb-model-family-select');
  if (_mfs) _mfs.style.display = (_viewedTemplate === 'medusa') ? 'none' : '';
  const board = document.getElementById('kb-board');
  if (_viewedTemplate === 'medusa') { _renderMedusaSplash(); return; }
  // Leaving the Medusa board: give the telemetry rail and the column layout back.
  if (board.classList.contains('kb-board-medusa')) {
    board.classList.remove('kb-board-medusa');
    _mdzPageMode(false);
    _mdzAnimate(false);             // leaving the board: the nodes go with it
    const _v = document.getElementById('mdz-video');
    // removeAttribute + load() is what actually stops the download; pause()
    // alone leaves a partially buffered stream fetching in the background.
    if (_v) { try { _v.pause(); _v.removeAttribute('src'); _v.load(); } catch (e) {} }
    const _tel = document.getElementById('kb-telemetry');
    if (_tel) _tel.style.display = '';
    const _lbl = document.getElementById('kb-pipeline-label');
    if (_lbl) _lbl.style.display = '';
  }
  board.innerHTML = '';

  // Empty blueprint (2026-09-16): a template with no columns would render as a
  // blank board with no explanation. Say so instead — but only for templates
  // that declare themselves a placeholder, so a genuinely empty STAGES from a
  // failed poll still looks broken rather than intentional.
  if (STAGES.length === 0) {
    const t = (_getTemplatesForFamily(_viewedFamily || _getSelectedFamily())[_viewedTemplate]
      || TEMPLATES[_viewedTemplate] || {});
    if (t.placeholder) {
      board.innerHTML = '<div class="kb-empty-blueprint">Empty blueprint placeholder — '
        + _kbEsc(t.name) + ' is not designed yet.</div>';
    }
  }

  let total = 0;
  const peekRuns = _allRuns.filter(r => r.pipeline_id !== (_focusPipelineId || (_allRuns[0] && _allRuns[0].pipeline_id)));

  STAGES.forEach(stage => {
    const jobs = JOBS.filter(j => j.stage === stage.id);
    total += jobs.length;

    const col = document.createElement('div');
    col.className = 'kb-column';
    col.innerHTML = `
      <div class="kb-column-head">
        <span class="kb-column-name">${stage.name}</span>
      </div>`;

    jobs.forEach(job => {
      const nPeeks = peekRuns.length;
      // 9 runs or fewer (the focused card + 8 peers) keep the stacked-tab look.
      // Past that the peers go into a grid under the card — see renderPeekGrid.
      const gridMode = (nPeeks + 1) > PEEK_STACK_MAX;

      // ── Wrapper stack ──
      const stack = document.createElement('div');
      stack.className = 'kb-stack' + (gridMode ? ' kb-stack-grid' : '');
      // Tabs are absolutely positioned, so the stack has to reserve their room:
      // margin (not padding) so peeks align flush with card bottom, not the gap
      // below. The grid is in normal flow and sizes itself, so it reserves none.
      stack.style.marginBottom = gridMode ? '' : (nPeeks * 14) + 'px';

      // ── Main card ──
      const card = document.createElement('div');
      card.className = `kb-card status-${job.status}`;
      card.dataset.id = job.id;

      // Apply focused pipeline color if not primary
      const focusRun = _focusPipelineId ? _allRuns.find(r => r.pipeline_id === _focusPipelineId) : _allRuns[0];
      const colorIdx = focusRun ? focusRun.colorIdx : 0;
      if (colorIdx > 0) {
        const c = pipelineColor(colorIdx);
        card.style.background = `linear-gradient(148deg,${c.a} 0%,${c.m} 42%,${c.b} 100%)`;
        card.style.borderColor = c.border;
        card.style.boxShadow   = `0 4px 18px ${c.peek}66,0 0 22px ${c.peek}33,inset 0 1px 0 rgba(255,255,255,0.25)`;
      }

      const progressBar = job.status === 'running'
        ? `<div class="kb-progress"><div class="kb-progress-fill" style="width:${job.progress}%"></div></div>`
        : '';

      card.innerHTML = `
        <div class="kb-quick-actions">
          <button class="kb-qa-btn" onclick="retryJob('${job.id}',event)">↺</button>
          <button class="kb-qa-btn" onclick="viewJob('${job.id}',event)">⤢</button>
          <button class="kb-qa-btn" onclick="cancelJob('${job.id}',event)">✕</button>
        </div>
        <div class="kb-card-prompt"><span>${job.prompt}</span></div>
        <div class="kb-card-meta">
          <span class="kb-status-pill pill-${job.status}">${job.status.toUpperCase()}</span>
        </div>
        ${progressBar}`;

      card.addEventListener('click', (e) => {
        if (e.target.closest('.kb-quick-actions')) return;
        openDialog(job);
      });

      stack.appendChild(card);

      // ── Peers: stacked tabs (≤9 runs) or a packed grid (>9 runs) ──
      if (gridMode) {
        stack.appendChild(buildPeekGrid(peekRuns, job));
      } else {
        peekRuns.forEach((run, idx) => {
          const c = pipelineColor(run.colorIdx);
          const peek = document.createElement('div');
          peek.className = 'kb-peek';
          peek.style.background = `linear-gradient(90deg,${c.b},${c.m},${c.a})`;
          peek.style.bottom      = `-${(idx + 1) * 14}px`;
          peek.style.zIndex      = String(10 - idx);
          peek.title = `Pipeline ${run.colorIdx + 1}${run.topic ? ': ' + run.topic.slice(0, 40) : ''}`;
          peek.innerHTML = `<span class="kb-peek-label">RUN ${run.colorIdx + 1}${run.topic ? ' · ' + run.topic.slice(0, 22) : ''}</span>`;
          peek.addEventListener('click', (e) => {
            e.stopPropagation();
            switchPipeline(run.pipeline_id);
          });
          stack.appendChild(peek);
        });
      }

      col.appendChild(stack);
    });

    board.appendChild(col);
  });

  document.getElementById('total-badge').textContent = total + ' jobs';
}

/* ── Peer-run grid (>9 concurrent runs) ──────────────────────────────────────
   One cell per concurrent run, packed into rows and columns under the card
   instead of a single column of full-width tabs. Cell background = that
   pipeline's colour (same identity as the stacked tabs, so switching views is
   the same click); the bar along the bottom of the cell = that run's status
   for THIS card, which is the thing a stacked tab could never show.
   Sized for up to MAX_CONCURRENT_RUNS cells under every card.
──────────────────────────────────────────────────────────────────────────── */
function _peekCellWidth(n) {
  if (n <= 24) return 30;
  if (n <= 48) return 26;
  return 22;
}

function buildPeekGrid(peekRuns, job) {
  const n    = peekRuns.length;
  const cw   = _peekCellWidth(n);
  const grid = document.createElement('div');
  grid.className = 'kb-peek-grid';
  grid.style.gridTemplateColumns = `repeat(auto-fill,minmax(${cw}px,1fr))`;

  peekRuns.forEach(run => {
    const c  = pipelineColor(run.colorIdx);
    const st = (run.cards && run.cards[job.prompt]) || 'queued';
    const cell = document.createElement('div');
    cell.className = 'kb-peek-cell st-' + st;
    cell.style.background = `linear-gradient(150deg,${c.a},${c.m} 55%,${c.b})`;
    cell.style.borderColor = c.border;
    cell.title = `RUN ${run.colorIdx + 1} — ${st.toUpperCase()}`
               + (run.topic ? `\n${run.topic.slice(0, 60)}` : '')
               + (run.user_name ? `\n${run.user_name}` : '');
    cell.innerHTML = `<span class="kb-peek-cell-n">${run.colorIdx + 1}</span>`;
    cell.addEventListener('click', (e) => {
      e.stopPropagation();
      switchPipeline(run.pipeline_id);
    });
    grid.appendChild(cell);
  });
  return grid;
}

/* ── Quick action handlers ──────────────────────────────────────────────────── */
function retryJob(id, e) {
  e.stopPropagation();
  const job = JOBS.find(j => j.id === id);
  if (!job) return;
  job.status = 'queued';
  job.progress = 0;
  job.logs = generateLogs('queued');
  renderBoard();
}

function cancelJob(id, e) {
  e.stopPropagation();
  const idx = JOBS.findIndex(j => j.id === id);
  if (idx !== -1) JOBS.splice(idx, 1);
  renderBoard();
}

function viewJob(id, e) {
  e.stopPropagation();
  const job = JOBS.find(j => j.id === id);
  if (job) openDialog(job);
}

/* ── Debug state ─────────────────────────────────────────────────────────────── */
const DBG = {
  telemetryOk: false, telemetryAt: null, telemetryRaw: null,
  pipelineOk:  false, pipelineAt:  null, pipelineRaw:  null,
  errors: [],
  events: [],
};

function dbgLog(msg) {
  const now  = new Date();
  const date = _ltFormatLocalDate(now);
  const time = _ltFormatLocalTime(now);
  DBG.errors.push({
    date,
    line: '[  ' + time + '  ]  ' + msg,
    sortKey: String(now.getTime()).padStart(15, '0'),
  });
  if (DBG.errors.length > 40) DBG.errors.shift();
  renderLiveTailDebug();
}

function _ltEventSortKey(item) {
  if (item && item.sortKey) return item.sortKey;
  const raw = (typeof item === 'object' ? (item.raw || item.line) : String(item)) || '';
  const m = raw.match(/\[(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})/);
  if (m) return m[1] + 'T' + m[2];
  const d = (typeof item === 'object' ? item.date : null) || '?';
  const t = (typeof item === 'object' ? item.line : String(item)).match(/\[\s*(\d{2}:\d{2}:\d{2})\s*\]/);
  return d + 'T' + (t ? t[1] : '00:00:00');
}

function _ltSortEvents(items) {
  return items.slice().sort(function(a, b) {
    const ka = _ltEventSortKey(a);
    const kb = _ltEventSortKey(b);
    if (ka === kb) return 0;
    return ka < kb ? -1 : 1;
  });
}

function _ltScrollPaneBottom(el) {
  if (!el) return;
  if (!el._ltScrollGuardSetup) {
    el._ltScrollGuardSetup = true;
    var _onInteract = function() { el._ltInteractAt = Date.now(); };
    el.addEventListener('mousedown',  _onInteract, {passive: true});
    el.addEventListener('wheel',      _onInteract, {passive: true});
    el.addEventListener('touchstart', _onInteract, {passive: true});
  }
  if (el._ltInteractAt && Date.now() - el._ltInteractAt < 5000) return;
  requestAnimationFrame(function() {
    el.scrollTop = el.scrollHeight;
    requestAnimationFrame(function() { el.scrollTop = el.scrollHeight; });
  });
}

function _ltFormatLocalTime(d) {
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  return hh + ':' + mm + ':' + ss;
}

function _ltFormatLocalDate(d) {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return yyyy + '-' + mm + '-' + dd;
}

function _ltParseApiEvent(e) {
  const raw = String(e);
  // Server emits timestamps in Europe/Amsterdam with an offset suffix:
  //   [YYYY-MM-DDTHH:MM:SS(.ffff)+02:00] [stage] msg
  // Older log lines may still be naive UTC (no offset) or have a Z suffix —
  // both are still accepted for backwards compatibility.
  const m = raw.match(/\[(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+\-]\d{2}:?\d{2})?\]/);
  let date, localTime, sortKey;
  if (m) {
    // If no explicit TZ marker, assume legacy UTC (server pre-2026 fix).
    const tz  = m[4] || 'Z';
    const iso = m[1] + 'T' + m[2] + (m[3] || '') + tz;
    const d = new Date(iso);
    if (!isNaN(d.getTime())) {
      date = _ltFormatLocalDate(d);
      localTime = _ltFormatLocalTime(d);
      // Sort by epoch ms so events stay in chronological order regardless of TZ
      sortKey = String(d.getTime()).padStart(15, '0');
    } else {
      date = m[1];
      localTime = m[2];
      sortKey = m[1] + 'T' + m[2];
    }
  } else {
    const now = new Date();
    date = _ltFormatLocalDate(now);
    localTime = _ltFormatLocalTime(now);
    sortKey = String(now.getTime()).padStart(15, '0');
  }
  const cleaned = raw.replace(
    /\[(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})[^\]]*\]/,
    '[  ' + localTime + '  ]'
  );
  return { date, line: cleaned, raw, sortKey };
}

function _ltAppendApiEventToLog(obj, cls) {
  const el = document.getElementById('lt-pane-log');
  if (!el) return;
  if (el.querySelector('[data-lt-raw="' + CSS.escape(obj.raw) + '"]')) return;
  if (obj.date !== _ltLastLogDate) {
    _ltLastLogDate = obj.date;
    const sep = document.createElement('div');
    sep.className = 'lt-line';
    sep.style.cssText = 'color:#6b7280;font-weight:700;margin-top:6px;margin-bottom:2px;font-size:10px;letter-spacing:0.05em;';
    sep.textContent = obj.date;
    el.appendChild(sep);
  }
  const line = document.createElement('div');
  line.className = 'lt-line ' + (cls || 'info');
  line.dataset.ltRaw = obj.raw;
  line.textContent = obj.line;
  el.appendChild(line);
  if (el.children.length > 400) el.removeChild(el.firstChild);
  _ltScrollPaneBottom(el);
}

function renderLiveTailDebug() {
  const p = document.getElementById('lt-pane-debug');
  if (!p || _ltTab !== 'debug') return;
  const fmtRaw = r => r
    ? `<pre style="color:#aaa;font-size:10px;white-space:pre-wrap;margin:2px 0;">${JSON.stringify(r,null,1).slice(0,500)}</pre>`
    : '<em style="color:#555">none</em>';

  // Group {date, line} objects by date; oldest first, newest at bottom
  function groupedLines(items, lineColor = '#fc8181') {
    if (!items.length) return '<em style="color:#555">none</em>';
    const sorted = _ltSortEvents(items);
    const groups = {};
    const order  = [];
    sorted.forEach(function(e) {
      const d = (typeof e === 'object' ? e.date : '?') || '?';
      if (!groups[d]) { groups[d] = []; order.push(d); }
      groups[d].push(typeof e === 'object' ? e.line : e);
    });
    return order.map(function(d) {
      return `<div style="color:#6b7280;font-weight:700;font-size:10px;margin-top:4px;">${d}</div>`
        + groups[d].map(l => `<div style="color:${lineColor};font-size:10px;margin-top:1px;">${l}</div>`).join('');
    }).join('');
  }

  p.innerHTML = `
    <div id="lt-dbg-live-wrap">
      <b style="color:#67e8f9">Live Log</b>
      <div id="lt-dbg-events" style="margin-top:2px;">
        ${groupedLines(DBG.events.slice(-30), '#a5f3fc')}
      </div>
      <hr style="border-color:#222;margin:6px 0">
      <b style="color:#f87171">Errors</b>
      ${groupedLines(DBG.errors.slice(-30))}
    </div>
    <div id="lt-dbg-meta-wrap">
      <div style="margin-bottom:6px;">
        <b style="color:#7ee8a2">Telemetry</b>
        <span style="color:#555;font-size:10px;margin-left:8px;">Last: ${DBG.telemetryAt||'—'}</span>
        <span style="float:right">${DBG.telemetryOk ? '<span style="color:#7ee8a2">● OK</span>' : '<span style="color:#f87171">● FAIL</span>'}</span>
      </div>
      ${fmtRaw(DBG.telemetryRaw)}
      <hr style="border-color:#222;margin:6px 0">
      <div style="margin-bottom:6px;">
        <b style="color:#7ee8a2">Pipeline</b>
        <span style="color:#555;font-size:10px;margin-left:8px;">Last: ${DBG.pipelineAt||'—'}</span>
        <span style="float:right">${DBG.pipelineOk ? '<span style="color:#7ee8a2">● OK</span>' : '<span style="color:#f87171">● FAIL</span>'}</span>
      </div>
      ${fmtRaw(DBG.pipelineRaw)}
    </div>
  `;
  _ltScrollPaneBottom(document.getElementById('lt-dbg-live-wrap'));
}

/* ── Real pipeline poller ────────────────────────────────────────────────────── */
/* When pipeline is IDLE keep cards on bright queued styling (not dim idle). */
let _pipelineIdle = true;

/* ── Operator review gate ────────────────────────────────────────────────────
   2026-08-26. A creature run parks at `awaiting_review` after the sheet and
   waits for a human. Nothing on this page said so: _updateActiveStatus() hides
   for any status that isn't 'running', _pipelineIdle goes true, auto-follow
   stops moving the view — so the board looked exactly like "nothing is
   happening" while a finished sheet waited for approval. The only documented
   way through the gate was a hand-written POST, printed in a card tooltip.
   The banner below is that POST, with the sheet attached to it. */
let _reviewGateKey = null;      // re-render only when the parked run changes
let _reviewGateBusy = false;

function _updateReviewGate(pipeline) {
  const el = document.getElementById('kb-review-gate');
  if (!el) return;
  const parked = pipeline && pipeline.review_pending && /^[a-f0-9]{12}$/.test(pipeline.job_id || '');
  if (!parked) {
    if (_reviewGateKey !== null) { el.style.display = 'none'; el.innerHTML = ''; _reviewGateKey = null; }
    return;
  }
  const key = pipeline.job_id + '|' + (pipeline.current_stage || '');
  if (key === _reviewGateKey) return;   // never rebuild under an in-flight click
  _reviewGateKey = key;
  _reviewGateBusy = false;

  const cid   = pipeline.job_id;
  const name  = (pipeline.topic || '').trim() || cid.slice(0, 8);
  const rep   = pipeline.sheet_report || {};
  const cells = rep.cell_count
    ? `${rep.pass_count}/${rep.cell_count} cells pass`
    : 'sheet ready';
  const judge = rep.judged_any === false
    ? ' <span style="color:#ffd46b;">· judge offline (structural + DINO only)</span>' : '';
  const sheet = '/api/kanban/creature/sheet?id=' + cid;
  el.style.display = 'block';
  el.innerHTML = `
    <div style="display:flex;gap:14px;align-items:center;margin:10px 16px;padding:12px 16px;
                background:rgba(255,212,107,0.07);border:1px solid rgba(255,212,107,0.34);
                border-radius:8px;">
      <a href="${sheet}" target="_blank" rel="noopener" title="Open the full sheet">
        <img src="${sheet}" alt="review sheet" style="height:82px;width:auto;max-width:180px;
             border-radius:5px;border:1px solid rgba(255,212,107,0.34);display:block;object-fit:cover;">
      </a>
      <div style="flex:1;min-width:0;">
        <div style="font-size:0.86rem;font-weight:700;color:#ffd46b;letter-spacing:0.01em;">
          ⏸ Sheet Review — awaiting your approval
        </div>
        <div style="font-size:0.8rem;color:#c9d1d9;margin-top:3px;overflow:hidden;text-overflow:ellipsis;">
          <b>${_escHtml(name)}</b> · ${_escHtml(cells)}${judge}
        </div>
        <div style="font-size:0.72rem;color:#8b949e;margin-top:3px;">
          Approve → captions + LoRA training. Reject → nothing trains; the dataset stays on disk.
          <a href="${sheet}" target="_blank" rel="noopener" style="color:#58a6ff;">open sheet ↗</a>
        </div>
      </div>
      <div style="display:flex;gap:8px;flex-shrink:0;">
        <button id="kb-review-approve" onclick="kbReviewDecide('approve')"
                style="background:#238636;color:#fff;border:0;border-radius:5px;padding:7px 15px;
                       font-weight:700;font-size:0.8rem;cursor:pointer;">✅ Approve</button>
        <button id="kb-review-reject" onclick="kbReviewDecide('reject')"
                style="background:transparent;color:#f85149;border:1px solid #f85149;border-radius:5px;
                       padding:7px 15px;font-weight:700;font-size:0.8rem;cursor:pointer;">✕ Reject</button>
      </div>
    </div>
    <div id="kb-review-msg" style="display:none;margin:-4px 16px 10px;font-size:0.78rem;"></div>`;
}

function _escHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function _reviewMsg(text, color) {
  const m = document.getElementById('kb-review-msg');
  if (!m) return;
  m.style.display = 'block';
  m.style.color = color;
  m.textContent = text;
}

/* Posts to THIS server (:8899), which forwards to the pipeline API on :5000 with
   the internal token — the page has no session there and the approve route must
   not be public: it starts a GPU training run. */
function kbReviewDecide(action) {
  if (_reviewGateBusy) return;
  const cid = (_reviewGateKey || '').split('|')[0];
  if (!cid) return;
  if (action === 'reject' &&
      !confirm('Reject this sheet? Nothing will train. The dataset stays on disk.')) return;
  _reviewGateBusy = true;
  ['kb-review-approve', 'kb-review-reject'].forEach(id => {
    const b = document.getElementById(id);
    if (b) { b.disabled = true; b.style.opacity = '0.5'; b.style.cursor = 'default'; }
  });
  _reviewMsg(action === 'approve' ? 'Approving — starting captions + LoRA training…'
                                  : 'Rejecting…', '#8b949e');
  fetch('/api/kanban/creature/decide', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: cid, action: action }),
  })
    .then(r => r.json().then(d => ({ ok: r.ok, d: d })))
    .then(({ ok, d }) => {
      if (ok && (d.success || d.ok)) {
        _reviewMsg(action === 'approve'
          ? '✅ Approved — training started. The board follows it from here.'
          : '✕ Rejected — nothing trains.', action === 'approve' ? '#3fb950' : '#f85149');
        _reviewGateKey = null;   // let the next poll clear or redraw the banner
      } else {
        _reviewGateBusy = false;
        ['kb-review-approve', 'kb-review-reject'].forEach(id => {
          const b = document.getElementById(id);
          if (b) { b.disabled = false; b.style.opacity = '1'; b.style.cursor = 'pointer'; }
        });
        _reviewMsg('Failed: ' + (d.error || 'unknown error'), '#f85149');
      }
    })
    .catch(err => {
      _reviewGateBusy = false;
      ['kb-review-approve', 'kb-review-reject'].forEach(id => {
        const b = document.getElementById(id);
        if (b) { b.disabled = false; b.style.opacity = '1'; b.style.cursor = 'pointer'; }
      });
      _reviewMsg('Request failed: ' + err, '#f85149');
    });
}

function _updateActiveStatus(pipeline) {
  const el = document.getElementById('kb-active-status');
  if (!el) return;
  // A run parked at the review gate is not running and not finished. It used to
  // fall into the "hide everything" branch, which is why an operator watching
  // this header saw a finished sheet as an empty board (2026-08-26).
  if (pipeline && pipeline.review_pending) {
    el.innerHTML = '<span style="color:#ffd46b;">'
      + (pipeline.current_stage || 'Awaiting operator review') + '</span>';
    el.style.display = 'inline';
    return;
  }
  if (!pipeline || pipeline.status !== 'running') {
    el.style.display = 'none';
    el.innerHTML = '';
    return;
  }
  const dept  = (pipeline.department || 'Documentary').replace(/\b\w/g, c => c.toUpperCase());
  const user  = pipeline.user_name || 'User';
  const url   = pipeline.url || '';
  let html = `<span style="color:#3fb950;">${dept} Active</span>, Generating request from <span style="color:#3fb950;">${user}</span>`;
  if ((pipeline.department || '').toLowerCase() === 'character_creation') {
    const mf = (pipeline.model_family || 'sdxl').toUpperCase();
    html = `<span style="color:#3fb950;">Character Creation (${mf})</span> — `
      + `1a–1b Blender/dataset · <strong>1c ${mf} LoRA</strong> · 1d ${mf} previews`;
  }
  if (url) {
    const display = url.length > 60 ? url.slice(0, 57) + '…' : url;
    html += ` <a href="${url}" target="_blank" rel="noopener" style="color:#3fb950;text-decoration:underline;word-break:break-all;">${display}</a>`;
  }
  el.innerHTML = html;
  el.style.display = 'inline';
}

function applyPipelineStatus(data) {
  const cards    = data.cards    || {};
  const pipeline = data.pipeline;

  // Build sports_video → Templates card map so the Templates board activates during a sv run
  const sv = data.sports_video || {};
  const svCardMap = {};
  if (_viewedTemplate === 'templates' && sv.state && sv.state !== 'idle') {
    const SV_ORDER = [
      'Template Request Parsing', 'Category & Pipeline Routing', 'Prompt Scaffolding',
      'Visual Test Render (if type=visual)', 'TTS Dry Run (if type=tts)',
      'Output QA Score', 'Category Tagging & Search Indexing', 'Activation & Pipeline Injection'
    ];
    const SV_STEP_IDX = {init:0,vram_check:1,build_template:2,render:3,tts:4,composite:5,cleanup:6,done:7,error:5};
    const curIdx = SV_STEP_IDX[sv.step] !== undefined ? SV_STEP_IDX[sv.step] : 0;
    SV_ORDER.forEach(function(name, idx) {
      if (sv.state === 'done') { svCardMap[name] = 'done'; }
      else if (idx < curIdx)   { svCardMap[name] = 'done'; }
      else if (idx === curIdx) { svCardMap[name] = sv.state === 'error' ? 'error' : 'running'; }
      else                     { svCardMap[name] = 'queued'; }
    });
  }
  // ── Build _allRuns for multi-pipeline stacking ──────────────────────────
  const primaryRun = {
    pipeline_id: (pipeline && pipeline.job_id) || 'primary',
    cards:       cards,
    colorIdx:    0,
    user_name:   pipeline && pipeline.user_name,
    topic:       pipeline && pipeline.topic,
  };
  // Client-side ceiling as well as the API's: the board draws one cell per
  // peer under EVERY card, so an unbounded list is a rendering hazard.
  const extraRuns = (data.concurrent_runs || []).slice(0, MAX_CONCURRENT_RUNS - 1).map((r, i) => ({
    pipeline_id: r.pipeline_id || ('run-' + i),
    cards:       r.cards || {},
    colorIdx:    i + 1,
    user_name:   r.user_name,
    topic:       r.topic,
  }));
  _allRuns = [primaryRun, ...extraRuns];
  // Peers in OTHER departments: named, never painted as cards on this board.
  _renderOtherRuns(data);

  // If focused pipeline is no longer in _allRuns, reset to primary
  if (_focusPipelineId && !_allRuns.find(r => r.pipeline_id === _focusPipelineId)) {
    _focusPipelineId = null;
  }

  // Medusa's /api/medusa/kanban_status returns `pipeline` as a bare char_id
  // STRING with `status`/`stage` as top-level sibling fields (bp_medusa.py),
  // not an object with its own .status like the shared /api/kanban/status
  // pipelines this idle-check was written for. Reading pipeline.status on a
  // string is always undefined, so this evaluated _pipelineIdle=true
  // unconditionally for Medusa — meaning a genuinely running Medusa job could
  // never render as running through honest polling (2026-08-06 fix).
  // A run parked at an operator gate is NOT idle — it is a live pipeline waiting
  // on a human. Reading it as idle forced every card on the board back to QUEUED
  // (the loop below), hid the 'Active:' badge and stopped auto-follow, so a
  // finished sheet awaiting approval rendered identically to an empty machine
  // (2026-08-26). `parked` is the one exception; everything else is unchanged.
  const _parked = !!(pipeline && pipeline.review_pending);
  // Medusa counts a Vicky/Victor turn in the Medusa app as a running workflow
  // (operator, 2026-09-17), which is why `active` is read in preference to the
  // generation job's own status — `status` only ever describes a sheet render.
  // `data.active === undefined` means an older bp_medusa is answering; fall
  // back to the job status rather than reporting a idle board as live.
  const _mdzOn = (data.active === undefined) ? (data.status === 'running') : !!data.active;
  if (_viewedTemplate === 'medusa') _mdzSetLive(_mdzOn, data.active_label);
  _pipelineIdle = (_viewedTemplate === 'medusa')
    ? !_mdzOn
    : (!pipeline || (pipeline.status !== 'running' && !_parked));
  const serverTemplate = data.template || 'documentary';
  const pipelineFamily = (data.model_family || (pipeline && pipeline.model_family) || '').toLowerCase();
  if (pipelineFamily === 'flux' || pipelineFamily === 'sdxl') {
    _activeModelFamily = pipelineFamily;
  }

  // ── Active pipeline status text ───────────────────────────────────────────
  _updateActiveStatus(pipeline);

  // ── Operator review gate banner (parked runs) ─────────────────────────────
  _updateReviewGate(pipeline);

  // ── Test run badge ────────────────────────────────────────────────────────
  _updateTestBadge(!_pipelineIdle && data.is_test);

  // Track live pipeline template without changing what the user is viewing.
  if (serverTemplate !== _activeTemplate) {
    _activeTemplate = serverTemplate;
    _syncDropdown();
  }

  // AUTO-FOLLOW THE LIVE BOARD (2026-08-01).
  // Previously the view never moved, so a running render left the operator on
  // the default Documentary board with every card 'queued' — indistinguishable
  // from "nothing is happening", which is exactly how the Second Ledger renders
  // were reported as invisible. A manual pick sets _viewPinned and always wins;
  // the 'Active:' badge remains the manual route back.
  // Must run BEFORE the JOBS.forEach below, which stamps card status onto
  // whatever board is currently built.
  if (!_viewPinned && !_pipelineIdle && _viewedTemplate !== _activeTemplate) {
    const famT = _getTemplatesForFamily(_viewedFamily || _getSelectedFamily());
    if (famT[_activeTemplate] || TEMPLATES[_activeTemplate]) {
      _viewedTemplate = _activeTemplate;
      _buildFromTemplate(_viewedTemplate);
      // _ltLastCards lives in kanban_livetail.js, which loads AFTER this file.
      // This runs on every poll (not on click like _goToActiveBoard), so it can
      // fire while that `let` is still in its temporal dead zone — and a bare
      // ReferenceError here would kill applyPipelineStatus and freeze the board.
      try { _ltLastCards = {}; } catch (e) { /* live tail not loaded yet */ }
      _syncDropdown();
    }
  }

  // ── Message cycle management ──────────────────────────────────────────────
  if (_pipelineIdle) {
    try { localStorage.removeItem('kb_auto_template'); localStorage.removeItem('kb_auto_family'); } catch {}
  }

  const nowRunning = !_pipelineIdle;
  if (nowRunning && !_pipelineWasRunning) {
    // Pipeline just started → kick off message cycle
    _pipelineWasRunning = true;
    _pipelineFinished = false;
    _startMessageCycle();
  } else if (!nowRunning && _pipelineWasRunning) {
    // Pipeline just finished
    _pipelineWasRunning = false;
    _pipelineFinished = true;
    // If we're at the Bruce Lee message, advance to completion message
    if (_msgIndex === 10) {
      _msgIndex = 11;
      _advanceMessage();
    } else if (_msgIndex < 11) {
      // Jump straight to completion
      clearTimeout(_msgTimer);
      _msgIndex = 11;
      _renderPipelineMessage(PIPELINE_MESSAGES[11]);
    }
    // Stop cycle after showing completion message (2 min then restore)
    setTimeout(_stopMessageCycle, 120000);
  }

  // ── Collect errors and info events from API response ──────────────────────
  if (data.errors && data.errors.length) {
    data.errors.forEach(e => {
      const obj = _ltParseApiEvent(e);
      if (!DBG.errors.some(x => x.raw === obj.raw)) {
        DBG.errors.push(obj);
        if (DBG.errors.length > 40) DBG.errors.shift();
        _ltAppendApiEventToLog(obj, 'err');
      }
    });
  }
  if (data.events && data.events.length) {
    data.events.forEach(e => {
      const obj = _ltParseApiEvent(e);
      if (!DBG.events.some(x => x.raw === obj.raw)) {
        DBG.events.push(obj);
        if (DBG.events.length > 80) DBG.events.shift();
        _ltAppendApiEventToLog(obj, 'info');
      }
    });
  }
  if ((data.errors && data.errors.length) || (data.events && data.events.length)) {
    renderLiveTailDebug();
  }

  const cardTimes = data.card_times || {};
  /* A card's clock must be cleared whenever its status is being forced rather
     than read from the live pipeline, or a stale start time outlives the run
     that produced it. */
  const clearClock = job => { job.since_s = null; job.elapsed_s = null; job.started_at = null; };
  const applyClock = job => {
    const t = cardTimes[job.prompt];
    if (!t) { clearClock(job); return; }
    job.since_s    = (typeof t.since_s    === 'number') ? t.since_s    : null;
    job.elapsed_s  = (typeof t.elapsed_s  === 'number') ? t.elapsed_s  : null;
    job.started_at = t.started_at || null;
  };

  JOBS.forEach(job => {
    if (_pipelineIdle) {
      job.status = 'queued';
      job.progress = 0;
      clearClock(job);
      return;
    }
    // Only apply card statuses from the active pipeline to its own template's cards.
    // Exception: sports_video pipeline drives the Templates board cards via svCardMap.
    if (_viewedTemplate !== _activeTemplate) {
      if (svCardMap[job.prompt]) {
        const svSt = svCardMap[job.prompt];
        job.status = svSt;
        if (svSt === 'running' && job.progress < 5) job.progress = 5;
        if (svSt === 'done')  job.progress = 100;
        if (svSt === 'error') job.progress = 0;
        // sports_video drives these cards positionally and keeps no per-stage
        // timestamps, so they carry a status and no clock.
        clearClock(job);
      } else {
        job.status = 'queued';
        job.progress = 0;
        clearClock(job);
      }
      return;
    }
    const st = cards[job.prompt];
    if (!st) {
      job.status = 'queued';
      job.progress = 0;
      clearClock(job);
    } else {
      job.status = st;
      if (st === 'running' && job.progress < 5) job.progress = 5;
      if (st === 'done')    job.progress = 100;
      if (st === 'error')   job.progress = 0;
      applyClock(job);
    }
  });
  renderBoard();
}

let _simFallback = false;
let _pollFailStreak = 0;   // consecutive poll failures; suppress log until streak ≥ 3

function pollPipeline() {
  // Medusa board polls its OWN status endpoint (dedicated workflow); every other
  // board keeps the shared /api/kanban/status untouched.
  var _pollUrl = (typeof _viewedTemplate !== 'undefined' && _viewedTemplate === 'medusa')
    ? FLASK_BASE + '/api/medusa/kanban_status'
    : FLASK_BASE + '/api/kanban/status'
      // Pin the board to a run in another department when the operator clicked
      // one of the "also running" chips; without this the board snaps straight
      // back to whichever run started last (2026-10-02).
      + (_pinnedRunId ? ('?pipeline_id=' + encodeURIComponent(_pinnedRunId)) : '');
  fetch(_pollUrl)
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(data => {
      _pollFailStreak = 0;
      DBG.pipelineOk = true;
      DBG.pipelineAt = new Date().toLocaleTimeString();
      DBG.pipelineRaw = data;
      _simFallback = false;
      applyPipelineStatus(data);
      _ltOnPipelineData(data);
      renderLiveTailDebug();
      renderLiveTailTelem();
    })
    .catch(err => {
      _pollFailStreak++;
      DBG.pipelineOk = false;
      DBG.pipelineErr = String(err && err.message || err);
      // Only log after 3 consecutive failures to suppress startup noise — except
      // an HTTP status, which is the server answering and refusing (a 429 from
      // the rate limiter looked exactly like a blip for a whole day, 2026-09-23).
      if (_pollFailStreak >= 3 || DBG.pipelineErr.indexOf('HTTP') === 0) {
        dbgLog('Pipeline poll failed: ' + DBG.pipelineErr + ' (' + _pollUrl + ')');
      }
      _simFallback = true;
      renderLiveTailDebug();
    });
}

/* 2026-09-22: follow a Medusa render from any board. pollPipeline() reads ONE
   endpoint — the shared /api/kanban/status everywhere except on the Medusa
   board — and the shared status knows nothing about Medusa (it reports
   documentary/idle). So a render started in the Medusa app (:5300) never moved
   the page: the operator had to open the Medusa board by hand to see it live.
   This probe polls the endpoint the page is NOT on, every 2 s, and applies the
   same rule as the auto-follow in applyPipelineStatus: move only when the view
   is not pinned by a manual pick, and never away from a pipeline that is
   running. The Medusa -> shared direction is the same probe reversed, so an
   auto-followed Medusa board does not strand the page once Medusa goes idle.
   One exception to the pin: the MOMENT a Medusa render starts, the page moves
   even from a hand-picked board (operator: a Medusa render must activate the
   Medusa workflow). Only the idle -> active edge does that, so navigating away
   while it runs is not undone on the next probe.

   2026-09-23: that rising edge now also beats a BUSY board. The probe used to
   return early whenever the viewed board had a pipeline of its own running, so
   a Medusa render starting while (say) a documentary ran was never even asked
   about. The operator's rule is unconditional — anything generated in the
   Medusa app activates the Medusa board — and the reverse probe hands the page
   back to the live shared board as soon as Medusa goes idle, so nothing is lost
   by moving. Everything short of that edge keeps the old, conservative rule.

   The probe's failures are no longer swallowed either: it ran into HTTP 429 for
   a whole day (the endpoint was missing @limiter.exempt) with an empty catch,
   which is why the board looked like it simply did not fire. */
let _mdzProbeWas = null;   // Medusa active at the last probe; null = not known yet
let _mdzProbeFails = 0;    // consecutive probe failures
function _crossProbe() {
  const onMedusa = (_viewedTemplate === 'medusa');
  if (onMedusa) _mdzProbeWas = _mdzActive;
  // A busy viewed board still asks Medusa (only Medusa's idle -> active edge is
  // allowed to move the page from it); the shared direction keeps the old rule.
  if (!_pipelineIdle && onMedusa) return;   // the Medusa board is live — stay
  if (onMedusa && _viewPinned) return;
  const url = FLASK_BASE + (onMedusa ? '/api/kanban/status' : '/api/medusa/kanban_status');
  fetch(url)
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(data => {
      _mdzProbeFails = 0;
      DBG.medusaProbeOk = true;
      DBG.medusaProbeAt = new Date().toLocaleTimeString();
      if ((_viewedTemplate === 'medusa') !== onMedusa) return;
      if (!_pipelineIdle && onMedusa) return;
      let target = null, family = null;
      if (onMedusa) {
        const p = data.pipeline;
        const live = p && (p.status === 'running' || p.review_pending);
        if (!_viewPinned && live && data.template && data.template !== 'medusa') {
          target = data.template;
          family = (data.model_family || p.model_family || '').toLowerCase();
        }
      } else {
        const on = (data.active === undefined) ? (data.status === 'running') : !!data.active;
        const rising = on && _mdzProbeWas === false;
        _mdzProbeWas = on;
        // rising = a Medusa workflow just started: it takes the page off a
        // pinned board AND off a board with a run of its own. Otherwise only an
        // unpinned, idle board follows.
        if (on && (rising || (!_viewPinned && _pipelineIdle))) target = 'medusa';
      }
      if (!target) return;
      _viewPinned = false;                   // an automatic move, like _goToActiveBoard
      if (target === 'medusa') _mdzProbeWas = true;   // leaving it later is not a new start
      if (family === 'flux' || family === 'sdxl') {
        _activeModelFamily = family;
        _viewedFamily = family;
        const famSel0 = document.getElementById('kb-model-family-select');
        if (famSel0) famSel0.value = family;
      }
      const famT = _getTemplatesForFamily(_viewedFamily || _getSelectedFamily());
      if (!(famT[target] || TEMPLATES[target])) return;
      _activeTemplate = target;
      _viewedTemplate = target;
      _buildFromTemplate(target);
      try { _ltLastCards = {}; } catch (e) { /* live tail not loaded yet */ }
      const famSel = document.getElementById('kb-model-family-select');
      if (famSel) famSel.style.display = (target === 'medusa') ? 'none' : '';
      renderBoard();
      _syncDropdown();
      _char2dRunVisible();
      pollPipeline();                        // repaint from the new board's own status now
    })
    .catch(err => {
      // NOT silent any more. This probe is the only thing that can move the page
      // onto the Medusa board, so when it cannot reach the endpoint the board
      // sits idle through a live render and looks broken for no stated reason.
      _mdzProbeFails++;
      DBG.medusaProbeOk = false;
      DBG.medusaProbeErr = String(err && err.message || err);
      DBG.medusaProbeAt = new Date().toLocaleTimeString();
      // A 429 is a configuration fault, not a blip — say so the first time.
      if (_mdzProbeFails === 1 || _mdzProbeFails === 3 || _mdzProbeFails % 150 === 0) {
        dbgLog('Medusa cross-probe failed (' + DBG.medusaProbeErr + ') ×' + _mdzProbeFails);
      }
    });
}
setInterval(_crossProbe, 2000);

function simulateLive() {
  /* Only simulate card movement when real API is unreachable — and NEVER for
     the Medusa board (2026-08-06): a poll failure (e.g. the server briefly
     unresponsive under CPU load, as happened 2026-08-06) used to fall back to
     randomly marking arbitrary queued cards 'running' here, purely as a
     cosmetic "keep the board looking alive" demo behaviour. That's actively
     misleading for a workflow the operator needs to trust the real status
     of — on a poll failure the Medusa board now just holds its last known
     real state instead of fabricating new activity. Other boards keep the
     existing simulated fallback; only Medusa's accuracy was reported as a
     problem. */
  if (!_simFallback) return;
  if (_viewedTemplate === 'medusa') return;
  JOBS.forEach(job => {
    if (job.status === 'running') {
      job.progress = Math.min(100, job.progress + randInt(1, 6));
      if (job.progress >= 100) job.status = 'done';
    }
    // No clock is simulated here: with the API unreachable there is no honest
    // start time to show, and the dialog renders '—' for these cards.
  });
  const queued = JOBS.filter(j => j.status === 'queued');
  if (Math.random() < 0.3 && queued.length > 0) {
    const pick = randEl(queued);
    pick.status = 'running';
    pick.progress = randInt(2, 15);
  }
  renderBoard();
}

/* ── Init ───────────────────────────────────────────────────────────────────── */
// Default view: SDXL documentary board (model family persisted in localStorage).
// URL param ?view=<key> overrides the default (used by Asset Manager iframe embed).
try {
  const stored = (localStorage.getItem('kb_model_family') || '').toLowerCase();
  _viewedFamily = (stored === 'flux') ? 'flux' : 'sdxl';
  try { localStorage.removeItem('kb_auto_template'); localStorage.removeItem('kb_auto_family'); } catch {}
  const famSel = document.getElementById('kb-model-family-select');
  if (famSel) famSel.value = _viewedFamily;
  // ?view=<key> lets the Asset Manager embed a specific board without user interaction
  const _urlView = new URLSearchParams(window.location.search).get('view');
  if (_urlView && (_urlView in (_getTemplatesForFamily(_viewedFamily) || {}))) {
    _viewedTemplate = _urlView;
  }
  const tplSel = document.getElementById('kb-template-select');
  if (tplSel) tplSel.value = _viewedTemplate;
} catch {}
_buildFromTemplate(_viewedTemplate || 'documentary');
// The picker is markup, not a render of _viewedTemplate: its trigger reads
// "Documentary" and the Documentary row carries .active straight from
// kanban.html. Building the board never touched either, so a ?view= deep link
// drew the linked board under the wrong name and left the highlight on
// Documentary — for the whole session, since the only other _syncDropdown() on
// this path is inside applyPipelineStatus's auto-follow branch, which fires
// only while a pipeline is running on a DIFFERENT board.
_syncDropdown();
buildTelemetry();
renderBoard();
pollPipeline();
setInterval(() => { simulateLive(); updateTelemetry(); }, 500);
setInterval(pollPipeline, 500);

/* ── Custom channel/pipeline picker ─────────────────────────────────────────── */

function _flyoutClose() {
  clearTimeout(_flyAimTimer);
  const flyout = document.getElementById('kb-ch-flyout');
  if (flyout) { flyout.classList.remove('open'); flyout.dataset.activeGroup = ''; }
  document.querySelectorAll('.kb-ch-chevron-btn').forEach(function(b) { b.classList.remove('open'); });
}

function _chPickerClose() {
  const menu    = document.getElementById('kb-ch-menu');
  const trigger = document.getElementById('kb-ch-trigger');
  if (menu)    menu.classList.remove('open');
  if (trigger) trigger.classList.remove('open');
  _flyoutClose();
}

function _positionMenu() {
  const menu    = document.getElementById('kb-ch-menu');
  const trigger = document.getElementById('kb-ch-trigger');
  if (!menu || !trigger) return;
  const rect = trigger.getBoundingClientRect();
  menu.style.top  = (rect.bottom + 4) + 'px';
  menu.style.left = rect.left + 'px';
  // Clamp right edge
  const menuW   = menu.offsetWidth;
  const maxLeft = window.innerWidth - menuW - 8;
  if (parseFloat(menu.style.left) > maxLeft) menu.style.left = maxLeft + 'px';
}

function _toggleChPicker(e) {
  e.stopPropagation();
  const trigger = document.getElementById('kb-ch-trigger');
  const menu    = document.getElementById('kb-ch-menu');
  if (!trigger || !menu) return;
  if (menu.classList.contains('open')) {
    _chPickerClose();
  } else {
    menu.classList.add('open');
    trigger.classList.add('open');
    _flyPts = [];   // a stale apex from the last time the picker was open would
                    // make the first hover look like travel toward a flyout
    _positionMenu();
  }
}

// Open a group's flyout to the right of the menu, aligned with its header row.
function _openChGroup(groupId, hdrEl) {
  const flyout   = document.getElementById('kb-ch-flyout');
  const menu     = document.getElementById('kb-ch-menu');
  const children = document.getElementById('kb-chgrp-' + groupId);
  if (!flyout || !children || !menu) return;
  if (flyout.dataset.activeGroup === groupId && flyout.classList.contains('open')) return; // already open

  // Reset all chevrons, mark this group's chevron open
  document.querySelectorAll('.kb-ch-chevron-btn').forEach(function(b) { b.classList.remove('open'); });
  const chev = hdrEl && hdrEl.querySelector ? hdrEl.querySelector('.kb-ch-chevron-btn') : null;
  if (chev) chev.classList.add('open');

  // Copy subchannel items into flyout (strip the kb-ch-sub indent — they're top-level here)
  flyout.innerHTML = children.innerHTML;
  flyout.querySelectorAll('.kb-ch-item').forEach(function(el) {
    el.classList.remove('kb-ch-sub');
    el.style.paddingLeft = '14px';
  });

  const menuRect = menu.getBoundingClientRect();
  const hdrRect  = hdrEl ? hdrEl.getBoundingClientRect() : menuRect;

  /* Melodies is a 127-board taxonomy in nine families, not four sub-channels:
     its flyout lays out in columns, and the count comes from the room actually
     to the right of the menu. A @media breakpoint cannot decide this — it reads
     the REAL viewport, which is the same 1680 whether the page is standalone at
     zoom .67 (2507 layout px, six columns fit) or inside the :5000 dashboard
     iframe at zoom 1 (1680 layout px, four fit).
     The flyout element is SHARED by every group, so the inline width is cleared
     on the way in and only re-set for this one. */
  flyout.style.width = '';
  const melGrid = flyout.querySelector('.kb-melgrid');
  if (melGrid) {
    const room = window.innerWidth - menuRect.right - 18;
    const cols = Math.max(2, Math.min(6, Math.floor(room / 214)));
    melGrid.style.columnCount = cols;
    flyout.style.width = (cols * 214) + 'px';
  }

  flyout.classList.add('open');
  flyout.dataset.activeGroup = groupId;

  const flyW    = flyout.offsetWidth;
  let   flyLeft = menuRect.right + 5;
  if (flyLeft + flyW > window.innerWidth - 8) flyLeft = menuRect.left - flyW - 5;  // flip left if off-screen
  if (flyLeft < 8) flyLeft = 8;   // a flyout wider than the menu's left margin flipped to a negative x
  let flyTop = hdrRect.top;
  const flyH   = flyout.offsetHeight;
  const maxTop = window.innerHeight - flyH - 8;
  if (flyTop > maxTop) flyTop = maxTop;
  flyout.style.left = flyLeft + 'px';
  flyout.style.top  = flyTop  + 'px';
}

// Chevron click still toggles (open ↔ close); hover opens (wired below).
function _toggleChGroup(e, groupId) {
  e.stopPropagation();
  const flyout = document.getElementById('kb-ch-flyout');
  if (flyout && flyout.dataset.activeGroup === groupId && flyout.classList.contains('open')) {
    _flyoutClose();
    return;
  }
  const btn = e.currentTarget;
  const hdrEl = (btn && btn.closest) ? btn.closest('.kb-ch-group-hdr') : (btn ? btn.parentElement : null);
  _openChGroup(groupId, hdrEl);
}

/* Hover-to-open: hovering a group row opens its flyout to the right; hovering a flat
   (non-group) item, or leaving the menu+flyout, closes it.

   2026-10-05 — the flyout was UNREACHABLE. The picker is three side-by-side
   columns and the flyout opens to the right of ALL of them, so the cursor
   travelling from a group row in Pipelines out to its flyout has to cross the
   Channels and Blueprints columns. Every flat item it brushed scheduled a close
   and every other group header it brushed (Cars/News sit at the same y as Video)
   swapped the flyout's contents — the submenu collapsed before the pointer ever
   arrived. A plain delay cannot fix that: the crossed rows are hovered for real.

   The fix is a "safe triangle" (the Amazon-menu trick): while a flyout is open,
   a pointer whose recent motion is heading into the triangle apex=where-it-was,
   base=the flyout's near edge is TRAVELLING, not browsing, so its hovers are
   ignored. A row it actually stops on still wins — the decision is re-taken
   ~180 ms later if the pointer is still on that same row. */
var _flyHoverTimer = null;   // close delay
var _flyAimTimer   = null;   // deferred row activation while travelling
var _flyPts        = [];     // recent pointer samples; _flyPts[0] is the triangle apex

function _flyoutScheduleClose() { clearTimeout(_flyHoverTimer); _flyHoverTimer = setTimeout(_flyoutClose, 240); }
function _flyoutCancelClose()   { clearTimeout(_flyHoverTimer); }

function _flyNotePoint(e) {
  _flyPts.push({ x: e.clientX, y: e.clientY });
  if (_flyPts.length > 4) _flyPts.shift();
}

function _flyInTriangle(p, a, b, c) {
  function side(p1, p2, p3) { return (p1.x - p3.x) * (p2.y - p3.y) - (p2.x - p3.x) * (p1.y - p3.y); }
  const d1 = side(p, a, b), d2 = side(p, b, c), d3 = side(p, c, a);
  return !(((d1 < 0) || (d2 < 0) || (d3 < 0)) && ((d1 > 0) || (d2 > 0) || (d3 > 0)));
}

// True while the pointer is on its way into the open flyout.
function _flyTravelling() {
  const flyout = document.getElementById('kb-ch-flyout');
  if (!flyout || !flyout.classList.contains('open') || _flyPts.length < 2) return false;
  const r = flyout.getBoundingClientRect();
  const p = _flyPts[_flyPts.length - 1], a = _flyPts[0];
  if (p.x >= r.left && p.x <= r.right && p.y >= r.top && p.y <= r.bottom) return true;
  // The near edge is the side the cursor is coming from (the flyout flips left
  // when there is no room on the right), and the motion has to point at it.
  const onLeft = (p.x <= r.left);
  const edge   = onLeft ? r.left : r.right;
  if (onLeft  && p.x <= a.x) return false;
  if (!onLeft && p.x >= a.x) return false;
  const pad = 12;  // the flyout's own border/shadow, plus the 5px gap to the menu
  return _flyInTriangle(p, a, { x: edge, y: r.top - pad }, { x: edge, y: r.bottom + pad });
}

function _flyApplyRow(row) {
  const hdr = row.classList.contains('kb-ch-group-hdr')
    ? row
    : (row.closest ? row.closest('.kb-ch-group-hdr') : null);
  if (hdr) {
    _flyoutCancelClose();
    const childrenDiv = hdr.parentElement && hdr.parentElement.querySelector
      ? hdr.parentElement.querySelector('.kb-ch-group-children') : null;
    if (childrenDiv && childrenDiv.id) _openChGroup(childrenDiv.id.replace('kb-chgrp-', ''), hdr);
    return;
  }
  // a flat item (not part of a group) → let any open flyout close
  if (!(row.closest && row.closest('.kb-ch-group'))) _flyoutScheduleClose();
}

function _flyAimRow(row) {
  clearTimeout(_flyAimTimer);
  if (!_flyTravelling()) { _flyApplyRow(row); return; }
  _flyoutCancelClose();                       // hands off — the pointer is in transit
  _flyAimTimer = setTimeout(function() {      // …unless it stopped here
    const p  = _flyPts[_flyPts.length - 1];
    const el = p ? document.elementFromPoint(p.x, p.y) : null;
    const still = (el && el.closest) ? el.closest('.kb-ch-group-hdr, .kb-ch-item') : null;
    if (still === row) _flyApplyRow(row);
  }, 180);
}

function _wireFlyoutHover() {
  const menu   = document.getElementById('kb-ch-menu');
  const flyout = document.getElementById('kb-ch-flyout');
  if (!menu || !flyout || menu.dataset.hoverWired) return;
  menu.dataset.hoverWired = '1';
  menu.addEventListener('mousemove',   _flyNotePoint);
  flyout.addEventListener('mousemove', _flyNotePoint);
  menu.addEventListener('mouseover', function(e) {
    const row = e.target.closest ? e.target.closest('.kb-ch-group-hdr, .kb-ch-item') : null;
    if (row) _flyAimRow(row);
  });
  menu.addEventListener('mouseleave', function() {
    if (!_flyTravelling()) _flyoutScheduleClose();
  });
  flyout.addEventListener('mouseenter', function() { clearTimeout(_flyAimTimer); _flyoutCancelClose(); });
  flyout.addEventListener('mouseleave', _flyoutScheduleClose);
}

// Environments/Effects render mode (2026-07-28): 3d video (default) vs 2d still.
var _renderMode = '3d';
function _setRenderMode(m) { _renderMode = (m === '2d') ? '2d' : '3d'; }

function _selectTemplate(key) {
  _viewedTemplate = key;
  _viewPinned     = true;
  _chPickerClose();
  _buildFromTemplate(key);
  renderBoard();
  _syncDropdown();
  // Medusa is controlled solely by the Medusa app — hide the shared model-family
  // selector on its board so global config can't be changed from (or applied to) it.
  var _famSel = document.getElementById('kb-model-family-select');
  if (_famSel) _famSel.style.display = (key === 'medusa') ? 'none' : '';
  if (DBG.pipelineRaw) applyPipelineStatus(DBG.pipelineRaw);
  _char2dRunVisible();
}

/* ── Video → prepared-series flyout (2026-07-28) ─────────────────────────────
   The "Video" pipeline item has a side flyout listing every prepared series
   (from storyteller_templates.json via the same-origin :8899 endpoint). Clicking
   a series LOADS it on the board (relabels + selects it) — pure navigation, no
   render is launched. Mirrors the generic _toggleChGroup flyout mechanism. */
var _SERIES = [];            // [{id, title, order}]

/* Series that render on their own board instead of the generic Video board.
   Key = series id from /kanban/api/series, value = TEMPLATES key. Must stay in
   step with the server: kanban_video_status.SERIES_BY_PATH decides which series
   a run belongs to, and returns template 'second_ledger' for these. A series
   absent here falls back to 'video', which is correct for the FLUX->WAN2.1-I2V
   pipeline that board actually describes. */
var SERIES_BOARD = {
  st_second_ledger: 'second_ledger',
};
var _viewedSeries = null;    // currently-selected series id (or null)
function _kbEsc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
/* 2026-09-16: paint a TRAILING roman numeral in the steel gradient (.kb-roman in
   kanban.css) and nothing else. Used for the picker's trigger label and the board
   label, which are plain text everywhere else — hence the escape first, then the
   one <span>. The optional trailing ']' lets the board label
   '[ 2D CHARACTER BASICS I ]' match too. Declared as a function so it hoists above
   _syncDropdown/_buildFromTemplate, which live earlier in this file. */
function _romanHtml(s) {
  s = _kbEsc(s);
  return s.replace(/\b([IVX]{1,4})(\s*\]?)$/, '<span class="kb-roman">$1</span>$2');
}
function _loadSeriesMenu() {
  var box = document.getElementById('kb-chgrp-video');
  if (!box) return;
  // same-origin (this page is served by kanban_server on :8899) — no CORS/auth needed
  fetch('/kanban/api/series')
    .then(function(r) { return r.ok ? r.json() : null; })
    .then(function(d) {
      _SERIES = ((d && d.series) || []).map(function(t) {
        return { id: String(t.id || ''), title: String(t.title || t.id || ''), order: t.order || 0 };
      }).filter(function(s) { return s.id; });
      _SERIES.sort(function(a, b) { return (a.order - b.order) || a.title.localeCompare(b.title); });
      box.innerHTML = _SERIES.length
        ? _SERIES.map(function(s) {
            return '<div class="kb-ch-item kb-ch-sub" data-key="series:' + _kbEsc(s.id) + '" '
                 + 'onclick="_selectSeries(\'' + String(s.id).replace(/'/g, "\\'") + '\')">'
                 + _kbEsc(s.title) + '</div>';
          }).join('')
        : '<div class="kb-ch-item kb-ch-sub" style="opacity:.55;cursor:default">No series found</div>';
    })
    .catch(function() {
      box.innerHTML = '<div class="kb-ch-item kb-ch-sub" style="opacity:.55;cursor:default">Series unavailable</div>';
    });
}
/* ── Melodies → style flyout (2026-09-06) ───────────────────────────────────
   Built from MELODY_FAMILIES, the same table that registered the boards, so a
   menu entry and its board cannot drift apart.  Nine family blocks; each is one
   .kb-melfam so the CSS multi-column flyout never splits a heading from its
   styles.  Navigation only — _selectTemplate just re-draws the board, exactly
   like every other sub-channel; nothing is launched from here. */
function _buildMelodyMenu() {
  var box = document.getElementById('kb-chgrp-melodies');
  if (!box) return;
  box.innerHTML = '<div class="kb-melgrid">' + MELODY_FAMILIES.map(function(fam) {
    return '<div class="kb-melfam">'
      + '<div class="kb-ch-section">' + _kbEsc(fam.name) + '</div>'
      + fam.styles.map(function(s) {
          var key   = _melodyKey(fam.key, s[0]);
          var wired = (MELODY_WIRED[fam.key] || []).indexOf(s[0]) >= 0;
          var off   = !!MELODY_EXCLUDED[fam.key + '/' + s[0]];
          var tip = fam.short + ' — ' + s[1] + (off
            ? ' · excluded (operator decision)'
            : wired
              ? (fam.key === 'cinematic'
                  ? ' · live: cinematic board (instrumental, no pictures)'
                  : ' · live: full composer board')
              : s[2]
                ? ' · already a shelf in the Melodies library'
                : ' · new melody type, no runner wired yet');
          // An excluded style keeps its row — dimmed and inert — so the absence
          // reads as a decision rather than a menu entry someone lost.
          return '<div class="kb-ch-item kb-ch-sub' + (off ? ' kb-ch-off' : '') + '"'
               + ' data-key="' + key + '"'
               + ' title="' + _kbEsc(tip) + '"'
               + (off ? ' onclick="return false;"'
                      : " onclick=\"_selectTemplate('" + key + "')\"")
               + '>' + _kbEsc(s[1]) + '</div>';
        }).join('')
      + '</div>';
  }).join('') + '</div>';
  // These rows are built AFTER init's _syncDropdown(), so a ?view=mel_* deep
  // link had nothing to put the highlight on yet — and the flyout is cloned from
  // these very rows, so the stale state reached the open menu too. Re-sync now
  // that they exist.
  _syncDropdown();
}

/* ── Kids Series → series flyout (2026-09-06) ───────────────────────────────
   GENERIC BY CONSTRUCTION.  Nothing below names a series: the list, the board
   columns and the launch buttons are all built from /kanban/api/kids_series,
   which is kids_series_common.discover() re-globbed on every call.  A new
   pipeline_kids_<slug>.py therefore reaches this menu without a line changing
   here and without a page rebuild.

   The one invariant that has to hold, and the one the kidsmusic board documents
   at the top of _addKidsMusicTemplate: a card's `prompt` MUST equal the stage
   string the runner emits, because bp_pipeline_api matches them by substring.
   So the cards are built FROM STAGES rather than written out — a title and a
   stage cannot drift apart if there is only one of them. */
var _KIDS_SERIES = [];       // [{slug, title, tagline, voice, stages, agents, ...}]

function _kidsColId(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '') || 'stage';
}

/* Placeholder so clicking the group name before the fetch lands still draws a
   board instead of throwing. _buildKidsMenu overwrites it with the real list. */
function _kidsHomeTemplate(rows) {
  return {
    name: 'Kids Series',
    label: '[ KIDS SERIES ]',
    columns: [
      { id: 'series', name: 'Series', cards: (rows || []).map(function(s) {
          return {
            prompt: s.title,
            agent: 'pipeline_kids_' + s.slug + '.py',
            meta: {
              description: '<p>' + _kbEsc(s.tagline) + '</p>'
                + '<ul><li>' + (s.voice ? 'Narrated' : 'No voice')
                + ' \u00b7 ' + _kbEsc(s.age_band || 'children')
                + ' \u00b7 ' + _kbEsc(String(s.episode_seconds || '?')) + ' s'
                + ' \u00b7 ' + _kbEsc(String(s.episodes || '?')) + ' episodes</li></ul>',
              llms: ['\u2014 (no LLM, fixed tables)'],
              tools: ['pipeline_kids_' + s.slug + '.py'],
            },
          };
        }) },
    ],
  };
}
TEMPLATES.kids_series_home = _kidsHomeTemplate([]);

/* Launch one episode. POSTs through the same-host kanban hop the composer panel
   uses (/inspect/api/kidseries/start -> :5000 /api/internal/kidseries/start),
   because this page is a different origin with no dashboard session. */
function _kidsStart(e, slug, testMode) {
  if (e) { e.stopPropagation(); e.preventDefault(); }
  _kidsMsg(slug, 'starting\u2026');
  fetch('/inspect/api/kidseries/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ series: slug, test_mode: !!testMode }),
  })
    .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, d: d }; }); })
    .then(function(res) {
      if (res.ok && res.d && res.d.job_id) {
        _kidsMsg(slug, (testMode ? 'test ' : 'episode ') + res.d.job_id);
      } else {
        _kidsMsg(slug, String((res.d && res.d.error) || 'start failed'));
      }
    })
    .catch(function(err) { _kidsMsg(slug, String(err && err.message || 'network error')); });
}

/* The status line lives in the menu rows, and _openChGroup CLONES those rows
   into the flyout — so there are two copies of every row and both must be
   written. Hence a class, not an id. */
function _kidsMsg(slug, text) {
  document.querySelectorAll('.kb-kids-msg[data-slug="' + slug + '"]').forEach(function(el) {
    el.textContent = text;
  });
}

function _buildKidsMenu() {
  var box = document.getElementById('kb-chgrp-kids');
  if (!box) return;
  // same-origin (this page is served by kanban_server on :8899) — no CORS/auth needed
  fetch('/kanban/api/kids_series')
    .then(function(r) { return r.ok ? r.json() : null; })
    .then(function(d) {
      _KIDS_SERIES = ((d && d.series) || []).filter(function(s) { return s && s.slug; });
      _KIDS_SERIES.forEach(function(s) {
        var stages = s.stages || [];
        var agents = s.agents || {};
        TEMPLATES['kids_' + s.slug] = {
          name: 'Kids Series \u00b7 ' + s.title,
          label: '[ KIDS SERIES \u203a ' + String(s.title).toUpperCase() + ' ]',
          columns: stages.map(function(st) {
            return {
              id: _kidsColId(st),
              name: st,
              // prompt === the stage title. See the note above: this is the
              // match bp_pipeline_api's identity stage map relies on.
              cards: [{
                prompt: st,
                agent: agents[st] || 'kids_series_common.py',
                meta: {
                  description: '<p>' + _kbEsc(s.tagline) + '</p>',
                  llms: ['\u2014 (no LLM, fixed tables)'],
                  tools: ['pipeline_kids_' + s.slug + '.py'],
                },
              }],
            };
          }),
        };
      });
      TEMPLATES.kids_series_home = _kidsHomeTemplate(_KIDS_SERIES);
      box.innerHTML = _KIDS_SERIES.length
        ? _KIDS_SERIES.map(function(s) {
            var key = 'kids_' + s.slug;
            var esc = String(s.slug).replace(/'/g, "\\'");
            var tip = (s.tagline || s.title) + ' \u2014 '
                    + (s.voice ? 'narrated' : 'no voice') + ', '
                    + (s.age_band || 'children') + ', '
                    + (s.episode_seconds || '?') + ' s';
            // Inline styles rather than kanban.css: this menu is the only user
            // of these three classes, and one file fewer to keep in step.
            var BTN = 'style="margin-left:6px;padding:0 5px;font:inherit;font-size:9px;'
                    + 'line-height:14px;border:1px solid currentColor;border-radius:3px;'
                    + 'background:transparent;color:inherit;opacity:.7;cursor:pointer"';
            return '<div class="kb-ch-item kb-ch-sub" data-key="' + _kbEsc(key) + '"'
                 + ' title="' + _kbEsc(tip) + '"'
                 + " onclick=\"_selectTemplate('" + _kbEsc(key) + "')\">"
                 + '<span class="kb-kids-voice" title="'
                 + (s.voice ? 'narrated' : 'no voice') + '">'
                 + (s.voice ? '\u25cf' : '\u25cb') + '</span> '
                 + _kbEsc(s.title)
                 + '<button class="kb-kids-btn" ' + BTN
                 + ' onclick="_kidsStart(event,\'' + esc + '\',true)"'
                 + ' title="One short test episode">\u25b6 test</button>'
                 + '<button class="kb-kids-btn" ' + BTN
                 + ' onclick="_kidsStart(event,\'' + esc + '\',false)"'
                 + ' title="One full episode">\u25b6 episode</button>'
                 + '<span class="kb-kids-msg" data-slug="' + _kbEsc(s.slug) + '"'
                 + ' style="margin-left:6px;font-size:9px;opacity:.6"></span>'
                 + '</div>';
          }).join('')
        : '<div class="kb-ch-item kb-ch-sub" style="opacity:.55;cursor:default">No kids series found</div>';
      // Built AFTER init's _syncDropdown(), so a ?view=kids_* deep link had
      // nothing to highlight yet — same reason _buildMelodyMenu re-syncs.
      _syncDropdown();
    })
    .catch(function() {
      box.innerHTML = '<div class="kb-ch-item kb-ch-sub" style="opacity:.55;cursor:default">Kids series unavailable</div>';
    });
}

function _selectSeries(id) {
  var s = _SERIES.filter(function(x) { return x.id === id; })[0];
  var title = s ? s.title : id;
  _viewedSeries   = id;
  // Series that have their own board get it; everything else keeps the generic
  // Video board. The Second Ledger renders on Wan2.1+VACE and shares no stage
  // with the generic board, so pointing it at 'video' guaranteed every card sat
  // at 'queued' forever — no card title could ever match a VACE stage name.
  _viewedTemplate = SERIES_BOARD[id] || 'video';
  _viewPinned     = true;
  _chPickerClose();
  _buildFromTemplate(_viewedTemplate);
  renderBoard();
  _syncDropdown();
  // override the generic labels with the series identity
  var lbl = document.getElementById('kb-pipeline-label');
  if (lbl) lbl.textContent = '[ ' + String(title).toUpperCase() + ' — VIDEO SERIES ]';
  var chl = document.getElementById('kb-ch-label');
  if (chl) chl.textContent = title;
  // highlight the picked series (in the source list and any open flyout copy)
  document.querySelectorAll('#kb-ch-menu [data-key], #kb-ch-flyout [data-key]').forEach(function(el) {
    el.classList.toggle('active', el.dataset.key === ('series:' + id));
  });
  var famSel = document.getElementById('kb-model-family-select');
  if (famSel) famSel.style.display = '';
  if (DBG.pipelineRaw) applyPipelineStatus(DBG.pipelineRaw);
}

// Escape the stacking context created by .kb-header's backdrop-filter.
// Moving menu + flyout to <body> makes their z-index apply at document root level.
(function() {
  var menu   = document.getElementById('kb-ch-menu');
  var flyout = document.getElementById('kb-ch-flyout');
  if (menu)   document.body.appendChild(menu);
  if (flyout) document.body.appendChild(flyout);
})();

// Hover a pipeline/channel group → open its flyout to the right (no need to click the arrow).
_wireFlyoutHover();

// Populate the Video → series flyout from the prepared-series list.
_loadSeriesMenu();

// Populate the Melodies → style flyout from MELODY_FAMILIES.
_buildMelodyMenu();

// Populate the Kids Series flyout from kids_series_common.discover().
_buildKidsMenu();

// Close picker when clicking outside or scrolling.
// menu/flyout are now body children so check them separately.
document.addEventListener('click', function(e) {
  const wrap   = document.getElementById('kb-ch-picker-wrap');
  const menu   = document.getElementById('kb-ch-menu');
  const flyout = document.getElementById('kb-ch-flyout');
  const inside = (wrap   && wrap.contains(e.target))
              || (menu   && menu.contains(e.target))
              || (flyout && flyout.contains(e.target));
  if (!inside) _chPickerClose();
});
window.addEventListener('scroll', _chPickerClose, true);

/* ── Template dropdown (hidden native select — kept for backward-compat reads) ── */
document.getElementById('kb-template-select').addEventListener('change', function() {
  _viewedTemplate = this.value;
  _viewPinned     = true;
  _buildFromTemplate(_viewedTemplate);
  renderBoard();
  _syncDropdown();
});

/* ── Model-family dropdown ───────────────────────────────────────────────────── */
document.getElementById('kb-model-family-select').addEventListener('change', function() {
  const v = (this.value || '').toLowerCase();
  const fam = (v === 'flux') ? 'flux' : 'sdxl';
  _viewedFamily = fam;
  _familyPinned = true;
  try { localStorage.setItem('kb_model_family', fam); } catch {}
  _buildFromTemplate(_viewedTemplate);
  renderBoard();
  // If a pipeline is running, show mismatch banner when pinned to a different family.
  const mm = document.getElementById('kb-family-mismatch');
  if (mm) mm.style.display = 'none';
});

(function() {
  const badge = document.getElementById('kb-live-badge');
  if (!badge) return;
  badge.addEventListener('click', _goToActiveBoard);
  badge.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      _goToActiveBoard();
    }
  });
})();
