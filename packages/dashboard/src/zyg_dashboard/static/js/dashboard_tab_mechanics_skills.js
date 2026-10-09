// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

(function () {
'use strict';

/* ─── Sandbox system ─────────────────────────────────────────────────────────── */
var ZYG_SANDBOX = window.ZYG_SANDBOX = {
    _store: (function () {
        try { return JSON.parse(localStorage.getItem('zyg_sandbox') || '{}'); } catch (e) { return {}; }
    })(),
    _save: function () {
        try { localStorage.setItem('zyg_sandbox', JSON.stringify(ZYG_SANDBOX._store)); } catch (e) {}
    },
    configured: false,
    /** Return cached result for a skill, or null if never checked. */
    check: function (skillId) {
        return ZYG_SANDBOX._store[skillId] || null;
    },
    /** Run all sandbox layers for a skill via the Flask API.
     *  @param {string} skillId
     *  @param {string[]} deps
     *  @param {Function} cb  called with (result) when done, or (null, err) on failure
     */
    runCheck: function (skillId, deps, cb) {
        fetch('/api/skill/sandbox/check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ skill_id: skillId, deps: deps || [] })
        })
        .then(function (r) { return r.json(); })
        .then(function (result) {
            ZYG_SANDBOX._store[skillId] = result;
            ZYG_SANDBOX._save();
            if (cb) cb(result, null);
        })
        .catch(function (err) {
            if (cb) cb(null, err);
        });
    },
    /** Fetch sandbox system readiness and update the banner. */
    loadStatus: function () {
        fetch('/api/skill/sandbox/status')
        .then(function (r) { return r.json(); })
        .then(function (s) {
            ZYG_SANDBOX.configured = !!s.all_ready;
            var banner = document.getElementById('skills-sandbox-banner');
            var txt    = document.getElementById('skills-sandbox-status-text');
            var badge  = document.getElementById('skills-sandbox-status-badge');
            if (!txt || !badge || !banner) return;
            if (s.all_ready) {
                var parts = [];
                if (s.bandit_version)    parts.push(s.bandit_version.replace('__main__.py ', 'bandit '));
                if (s.pip_audit_version) parts.push(s.pip_audit_version.replace('pip-audit ', 'pip-audit '));
                if (s.pyseccomp)         parts.push('pyseccomp ✔');
                txt.textContent = (parts.length ? parts.join(' · ') : 'All tools ready');
                badge.textContent = '✅ Ready';
                badge.style.background = '#16a34a';
                banner.style.background = '#f0fdf4';
                banner.style.borderColor = '#86efac';
                banner.style.color = '#166534';
            } else {
                var missing = [];
                if (!s.bandit)    missing.push('bandit');
                if (!s.pip_audit) missing.push('pip-audit');
                if (!s.pyseccomp) missing.push('pyseccomp');
                txt.textContent = 'Missing: ' + missing.join(', ');
                badge.textContent = '⚠ Partial';
                badge.style.background = '#d97706';
            }
        })
        .catch(function () { /* banner stays at default ⚠ Pending */ });
    },
    /* Legacy helpers kept for backward-compat */
    connect: function (skillId) {
        var r = ZYG_SANDBOX._store[skillId] || {};
        r._manual_connected = true; r._ts = Date.now();
        ZYG_SANDBOX._store[skillId] = r; ZYG_SANDBOX._save();
    },
    disconnect: function (skillId) {
        var r = ZYG_SANDBOX._store[skillId] || {};
        delete r._manual_connected; delete r._ts;
        ZYG_SANDBOX._store[skillId] = r; ZYG_SANDBOX._save();
    }
};

/* ─── Skills data ────────────────────────────────────────────────────────────── */
var SKILLS_DATA = [
    /* ═══ ESSAY SOURCING ═══ */
    {
        id: 'academic-deep-research',
        name: 'academic-deep-research',
        category: 'essay-sourcing',
        summary: 'Transparent, rigorous academic research with full source tracing.',
        creator: 'kesslerio',
        source: 'https://clawskills.sh/skills/kesslerio-academic-deep-research',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Essay Sourcing',
        functions: [
            'Deep multi-source academic paper search',
            'Full citation and source tracing',
            'Multi-query fallback strategy',
            'Research quality scoring'
        ],
        deps: ['Internet access', 'OpenClaw runtime']
    },
    {
        id: 'agentic-paper-digest',
        name: 'agentic-paper-digest',
        category: 'essay-sourcing',
        summary: 'Fetches and summarizes recent arXiv and HuggingFace papers automatically.',
        creator: 'matanle51',
        source: 'https://clawskills.sh/skills/matanle51-agentic-paper-digest',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Essay Sourcing',
        functions: [
            'arXiv paper discovery by topic',
            'HuggingFace paper search',
            'Automatic abstract summarisation',
            'Freshness filter (recent papers only)'
        ],
        deps: ['Internet access', 'arXiv API (free)']
    },
    {
        id: 'arxiv-watcher',
        name: 'arxiv-watcher',
        category: 'essay-sourcing',
        summary: 'Search and summarise papers from arXiv with topic-based discovery.',
        creator: 'rubenfb23',
        source: 'https://clawskills.sh/skills/rubenfb23-arxiv-watcher',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Essay Sourcing',
        functions: [
            'arXiv search by keyword / topic',
            'Paper metadata extraction (title, abstract, authors)',
            'Category filtering',
            'Summary generation'
        ],
        deps: ['Internet access', 'arXiv open API']
    },
    {
        id: 'baidu-scholar-search',
        name: 'baidu-scholar-search',
        category: 'essay-sourcing',
        summary: 'Baidu Academic Search — broader international coverage than Western APIs.',
        creator: 'jlpjavawayup',
        source: 'https://clawskills.sh/skills/jlpjavawayup-baidu-scholar-search',
        created: '2024', updated: '2024',
        stage: 'Stage 2 — Essay Sourcing',
        functions: [
            'Baidu Scholar API query',
            'Cross-lingual paper discovery',
            'Supplementary source for non-Western academic content'
        ],
        deps: ['Internet access', 'Baidu Scholar API key']
    },
    {
        id: 'book-reader',
        name: 'book-reader',
        category: 'essay-sourcing',
        summary: 'Read books and academic documents (epub, pdf, txt) with progress tracking.',
        creator: 'josharsh',
        source: 'https://clawskills.sh/skills/josharsh-book-reader',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Essay Sourcing / PDF Extraction',
        functions: [
            'epub / pdf / txt ingestion',
            'Chapter-by-chapter extraction',
            'Progress tracking',
            'Fallback plain-text reader'
        ],
        deps: ['Python', 'ebooklib (epub)', 'PyMuPDF or pdfminer (pdf)']
    },
    {
        id: 'boof',
        name: 'boof',
        category: 'essay-sourcing',
        summary: 'Convert PDFs to markdown, index locally for RAG retrieval and token-efficient analysis.',
        creator: 'killerapp',
        source: 'https://clawskills.sh/skills/killerapp-boof',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — PDF Extraction',
        functions: [
            'PDF → markdown conversion',
            'Local RAG index building',
            'Token-efficient chunk retrieval',
            'Full-text semantic search'
        ],
        deps: ['Python', 'PyMuPDF or pdfminer', 'Local embeddings model']
    },
    {
        id: 'paddleocr-doc-parsing',
        name: 'paddleocr-doc-parsing',
        category: 'essay-sourcing',
        summary: 'Parse scanned documents and PDFs using PaddleOCR — useful for locked/image-based PDFs.',
        creator: 'bobholamovic',
        source: 'https://clawskills.sh/skills/bobholamovic-paddleocr-doc-parsing',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — PDF Extraction (fallback for image PDFs)',
        functions: [
            'OCR-based text extraction from scanned PDFs',
            'PaddleOCR API integration',
            'Structured layout analysis',
            'Multi-language support'
        ],
        deps: ['PaddleOCR API endpoint', 'Internet access']
    },
    {
        id: 'call-academic-search-agent',
        name: 'call-academic-search-agent',
        category: 'essay-sourcing',
        summary: 'Orchestrated academic search agent — dispatches sub-agents for parallel paper retrieval.',
        creator: 'teamolab',
        source: 'https://clawskills.sh/skills/teamolab-call-academic-search-agent',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Essay Sourcing',
        functions: [
            'Multi-agent academic search dispatch',
            'Parallel API querying',
            'Result deduplication and ranking',
            'Fallback chain management'
        ],
        deps: ['Internet access', 'OpenClaw runtime', 'One or more academic API keys']
    },

    /* ═══ SPEECH & TTS ═══ */
    {
        id: 'elevenlabs-tts',
        name: 'elevenlabs-tts',
        category: 'speech-tts',
        summary: 'Best-in-class ElevenLabs TTS integration for OpenClaw — high-quality voice synthesis.',
        creator: 'shaharsha',
        source: 'https://clawskills.sh/skills/shaharsha-elevenlabs-tts',
        created: '2024', updated: '2025',
        stage: 'Stage 4 — TTS (IndexTTS-2 default, Chatterbox fallback)',
        functions: [
            'High-quality text-to-speech synthesis',
            'Voice selection and cloning',
            'Emotion and style control',
            'Streaming audio output'
        ],
        deps: ['ElevenLabs API key', 'Internet access']
    },
    {
        id: 'elevenlabs-cli',
        name: 'elevenlabs-cli',
        category: 'speech-tts',
        summary: 'CLI for ElevenLabs — TTS, STT, and voice cloning from the command line.',
        creator: 'hongkongkiwi',
        source: 'https://clawskills.sh/skills/hongkongkiwi-elevenlabs-cli',
        created: '2024', updated: '2025',
        stage: 'Stage 4 — TTS (IndexTTS-2 default, Chatterbox fallback)',
        functions: [
            'CLI-based TTS generation',
            'Speech-to-text transcription',
            'Voice cloning from audio sample',
            'Batch audio generation'
        ],
        deps: ['ElevenLabs API key', 'Node.js or Python']
    },
    {
        id: 'kokoro-tts',
        name: 'kokoro-tts',
        category: 'speech-tts',
        summary: 'Local Kokoro TTS engine — no API key, runs entirely on-device.',
        creator: 'edkief',
        source: 'https://clawskills.sh/skills/edkief-kokoro-tts',
        created: '2024', updated: '2025',
        stage: 'Stage 4 — TTS (local fallback alternative)',
        functions: [
            'Local on-device TTS (no API key)',
            'Multiple voice styles',
            'Fast inference on CPU/GPU',
            'Audio file export'
        ],
        deps: ['Python', 'kokoro-tts pip package', 'soundfile']
    },
    {
        id: 'local-llama-tts',
        name: 'local-llama-tts',
        category: 'speech-tts',
        summary: 'Local TTS using llama.cpp and OuteTTS-1.0-0.6B — privacy-first, runs on GPU.',
        creator: 'wuxxin',
        source: 'https://clawskills.sh/skills/wuxxin-local-llama-tts',
        created: '2024', updated: '2025',
        stage: 'Stage 4 — TTS (local GPU alternative)',
        functions: [
            'Local llama.cpp TTS via OuteTTS model',
            'GPU-accelerated inference',
            'No cloud dependency',
            'Configurable voice and speed'
        ],
        deps: ['llama.cpp built with CUDA', 'OuteTTS-1.0-0.6B model (~600 MB)', 'CUDA GPU']
    },
    {
        id: 'clonev',
        name: 'clonev',
        category: 'speech-tts',
        summary: 'Clone any voice and generate speech using Coqui XTTS v2 — local voice cloning.',
        creator: 'instant-picture',
        source: 'https://clawskills.sh/skills/instant-picture-clonev',
        created: '2024', updated: '2025',
        stage: 'Stage 4 — TTS / Voice Cloning',
        functions: [
            'Voice cloning from 6-second audio sample',
            'XTTS v2 multi-lingual synthesis',
            'Local inference (no API)',
            'Voice consistency across long narrations'
        ],
        deps: ['Python', 'TTS (Coqui) pip package', 'CUDA GPU (recommended)']
    },
    {
        id: 'faster-whisper',
        name: 'faster-whisper',
        category: 'speech-tts',
        summary: 'Local speech-to-text via faster-whisper — transcribe narration audio for QA.',
        creator: 'theplasmak',
        source: 'https://clawskills.sh/skills/theplasmak-faster-whisper',
        created: '2024', updated: '2025',
        stage: 'Stage 4 — Post-TTS QA (transcription check)',
        functions: [
            'Local Whisper-based STT transcription',
            'Multiple model sizes (tiny → large)',
            'Timestamp alignment',
            'Word-level confidence scoring'
        ],
        deps: ['Python', 'faster-whisper pip package', 'ctranslate2']
    },
    {
        id: 'auto-whisper-safe',
        name: 'auto-whisper-safe',
        category: 'speech-tts',
        summary: 'RAM-safe voice transcription with auto-chunking — safe on 16 GB machines.',
        creator: 'neal-collab',
        source: 'https://clawskills.sh/skills/neal-collab-auto-whisper-safe',
        created: '2024', updated: '2025',
        stage: 'Stage 4 — Post-TTS QA (safe transcription check)',
        functions: [
            'Chunked audio transcription (avoids OOM)',
            'Auto-detects audio length and splits safely',
            'Whisper model selection by available RAM',
            'Progress reporting per chunk'
        ],
        deps: ['Python', 'openai-whisper pip package', 'ffmpeg']
    },
    {
        id: 'assemblyai-transcribe',
        name: 'assemblyai-transcribe',
        category: 'speech-tts',
        summary: 'Cloud transcription with AssemblyAI — speaker diarisation and confidence scoring.',
        creator: 'tristanmanchester',
        source: 'https://clawskills.sh/skills/tristanmanchester-assemblyai-transcribe',
        created: '2024', updated: '2025',
        stage: 'Stage 4 — Post-TTS QA (cloud transcription)',
        functions: [
            'AssemblyAI cloud STT',
            'Speaker diarisation',
            'Word-level timestamps',
            'Automatic punctuation and formatting'
        ],
        deps: ['AssemblyAI API key', 'Internet access']
    },
    {
        id: 'siliconflow-tts-gen',
        name: 'siliconflow-tts-gen',
        category: 'speech-tts',
        summary: 'TTS via SiliconFlow API using CosyVoice2 — alternative cloud TTS.',
        creator: 'lilei0311',
        source: 'https://clawskills.sh/skills/lilei0311-siliconflow-tts-gen',
        created: '2025', updated: '2025',
        stage: 'Stage 4 — TTS (cloud alternative)',
        functions: [
            'CosyVoice2 TTS synthesis',
            'SiliconFlow API gateway',
            'Emotion-aware voice styles',
            'Multi-language output'
        ],
        deps: ['SiliconFlow API key', 'Internet access']
    },
    {
        id: 'chichi-speech',
        name: 'chichi-speech',
        category: 'speech-tts',
        summary: 'High-quality TTS using Qwen3 via a RESTful service — local or hosted.',
        creator: 'hudeven',
        source: 'https://clawskills.sh/skills/hudeven-chichi-speech',
        created: '2025', updated: '2025',
        stage: 'Stage 4 — TTS (alternative)',
        functions: [
            'Qwen3-based TTS inference',
            'RESTful HTTP API',
            'Natural prosody and pacing',
            'Configurable speaking rate and pitch'
        ],
        deps: ['chichi-speech server running', 'Python', 'Qwen3 TTS model weights']
    },

    /* ═══ IMAGE GENERATION ═══ */
    {
        id: 'comfyui',
        name: 'comfyui',
        category: 'image-generation',
        summary: 'Send workflow requests to ComfyUI and retrieve image results — local FLUX pipelines.',
        creator: 'xtopher86',
        source: 'https://clawskills.sh/skills/xtopher86-comfyui-request',
        created: '2024', updated: '2025',
        stage: 'Stage 3.5 — Image Generation (ComfyUI backend)',
        functions: [
            'Submit workflow JSON to ComfyUI API',
            'Poll and retrieve generated images',
            'Supports any ComfyUI workflow (FLUX, SD, ControlNet…)',
            'Batch generation support'
        ],
        deps: ['ComfyUI running at localhost:8188', 'CUDA GPU', 'ComfyUI workflow JSON']
    },
    {
        id: 'comfyui-imagegen',
        name: 'comfyui-imagegen',
        category: 'image-generation',
        summary: 'Generate images via ComfyUI API using a Flux2 workflow — pre-configured pipeline.',
        creator: 'halr9000',
        source: 'https://clawskills.sh/skills/halr9000-comfyui-imagegen',
        created: '2024', updated: '2025',
        stage: 'Stage 3.5 — Image Generation (Flux2 via ComfyUI)',
        functions: [
            'Pre-built Flux2 ComfyUI workflow',
            'Text prompt → image generation',
            'Resolution and step count control',
            'Auto-seed for reproducibility'
        ],
        deps: ['ComfyUI at localhost:8188', 'Flux2 model files', 'CUDA GPU ≥ 16 GB VRAM']
    },
    {
        id: 'fal-ai',
        name: 'fal-ai',
        category: 'image-generation',
        summary: 'Generate images, videos, and audio via fal.ai — FLUX, SDXL, Whisper and more.',
        creator: 'agmmnn',
        source: 'https://clawskills.sh/skills/agmmnn-fal-ai',
        created: '2024', updated: '2025',
        stage: 'Stage 3.5 — Image Generation (cloud FLUX) / Stage 4 (Whisper STT)',
        functions: [
            'FLUX and SDXL image generation via API',
            'Video generation endpoints',
            'Whisper audio transcription',
            'Consistent style via image-to-image'
        ],
        deps: ['fal.ai API key', 'Internet access']
    },
    {
        id: 'eachlabs-image-generation',
        name: 'eachlabs-image-generation',
        category: 'image-generation',
        summary: 'Generate images with Flux, GPT Image, Gemini, Imagen via each::sense API.',
        creator: 'eftalyurtseven',
        source: 'https://clawskills.sh/skills/eftalyurtseven-eachlabs-image-generation',
        created: '2024', updated: '2025',
        stage: 'Stage 3.5 — Image Generation (cloud multi-model)',
        functions: [
            'Flux / GPT Image / Gemini / Imagen backends',
            'Style reference image support',
            'Aspect ratio control',
            'Batch generation'
        ],
        deps: ['each::sense API key', 'Internet access']
    },
    {
        id: 'color-palette',
        name: 'color-palette',
        category: 'image-generation',
        summary: 'Extract a color palette from a generated image — ensures visual consistency across clips.',
        creator: 'qrost',
        source: 'https://clawskills.sh/skills/qrost-color-palette',
        created: '2024', updated: '2025',
        stage: 'Stage 3.5 — Image Post-Processing / Visual Consistency',
        functions: [
            'Extract dominant color palette from image',
            'Return HEX and RGB values',
            'Generate color swatch image',
            'Palette comparison across frames'
        ],
        deps: ['Python', 'Pillow or colorthief']
    },
    {
        id: 'depth-map-generation',
        name: 'depth-map-generation',
        category: 'image-generation',
        summary: 'Generate depth maps from images via each::sense AI — useful for parallax / 2.5D effects.',
        creator: 'eftalyurtseven',
        source: 'https://clawskills.sh/skills/eftalyurtseven-depth-map-generation',
        created: '2024', updated: '2025',
        stage: 'Stage 3.5 — Image Post-Processing (depth / parallax)',
        functions: [
            'Monocular depth estimation from FLUX image',
            'each::sense API integration',
            'Depth map export (greyscale PNG)',
            'Input for 2.5D video parallax effects'
        ],
        deps: ['each::sense API key', 'Internet access']
    },
    {
        id: 'art-philosophy',
        name: 'art-philosophy',
        category: 'image-generation',
        summary: 'Auto-learns your visual language — tracks style preferences and enforces consistency across prompts.',
        creator: 'nyxur42',
        source: 'https://clawskills.sh/skills/nyxur42-art-philosophy',
        created: '2024', updated: '2025',
        stage: 'Stage 3.5 — Image Prompt Consistency',
        functions: [
            'Visual style memory across pipeline runs',
            'Prompt enrichment with learned style tokens',
            'Style drift detection',
            'Preference profile persistence'
        ],
        deps: ['OpenClaw runtime', 'Local JSON storage']
    },

    /* ═══ VIDEO GENERATION ═══ */
    {
        id: 'ai-video-gen',
        name: 'ai-video-gen',
        category: 'video-generation',
        summary: 'End-to-end AI video generation from text — wraps multiple T2V backends.',
        creator: 'rhanbourinajd',
        source: 'https://clawskills.sh/skills/rhanbourinajd-ai-video-gen',
        created: '2024', updated: '2025',
        stage: 'Wan Integration — T2V Generation',
        functions: [
            'Text-to-video generation',
            'Multiple model backend support',
            'Clip duration control',
            'Prompt-to-scene mapping'
        ],
        deps: ['GPU with ≥ 16 GB VRAM', 'diffusers', 'Internet access (model download)']
    },
    {
        id: 'eachlabs-video-generation',
        name: 'eachlabs-video-generation',
        category: 'video-generation',
        summary: 'Generate videos from text or images using cloud AI models via each::sense.',
        creator: 'eftalyurtseven',
        source: 'https://clawskills.sh/skills/eftalyurtseven-eachlabs-video-generation',
        created: '2024', updated: '2025',
        stage: 'Wan Integration — T2V (cloud alternative)',
        functions: [
            'Text-to-video via each::sense API',
            'Image-to-video (animate a FLUX frame)',
            'Multiple model backends (Wan, SVD, etc.)',
            'Aspect ratio and duration control'
        ],
        deps: ['each::sense API key', 'Internet access']
    },
    {
        id: 'cine-cog',
        name: 'cine-cog',
        category: 'video-generation',
        summary: 'Full cinematic video generation — "if you can imagine it, CellCog can film it."',
        creator: 'nitishgargiitd',
        source: 'https://clawskills.sh/skills/nitishgargiitd-cine-cog',
        created: '2025', updated: '2025',
        stage: 'Wan Integration — Cinematic T2V',
        functions: [
            'Cinematic text-to-video via CellCog API',
            'Director-style prompt language',
            'Camera motion control',
            'High-quality 1080p output'
        ],
        deps: ['CellCog API key', 'Internet access']
    },
    {
        id: 'insta-cog',
        name: 'insta-cog',
        category: 'video-generation',
        summary: 'Full video production from a single prompt — end-to-end T2V pipeline.',
        creator: 'nitishgargiitd',
        source: 'https://clawskills.sh/skills/nitishgargiitd-insta-cog',
        created: '2025', updated: '2025',
        stage: 'Wan Integration — T2V Production',
        functions: [
            'Single-prompt full video production',
            'Scene breakdown and B-roll generation',
            'Auto music and TTS integration',
            'Export-ready MP4 output'
        ],
        deps: ['CellCog API key', 'Internet access']
    },
    {
        id: 'ffmpeg-video-editor',
        name: 'ffmpeg-video-editor',
        category: 'video-generation',
        summary: 'Generate FFmpeg commands from natural language — translate instructions to precise filters.',
        creator: 'mahmoudadelbghany',
        source: 'https://clawskills.sh/skills/mahmoudadelbghany-ffmpeg-video-editor',
        created: '2024', updated: '2025',
        stage: 'Wan Integration / Stage 6 — Video Editing',
        functions: [
            'Natural language → FFmpeg command generation',
            'Filter chain construction (xfade, overlay, scale, etc.)',
            'Validation of generated commands',
            'Batch processing support'
        ],
        deps: ['ffmpeg installed', 'LLM backend for command generation']
    },
    {
        id: 'heygen-avatar-lite',
        name: 'heygen-avatar-lite',
        category: 'video-generation',
        summary: 'Create AI digital human presenter videos with HeyGen API — talking head overlay.',
        creator: 'daaab',
        source: 'https://clawskills.sh/skills/daaab-heygen-avatar-lite',
        created: '2024', updated: '2025',
        stage: 'Wan Integration — Presenter Avatar',
        functions: [
            'AI digital human video creation',
            'Script-to-talking-head synthesis',
            'Avatar selection and customisation',
            'Overlay on B-roll background'
        ],
        deps: ['HeyGen API key', 'Internet access']
    },

    /* ═══ MEDIA ASSEMBLY ═══ */
    {
        id: 'ffmpeg-master',
        name: 'ffmpeg-master',
        category: 'media-assembly',
        summary: 'FFmpeg master skill — full video/audio processing specialist for pipeline assembly.',
        creator: 'liudu2326526',
        source: 'https://clawskills.sh/skills/liudu2326526-ffmpeg-master',
        created: '2024', updated: '2025',
        stage: 'Stage 6 — Media Assembly',
        functions: [
            'Full FFmpeg command library',
            'Video concatenation with transitions',
            'Audio normalisation and mixing',
            'Subtitle and caption burning'
        ],
        deps: ['ffmpeg installed (with libx264, libx265, aac)']
    },
    {
        id: 'mediaproc',
        name: 'mediaproc',
        category: 'media-assembly',
        summary: 'Process media files via a locked-down SSH container — secure, isolated media ops.',
        creator: 'psyb0t',
        source: 'https://clawskills.sh/skills/psyb0t-mediaproc',
        created: '2024', updated: '2025',
        stage: 'Stage 6 — Media Assembly (isolated)',
        functions: [
            'Sandboxed media processing via SSH',
            'Video, audio, and image manipulation',
            'ffmpeg + ImageMagick operations',
            'Result file retrieval'
        ],
        deps: ['SSH access', 'Docker container with ffmpeg / ImageMagick']
    },
    {
        id: 'media-player',
        name: 'media-player',
        category: 'media-assembly',
        summary: 'Play audio/video locally on the host — useful for previewing assembled clips.',
        creator: 'xejrax',
        source: 'https://clawskills.sh/skills/xejrax-media-player',
        created: '2024', updated: '2025',
        stage: 'Stage 6 — QA Preview',
        functions: [
            'Local playback of generated clips',
            'Support for mp4, webm, mp3, wav',
            'Volume and playback speed control',
            'Preview before upload'
        ],
        deps: ['vlc or mpv or system media player']
    },
    {
        id: 'captions',
        name: 'captions',
        category: 'media-assembly',
        summary: 'Extract closed captions and subtitles — source content for B-roll lookup or QA.',
        creator: 'therohitdas',
        source: 'https://clawskills.sh/skills/therohitdas-captions',
        created: '2024', updated: '2025',
        stage: 'Stage 6 — Caption / Subtitle Generation',
        functions: [
            'Closed caption extraction from YouTube',
            'SRT / VTT / plain-text output',
            'Multi-language caption support',
            'Timestamp alignment for burn-in'
        ],
        deps: ['Internet access', 'yt-dlp (optional)']
    },
    {
        id: 'podcast-chaptering-highlights',
        name: 'podcast-chaptering-highlights',
        category: 'media-assembly',
        summary: 'Create chapters, highlights, and show notes from audio or transcripts — for final deliverable.',
        creator: 'codedao12',
        source: 'https://clawskills.sh/skills/codedao12-podcast-chaptering-highlights',
        created: '2024', updated: '2025',
        stage: 'Stage 6 — Final Deliverable Enrichment',
        functions: [
            'Chapter marker generation from transcript',
            'Highlight clip identification',
            'Show notes draft generation',
            'YouTube description block output'
        ],
        deps: ['LLM API key or local LLM', 'Audio transcript (SRT or plain text)']
    },

    /* ═══ AI & SCRIPTING ═══ */
    {
        id: 'ai-humanizer',
        name: 'ai-humanizer',
        category: 'ai-scripting',
        summary: 'Humanize AI-generated narration by detecting and removing LLM output patterns.',
        creator: 'brandonwise',
        source: 'https://clawskills.sh/skills/brandonwise-ai-humanizer',
        created: '2024', updated: '2025',
        stage: 'Stage 3 — Script Writing (narration polish)',
        functions: [
            'Detect AI-written phrase patterns',
            'Replace with natural human phrasing',
            'Tone and style consistency check',
            'Output quality score'
        ],
        deps: ['LLM API key or local LLM']
    },
    {
        id: 'ai-writing-humanizer',
        name: 'ai-writing-humanizer',
        category: 'ai-scripting',
        summary: 'Strip AI writing stock phrases before sending narration to TTS — reduces robotic tone.',
        creator: 'hosthobbit',
        source: 'https://clawskills.sh/skills/hosthobbit-ai-writing-humanizer',
        created: '2024', updated: '2025',
        stage: 'Stage 3 — Script Writing (pre-TTS cleanup)',
        functions: [
            'Remove "It is worth noting…" and similar AI phrases',
            'Preserve factual content intact',
            'Configurable phrase blacklist',
            'Before/after diff output'
        ],
        deps: ['Python', 'regex or LLM backend']
    },
    {
        id: 'chief-editor',
        name: 'chief-editor',
        category: 'ai-scripting',
        summary: 'Professional chief editor persona — reviews and improves narration scripts.',
        creator: 'teamolab',
        source: 'https://clawskills.sh/skills/teamolab-chief-editor',
        created: '2024', updated: '2025',
        stage: 'Stage 3 — Script Writing (editorial review)',
        functions: [
            'Script structure review',
            'Hook and pacing improvement',
            'Factual accuracy flagging',
            'Tone alignment with topic'
        ],
        deps: ['LLM API key', 'Internet access']
    },
    {
        id: 'compression',
        name: 'compression',
        category: 'ai-scripting',
        summary: 'Pre-run prompt compression for iterative AI dev loops — reduces token usage.',
        creator: 'trinitybotserver',
        source: 'https://clawskills.sh/skills/trinitybotserver-compression',
        created: '2024', updated: '2025',
        stage: 'Stage 3 — Prompt Engineering (cost reduction)',
        functions: [
            'Compress long prompts before LLM calls',
            'Preserve semantic meaning',
            'Token usage reporting',
            'Iterative loop optimisation'
        ],
        deps: ['Python', 'LLM API key']
    },
    {
        id: 'agent-orchestrator',
        name: 'agent-orchestrator',
        category: 'ai-scripting',
        summary: 'Meta-agent skill for orchestrating complex multi-step tasks across sub-agents.',
        creator: 'aatmaan1',
        source: 'https://clawskills.sh/skills/aatmaan1-agent-orchestrator',
        created: '2024', updated: '2025',
        stage: 'Pipeline Orchestration — Cross-Stage Coordination',
        functions: [
            'Sub-agent dispatch and coordination',
            'Pipeline state management',
            'Error handling and retry logic',
            'Output aggregation'
        ],
        deps: ['OpenClaw runtime', 'LLM API key']
    },
    {
        id: 'context-gatekeeper',
        name: 'context-gatekeeper',
        category: 'ai-scripting',
        summary: 'Keeps conversation token-friendly by summarising recent exchanges and surfacing pending actions.',
        creator: 'davienzomq',
        source: 'https://clawskills.sh/skills/davienzomq-context-gatekeeper',
        created: '2025', updated: '2025',
        stage: 'Stage 3 — Script Writing (context management)',
        functions: [
            'Automatic conversation summarisation',
            'Pending action surfacing',
            'Token budget enforcement',
            'Context window health monitoring'
        ],
        deps: ['LLM API key', 'OpenClaw runtime']
    },

    /* ═══ ANALYTICS ═══ */
    {
        id: 'agentpulse',
        name: 'agentpulse',
        category: 'analytics',
        summary: 'Track LLM API costs, tokens, latency, and errors for your AI agent pipeline.',
        creator: 'sru4ka',
        source: 'https://clawskills.sh/skills/sru4ka-agentpulse',
        created: '2024', updated: '2025',
        stage: 'All Stages — Pipeline Cost & Performance Monitoring',
        functions: [
            'LLM API cost tracking (per-call and total)',
            'Token usage logging',
            'Latency percentile reporting',
            'Error rate and retry tracking'
        ],
        deps: ['agentpulse pip package', 'LLM API integration']
    },
    {
        id: 'daily-report',
        name: 'daily-report',
        category: 'analytics',
        summary: 'Track pipeline progress, report metrics, and manage run memory across sessions.',
        creator: 'visualdeptcreative',
        source: 'https://clawskills.sh/skills/visualdeptcreative-daily-report',
        created: '2024', updated: '2025',
        stage: 'All Stages — Daily Run Summary',
        functions: [
            'Daily pipeline run summary generation',
            'Success / failure metric tracking',
            'Stage timing breakdown',
            'Historical trend reporting'
        ],
        deps: ['Python', 'SQLite or JSON store']
    },
    {
        id: 'csv-pipeline',
        name: 'csv-pipeline',
        category: 'analytics',
        summary: 'Process, transform, analyse, and report on CSV and JSON pipeline data.',
        creator: 'gitgoodordietrying',
        source: 'https://clawskills.sh/skills/gitgoodordietrying-csv-pipeline',
        created: '2024', updated: '2025',
        stage: 'All Stages — Log & Data Analysis',
        functions: [
            'CSV / JSON ingestion and transformation',
            'Aggregation and pivot tables',
            'Anomaly detection in run logs',
            'Report generation and export'
        ],
        deps: ['Python', 'pandas', 'csv module']
    },
    {
        id: 'data-analyst',
        name: 'data-analyst',
        category: 'analytics',
        summary: 'Data visualisation, SQL queries, and report generation for pipeline telemetry.',
        creator: 'oyi77',
        source: 'https://clawskills.sh/skills/oyi77-data-analyst',
        created: '2024', updated: '2025',
        stage: 'All Stages — Visual Analytics & Reporting',
        functions: [
            'Data visualisation (charts, histograms)',
            'SQL query generation for SQLite logs',
            'Automated report templates',
            'VRAM / CPU / timing trend plots'
        ],
        deps: ['Python', 'matplotlib or plotly', 'pandas', 'SQLite']
    },
    /* ═══ WEB SCRAPING ═══ */
    {
        id: 'anycrawl',
        name: 'anycrawl',
        category: 'web-scraping',
        summary: 'AnyCrawl API — scrape, crawl, and search any website at scale.',
        creator: 'techlaai',
        source: 'https://clawskills.sh/skills/techlaai-anycrawl',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'Full-site crawl via AnyCrawl API',
            'Single-page scrape with JS rendering',
            'Web search aggregation',
            'Structured data extraction'
        ],
        deps: ['AnyCrawl API key', 'Internet access']
    },
    {
        id: 'stealthy-google-search',
        name: 'stealthy-google-search',
        category: 'web-scraping',
        summary: 'Google search via Scrapling\'s StealthyFetcher — bypasses bot detection.',
        creator: 'itzsubhadip',
        source: 'https://clawskills.sh/skills/itzsubhadip-stealthy-google-search',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'Google search without API key',
            'Bot-detection bypass (StealthyFetcher)',
            'Result parsing (titles, snippets, URLs)',
            'Wikipedia / any public site fetch'
        ],
        deps: ['Python', 'Scrapling library']
    },
    {
        id: 'exa-tool',
        name: 'exa-tool',
        category: 'web-scraping',
        summary: 'Exa MCP — neural web search, crawling, and deep content extraction.',
        creator: 'claireaicodes',
        source: 'https://clawskills.sh/skills/claireaicodes-exa-tool',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'Semantic neural web search',
            'Full-page content crawl',
            'Similar-page discovery',
            'Research mode (auto multi-query)'
        ],
        deps: ['Exa API key', 'Internet access']
    },
    {
        id: 'super-browser',
        name: 'super-browser',
        category: 'web-scraping',
        summary: 'Ultimate browser automation framework — combines 8 top browser skills.',
        creator: 'heldinhow',
        source: 'https://clawskills.sh/skills/heldinhow-super-browser',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'Multi-engine browser dispatch',
            'JS-rendered page scraping',
            'Form interaction and login flows',
            'Screenshot and PDF capture'
        ],
        deps: ['OpenClaw runtime', 'Browser engine (Playwright / Puppeteer)']
    },
    {
        id: 'camoufox',
        name: 'camoufox',
        category: 'web-scraping',
        summary: 'Anti-detect browser automation using Camoufox (Firefox-based).',
        creator: 'goodgoodjm',
        source: 'https://clawskills.sh/skills/goodgoodjm-camoufox',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'Fingerprint-masked browser sessions',
            'Bypass Cloudflare and anti-bot checks',
            'JS-heavy site scraping',
            'Headless Firefox automation'
        ],
        deps: ['Python', 'Camoufox (pip)', 'Firefox']
    },
    {
        id: 'browser-use',
        name: 'browser-use',
        category: 'web-scraping',
        summary: 'Cloud browser API — spin up remote browsers for scraping tasks.',
        creator: 'shawnpana',
        source: 'https://clawskills.sh/skills/shawnpana-browser-use',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'Cloud-hosted browser sessions',
            'Navigate, click, type on any page',
            'Extract text and structured data',
            'Screenshot and content export'
        ],
        deps: ['Browser Use API key', 'Internet access']
    },
    {
        id: 'mcp-chrome',
        name: 'mcp-chrome',
        category: 'web-scraping',
        summary: 'Control Chrome via MCP protocol — full browser automation with AI.',
        creator: 'femto',
        source: 'https://clawskills.sh/skills/femto-mcp-chrome',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'Chrome tab management',
            'Page navigation and DOM extraction',
            'Click / scroll / form fill',
            'Screenshot capture'
        ],
        deps: ['Chrome browser', 'MCP Chrome extension']
    },
    {
        id: 'cdp-browser',
        name: 'cdp-browser',
        category: 'web-scraping',
        summary: 'Direct Chrome DevTools Protocol control at localhost:9222.',
        creator: 'gostlightai',
        source: 'https://clawskills.sh/skills/gostlightai-cdp-browser',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'Raw CDP commands to Chrome',
            'DOM inspection and extraction',
            'Network request interception',
            'Headless automation'
        ],
        deps: ['Chrome / Chromium with --remote-debugging-port=9222']
    },
    {
        id: 'youtube-scrapper',
        name: 'youtube-scrapper',
        category: 'web-scraping',
        summary: 'Discover and scrape YouTube channels by category/location — no API key needed.',
        creator: 'arulmozhiv',
        source: 'https://clawskills.sh/skills/arulmozhiv-youtube-scrapper',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'Channel discovery by topic / location',
            'Video metadata extraction',
            'No YouTube API key required',
            'Category-filtered results'
        ],
        deps: ['Python', 'Internet access']
    },
    {
        id: 'instagram-scraper',
        name: 'instagram-scraper',
        category: 'web-scraping',
        summary: 'Browser-based Instagram profile discovery and scraping tool.',
        creator: 'arulmozhiv',
        source: 'https://clawskills.sh/skills/arulmozhiv-instagram-scraper',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'Profile metadata scraping',
            'Post and follower count extraction',
            'Browser-based (no private API)',
            'Bulk profile discovery'
        ],
        deps: ['Python', 'Playwright or Selenium', 'Internet access']
    },
    {
        id: 'tiktok-crawling',
        name: 'tiktok-crawling',
        category: 'web-scraping',
        summary: 'TikTok crawling, content retrieval, and analysis.',
        creator: 'romneyda',
        source: 'https://clawskills.sh/skills/romneyda-tiktok-crawling',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'TikTok video and profile crawling',
            'Hashtag / trend discovery',
            'Content metadata extraction',
            'Engagement analytics'
        ],
        deps: ['Python', 'Internet access']
    },
    {
        id: 'apify-lead-generation',
        name: 'apify-lead-generation',
        category: 'web-scraping',
        summary: 'B2B/B2C lead generation by scraping Google Maps, LinkedIn, and directories.',
        creator: 'jirispilka',
        source: 'https://clawskills.sh/skills/jirispilka-apify-lead-generation',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'Google Maps business scraping',
            'LinkedIn profile extraction',
            'Directory and listing crawl',
            'Structured lead data output'
        ],
        deps: ['Apify API key', 'Internet access']
    },
    {
        id: 'amazon-product-search-api-skill',
        name: 'amazon-product-search-api-skill',
        category: 'web-scraping',
        summary: 'Extract product data from Amazon search results via API.',
        creator: 'phheng',
        source: 'https://clawskills.sh/skills/phheng-amazon-product-search-api-skill',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'Amazon search result extraction',
            'Price, rating, and ASIN data',
            'Bulk product comparison',
            'Category filtering'
        ],
        deps: ['Amazon Product API key', 'Internet access']
    },
    {
        id: 'amazon-reviews-api-skill',
        name: 'amazon-reviews-api-skill',
        category: 'web-scraping',
        summary: 'Extract Amazon product reviews via the Amazon Reviews API.',
        creator: 'phheng',
        source: 'https://clawskills.sh/skills/phheng-amazon-reviews-api-skill',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'Star rating and review text extraction',
            'Verified-purchase filtering',
            'Sentiment-ready structured output',
            'Bulk ASIN review download'
        ],
        deps: ['Amazon Reviews API key', 'Internet access']
    },
    {
        id: 'daily-news',
        name: 'daily-news',
        category: 'web-scraping',
        summary: 'Fetch top news from Baidu, Google, and other sources daily.',
        creator: 'ym2760184260',
        source: 'https://clawskills.sh/skills/ym2760184260-daily-news',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'Google News top stories fetch',
            'Baidu news aggregation',
            'Multi-source deduplication',
            'Daily digest generation'
        ],
        deps: ['Internet access']
    },
    {
        id: 'url2pdf',
        name: 'url2pdf',
        category: 'web-scraping',
        summary: 'Convert any URL to PDF — capture full rendered page content.',
        creator: 'guoqiao',
        source: 'https://clawskills.sh/skills/guoqiao-url2pdf',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'Full-page URL to PDF conversion',
            'JS-rendered content capture',
            'Wikipedia / article archiving',
            'Mobile-optimised output'
        ],
        deps: ['Internet access', 'Headless browser or PDF API']
    },
    {
        id: 'url2png',
        name: 'url2png',
        category: 'web-scraping',
        summary: 'Convert any URL to PNG screenshot — visual page capture.',
        creator: 'guoqiao',
        source: 'https://clawskills.sh/skills/guoqiao-url2png',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'Full-page screenshot as PNG',
            'JS-rendered visual capture',
            'Viewport and scroll configuration',
            'Mobile-optimised output'
        ],
        deps: ['Internet access', 'Headless browser or screenshot API']
    },
    {
        id: 'x-tweet-fetcher',
        name: 'x-tweet-fetcher',
        category: 'web-scraping',
        summary: 'Fetch tweets from X/Twitter without login or API keys.',
        creator: 'hjw21century',
        source: 'https://clawskills.sh/skills/hjw21century-x-tweet-fetcher',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'Tweet content fetch without API key',
            'Thread and reply extraction',
            'User timeline scraping',
            'Keyword / hashtag search'
        ],
        deps: ['Internet access']
    },
    {
        id: 'phantombuster',
        name: 'phantombuster',
        category: 'web-scraping',
        summary: 'Control PhantomBuster automation agents — LinkedIn, Google, social scraping.',
        creator: 'capt-marbles',
        source: 'https://clawskills.sh/skills/capt-marbles-phantombuster',
        created: '2024', updated: '2025',
        stage: 'Stage 2 — Web Research',
        functions: [
            'LinkedIn profile and post scraping',
            'Google search result extraction',
            'Instagram / Twitter automation',
            'Scheduled scraping agents'
        ],
        deps: ['PhantomBuster API key', 'Internet access']
    }
];

/* ─── Category config ────────────────────────────────────────────────────────── */
var CATEGORIES = [
    { id: 'all',               label: '🔍 All',               color: '#374151', bg: '#f3f4f6' },
    { id: 'essay-sourcing',    label: '📚 Essay Sourcing',    color: '#1e40af', bg: '#dbeafe' },
    { id: 'speech-tts',        label: '🎙️ Speech & TTS',      color: '#065f46', bg: '#d1fae5' },
    { id: 'image-generation',  label: '🖼️ Image Generation',  color: '#7c3aed', bg: '#ede9fe' },
    { id: 'video-generation',  label: '🎥 Video Generation',  color: '#b45309', bg: '#fef3c7' },
    { id: 'media-assembly',    label: '🎞️ Media Assembly',    color: '#0f766e', bg: '#ccfbf1' },
    { id: 'ai-scripting',      label: '🤖 AI & Scripting',    color: '#9d174d', bg: '#fce7f3' },
    { id: 'analytics',         label: '📊 Analytics',         color: '#1d4ed8', bg: '#eff6ff' },
    { id: 'web-scraping',      label: '🕷️ Web Scraping',      color: '#065f46', bg: '#dcfce7' }
];

function getCatConfig(id) {
    return CATEGORIES.find(function (c) { return c.id === id; }) || CATEGORIES[0];
}

/* ─── State ──────────────────────────────────────────────────────────────────── */
var _activeCategory = 'all';

/* ─── Render helpers ─────────────────────────────────────────────────────────── */
function escHtml(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function renderCategoryPills(bar) {
    bar.innerHTML = '<span style="font-size:11px; color:#9ca3af; margin-right:4px;">Filter:</span>';
    CATEGORIES.forEach(function (cat) {
        var pill = document.createElement('button');
        pill.type = 'button';
        pill.setAttribute('data-skills-cat', cat.id);
        pill.style.cssText = 'padding:3px 10px; border-radius:12px; border:1px solid ' + cat.color + '; background:' + (cat.id === _activeCategory ? cat.bg : '#fff') + '; color:' + cat.color + '; font-size:11px; font-weight:600; cursor:pointer; transition:background 0.15s;';
        pill.textContent = cat.label;
        pill.addEventListener('click', function () {
            _activeCategory = cat.id;
            renderCategoryPills(bar);
            renderSkillCards();
        });
        bar.appendChild(pill);
    });
}

function renderSkillCards() {
    var grid = document.getElementById('skills-grid');
    var countEl = document.getElementById('skills-count-label');
    if (!grid) return;

    var visible = _activeCategory === 'all'
        ? SKILLS_DATA
        : SKILLS_DATA.filter(function (s) { return s.category === _activeCategory; });

    if (countEl) countEl.textContent = 'Showing ' + visible.length + ' of ' + SKILLS_DATA.length + ' skills';
    grid.innerHTML = '';

    visible.forEach(function (skill) {
        var cat = getCatConfig(skill.category);
        var card = document.createElement('div');
        card.setAttribute('data-skill-id', skill.id);
        card.title = skill.functions.join(' · ');
        card.style.cssText = [
            'background:#fff',
            'border:1px solid #e5e7eb',
            'border-radius:8px',
            'padding:10px 12px',
            'cursor:pointer',
            'display:flex',
            'flex-direction:column',
            'gap:5px',
            'transition:box-shadow 0.15s,border-color 0.15s'
        ].join(';');

        card.innerHTML = [
            '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">',
            '  <span style="padding:1px 7px;border-radius:8px;font-size:9px;font-weight:700;color:' + escHtml(cat.color) + ';background:' + escHtml(cat.bg) + ';white-space:nowrap;">' + escHtml(cat.label) + '</span>',
            '</div>',
            '<div style="font-size:12px;font-weight:700;color:#111827;word-break:break-all;">' + escHtml(skill.name) + '</div>',
            '<div style="font-size:11px;color:#6b7280;line-height:1.4;">' + escHtml(skill.summary) + '</div>',
            '<div style="font-size:10px;color:#9ca3af;margin-top:2px;">by ' + escHtml(skill.creator) + '</div>'
        ].join('');

        card.addEventListener('mouseenter', function () {
            card.style.boxShadow = '0 2px 8px rgba(0,0,0,0.12)';
            card.style.borderColor = cat.color;
        });
        card.addEventListener('mouseleave', function () {
            card.style.boxShadow = '';
            card.style.borderColor = '#e5e7eb';
        });
        card.addEventListener('click', function () { openSkillsDialog(skill.id); });

        grid.appendChild(card);
    });
}

/* ─── Dialog ─────────────────────────────────────────────────────────────────── */
/* ─── Sandbox section renderer ───────────────────────────────────────────────── */
function _verdictStyle(verdict) {
    var map = {
        'SAFE':    { bg: '#f0fdf4', border: '#86efac', color: '#16a34a', icon: '✅' },
        'UNSAFE':  { bg: '#fef2f2', border: '#fca5a5', color: '#dc2626', icon: '🚫' },
        'REVIEW':  { bg: '#fefce8', border: '#fde68a', color: '#d97706', icon: '⚠️' },
        'PENDING': { bg: '#f9fafb', border: '#e5e7eb', color: '#6b7280', icon: '⏳' }
    };
    return map[verdict] || map['PENDING'];
}

function _renderSandboxSection(skill) {
    var cached = ZYG_SANDBOX.check(skill.id);
    if (!cached || !cached.verdict) {
        return [
            '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">',
            '  <span style="font-size:12px;color:#78716c;">Not yet checked. Click to run static analysis, dependency audit, and behavioral probe.</span>',
            '  <button type="button" id="skills-sandbox-run-btn" data-skill-id="' + escHtml(skill.id) + '" ',
            '    style="padding:4px 12px;background:#2563eb;color:#fff;border:none;border-radius:5px;font-size:11px;cursor:pointer;">',
            '    🔍 Run Sandbox Check',
            '  </button>',
            '</div>'
        ].join('');
    }
    var vs = _verdictStyle(cached.verdict);
    var rows = [];

    /* Static analysis */
    var st = cached.static || {};
    rows.push('<div style="margin-top:8px;">');
    rows.push('<span style="font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;">Layer 1 · Static Analysis</span>');
    rows.push('<div style="font-size:11px;color:#374151;margin-top:2px;">' + escHtml(st.summary || '—') + '</div>');
    if (st.issues && st.issues.length) {
        rows.push('<ul style="margin:4px 0 0 14px;padding:0;font-size:11px;color:#374151;">');
        st.issues.slice(0, 8).forEach(function (iss) {
            var c = iss.severity === 'HIGH' ? '#dc2626' : iss.severity === 'MEDIUM' ? '#d97706' : '#6b7280';
            rows.push('<li style="margin-bottom:2px;"><span style="color:' + c + ';font-weight:700;">[' + escHtml(iss.severity) + ']</span> ' + escHtml(iss.text) + '</li>');
        });
        if (st.issues.length > 8) rows.push('<li style="color:#9ca3af;">…and ' + (st.issues.length - 8) + ' more</li>');
        rows.push('</ul>');
    }
    rows.push('</div>');

    /* Dependency audit */
    var dep = cached.deps || {};
    rows.push('<div style="margin-top:8px;">');
    rows.push('<span style="font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;">Layer 2 · Dependency Audit</span>');
    rows.push('<div style="font-size:11px;color:#374151;margin-top:2px;">' + escHtml(dep.summary || '—') + '</div>');
    if (dep.vulns && dep.vulns.length) {
        rows.push('<ul style="margin:4px 0 0 14px;padding:0;font-size:11px;color:#dc2626;">');
        dep.vulns.forEach(function (v) {
            rows.push('<li>' + escHtml(v.package) + ' — ' + escHtml(v.cve) + ': ' + escHtml(v.desc) + '</li>');
        });
        rows.push('</ul>');
    }
    rows.push('</div>');

    /* Behavioral probe */
    var beh = cached.behavioral || {};
    rows.push('<div style="margin-top:8px;">');
    rows.push('<span style="font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;">Layer 3 · Behavioral Probe</span>');
    rows.push('<div style="font-size:11px;color:#374151;margin-top:2px;">' + escHtml(beh.summary || 'No code provided for behavioral probe') + '</div>');
    rows.push('</div>');

    /* Timestamp + Re-run */
    var ts = cached.timestamp ? (' · ' + new Date(cached.timestamp).toLocaleString()) : '';

    return [
        '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:6px 10px;background:' + vs.bg + ';border:1px solid ' + vs.border + ';border-radius:5px;">',
        '  <span style="font-size:14px;">' + vs.icon + '</span>',
        '  <span style="font-size:13px;font-weight:700;color:' + vs.color + ';">' + escHtml(cached.verdict) + '</span>',
        '  <span style="font-size:10px;color:#9ca3af;">' + escHtml(ts) + '</span>',
        '  <span style="flex:1;"></span>',
        '  <button type="button" id="skills-sandbox-run-btn" data-skill-id="' + escHtml(skill.id) + '" ',
        '    style="padding:3px 9px;background:#6b7280;color:#fff;border:none;border-radius:5px;font-size:10px;cursor:pointer;">',
        '    🔄 Re-run',
        '  </button>',
        '</div>',
        rows.join('')
    ].join('');
}

function openSkillsDialog(skillId) {
    var skill = SKILLS_DATA.find(function (s) { return s.id === skillId; });
    if (!skill) return;
    var cat = getCatConfig(skill.category);

    var overlay = document.getElementById('skills-dialog-overlay');
    var badge   = document.getElementById('skills-dialog-cat-badge');
    var nameEl  = document.getElementById('skills-dialog-name');
    var body    = document.getElementById('skills-dialog-body');
    if (!overlay) return;

    badge.textContent = cat.label;
    badge.style.cssText = 'padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;color:' + cat.color + ';background:' + cat.bg + ';';
    nameEl.textContent = skill.name;

    var funcsHtml = skill.functions.map(function (f) {
        return '<li style="margin-bottom:3px;">' + escHtml(f) + '</li>';
    }).join('');
    var depsHtml = skill.deps.map(function (d) {
        return '<li style="margin-bottom:3px;">' + escHtml(d) + '</li>';
    }).join('');

    body.innerHTML = [
        /* Summary */
        '<div>',
        '  <div style="font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:0.07em;margin-bottom:4px;">📋 Summary</div>',
        '  <p style="margin:0;color:#374151;line-height:1.5;">' + escHtml(skill.summary) + '</p>',
        '</div>',
        /* Creator + link */
        '<div style="display:flex;gap:16px;flex-wrap:wrap;">',
        '  <div>',
        '    <div style="font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:0.07em;margin-bottom:3px;">👤 Creator</div>',
        '    <span style="color:#374151;font-weight:600;">' + escHtml(skill.creator) + '</span>',
        '  </div>',
        '  <div>',
        '    <div style="font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:0.07em;margin-bottom:3px;">🔗 Source</div>',
        '    <a href="' + escHtml(skill.source) + '" target="_blank" rel="noopener" style="color:#2563eb;font-size:12px;">clawskills.sh ↗</a>',
        '  </div>',
        '  <div>',
        '    <div style="font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:0.07em;margin-bottom:3px;">🗓 Created / Updated</div>',
        '    <span style="color:#374151;">' + escHtml(skill.created) + ' / ' + escHtml(skill.updated) + '</span>',
        '  </div>',
        '</div>',
        /* Pipeline stage */
        '<div>',
        '  <div style="font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:0.07em;margin-bottom:4px;">🎬 Pipeline Stage</div>',
        '  <span style="padding:3px 9px;background:#f0fdf4;border:1px solid #86efac;border-radius:5px;color:#166534;font-size:12px;font-weight:600;">' + escHtml(skill.stage) + '</span>',
        '</div>',
        /* Functions */
        '<div>',
        '  <div style="font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:0.07em;margin-bottom:4px;">⚡ Functions</div>',
        '  <ul style="margin:0;padding-left:16px;color:#374151;font-size:12px;line-height:1.6;">' + funcsHtml + '</ul>',
        '</div>',
        /* Dependencies */
        '<div>',
        '  <div style="font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:0.07em;margin-bottom:4px;">📦 Dependencies</div>',
        '  <ul style="margin:0;padding-left:16px;color:#374151;font-size:12px;line-height:1.6;">' + depsHtml + '</ul>',
        '</div>',
        /* Sandbox check */
        '<div id="skills-sandbox-detail" style="padding:10px 12px;background:#fffbeb;border:1px solid #fcd34d;border-radius:6px;">',
        '  <div style="font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:0.07em;margin-bottom:6px;">🔒 Sandbox Security Check</div>',
        _renderSandboxSection(skill),
        '</div>',
        /* Disclaimer */
        '<div style="padding:6px 10px;background:#f9fafb;border-radius:5px;font-size:10px;color:#9ca3af;">',
        '  ⚠ This skill is <strong>not installed or active</strong>. It is listed for planning and evaluation only. Source: VoltAgent / awesome-openclaw-skills.',
        '</div>'
    ].join('');

    /* Sandbox run-check button */
    var runBtn = document.getElementById('skills-sandbox-run-btn');
    if (runBtn) {
        runBtn.addEventListener('click', function () {
            var sid  = this.getAttribute('data-skill-id');
            var deps = (SKILLS_DATA.find(function (s) { return s.id === sid; }) || {}).deps || [];
            var detail = document.getElementById('skills-sandbox-detail');
            if (detail) {
                detail.innerHTML = '<div style="font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:0.07em;margin-bottom:6px;">🔒 Sandbox Security Check</div>'
                    + '<div style="font-size:12px;color:#6b7280;">⏳ Running checks… (static analysis + dep audit + behavioral probe)</div>';
            }
            ZYG_SANDBOX.runCheck(sid, deps, function (result, err) {
                if (detail) {
                    var skill = SKILLS_DATA.find(function (s) { return s.id === sid; }) || {};
                    detail.innerHTML = '<div style="font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:0.07em;margin-bottom:6px;">🔒 Sandbox Security Check</div>'
                        + _renderSandboxSection(skill);
                    /* re-attach button */
                    var nb = detail.querySelector('#skills-sandbox-run-btn');
                    if (nb) nb.addEventListener('click', arguments.callee.caller);
                }
            });
        });
    }

    overlay.style.display = 'flex';
    document.addEventListener('keydown', _onEscKey);
}

function closeSkillsDialog() {
    var overlay = document.getElementById('skills-dialog-overlay');
    if (overlay) overlay.style.display = 'none';
    document.removeEventListener('keydown', _onEscKey);
}
window.closeSkillsDialog = closeSkillsDialog;

function _onEscKey(e) {
    if (e.key === 'Escape') closeSkillsDialog();
}

/* ─── Init ───────────────────────────────────────────────────────────────────── */
function initSkillsPanel() {
    var bar = document.getElementById('skills-category-bar');
    if (bar) renderCategoryPills(bar);
    renderSkillCards();
    /* Load real sandbox status into the banner */
    ZYG_SANDBOX.loadStatus();
}

document.addEventListener('DOMContentLoaded', function () {
    /* Wire up the skills subtab click so initSkillsPanel runs on first open */
    var mechanicsPanel = document.getElementById('panel-mechanics');
    if (!mechanicsPanel) return;
    var subtabBtns = mechanicsPanel.querySelectorAll('.mechanics-subtab');
    subtabBtns.forEach(function (btn) {
        if (btn.getAttribute('data-mechanics-subtab') === 'skills') {
            btn.addEventListener('click', function () {
                /* small delay so the panel is visible first */
                setTimeout(initSkillsPanel, 20);
            }, { once: false });
        }
    });
    /* Also initialise immediately in case the tab is already active on load */
    var skillsPanel = document.getElementById('mechanics-skills');
    if (skillsPanel && skillsPanel.style.display !== 'none') {
        initSkillsPanel();
    }
});

})();
