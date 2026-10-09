# How the most popular GitHub projects present themselves — and what our portfolio takes from it

Researched 2026-10-04. Twenty flagship repositories, one per popular GitHub topic,
read live (raw README plus the project's own landing site). The question was:
how do they do their "slideshow" (hero, demo media, screenshots) and how do they
explain what the program does. The findings drive `zpub_portfolio_deck.py`,
the movie engine `templates/assets/js/zpub_portfolio_movie.js` and the card on
the Zero invite page.

## The twenty repositories

| Topic | Repo | Stars (approx) | Hero above the fold | Demo media in README |
|---|---|---|---|---|
| javascript | facebook/react | 250 k | 5 badges, 9-word tagline | none |
| python / ml | tensorflow/tensorflow | 200 k | logo, 11 badges | none |
| machine-learning | huggingface/transformers | 165 k | logo, 7 badges, architecture PNG | 2 stills in collapsibles |
| ai | comfyanonymous/ComfyUI | 136 k | 7 live-stat badges, 1 big screenshot | 1 screenshot |
| llm | ollama/ollama | 182 k | logo, 4-word tagline, install one-liners | none |
| typescript | microsoft/vscode | 193 k | title, 2 badges | 1 screenshot |
| react framework | vercel/next.js | 143 k | logo (light/dark), 4 badges | none |
| vue | vuejs/core | 54 k | title with 3 inline badges | none |
| css | tailwindlabs/tailwindcss | 98 k | logo, 8-word tagline, 4 badges | none |
| runtime | oven-sh/bun | 96 k | logo, 3 badges, nav strip | none |
| devops | kubernetes/kubernetes | 128 k | 2 badges, logo | none |
| shell | ohmyzsh/ohmyzsh | 190 k | ANSI logo, tagline, 5 badges | 1 themed screenshot |
| rust | rust-lang/rust (+ tauri) | 119 k | logo (light/dark), tagline, nav row | none (tauri: 1 splash) |
| go | gin-gonic/gin | 89 k | logo, 8 badges, release banner | none |
| database | supabase/supabase | 111 k | logo, tagline, dashboard screenshot | 1 screenshot, 1 GIF, 1 SVG diagram |
| automation | n8n-io/n8n | 207 k | banner, 12-word tagline | 2 stills |
| whiteboard | excalidraw/excalidraw | 134 k | logo (light/dark), tagline, 6 badges | 1 hero screenshot |
| home-automation | home-assistant/core | 91 k | title, chat badge, tagline | 2 screenshots |
| generative-art | AUTOMATIC1111/stable-diffusion-webui | 165 k | plain title, one line | 1 screenshot |
| video / media | obsproject/obs-studio | 77 k | title, tagline, 3 badges | none |

## Twenty essential things they have in common

Presentation (the "slideshow")

1. **Identity first.** Name or logo, then one sentence, before anything else. Nobody opens with a picture or a paragraph.
2. **A badge row as the trust signal.** Build, licence, version, downloads, community. It is the one universal above-the-fold element, used even when there is no other imagery.
3. **The tagline is one sentence of 9 to 16 words.** React 9, Tailwind 8, n8n 12, Home Assistant 13, OBS 16. Longer is a paragraph, shorter is a slogan.
4. **The tagline says WHAT it is, not WHY it matters.** All twenty. Benefit language, if any, comes in the second sentence or a later section.
5. **One hero picture at most.** When a screenshot exists it is a single frame of the real product, placed right under the badges, never a gallery.
6. **No animated GIF, no autoplaying video, no carousel in the README.** Zero of twenty. Where motion exists (comfy.org, bun.com, n8n.io) it lives on the project's own site.
7. **The rich showcase is a separate page.** The README is a dispatcher of links; the full visual story is one click away on a dedicated domain.
8. **Real product frames, never staged mockups.** VS Code uses literal runnable code, Bun uses terminal transcripts, Supabase its own dashboard.
9. **Light and dark variants of the hero.** Next.js, Tailwind, Excalidraw, Rust, Supabase swap the logo with `<picture>` and `prefers-color-scheme`.
10. **Live numbers beat static decoration.** ComfyUI's Discord and download counters, Transformers' checkpoint counter, OBS's translation progress.

Explanation (how they explain the program)

11. **Quick start is the first real section.** Install or run, as a copyable block, within the first screen. Every repo that explains itself at all does this first.
12. **A features list of short bullets, each one a capability.** Excalidraw 12, Tauri 8, n8n 6, Transformers "Why should I use" list. Prose paragraphs are rare.
13. **Numbers are the proof.** Gin's 29-framework benchmark table, Bun's bar charts, Ollama's install counters. A measured figure replaces a demo.
14. **Honesty about limits.** Transformers has "When shouldn't I use Transformers?"; ohmyzsh jokes it will not make you a 10x developer. The counter-pitch builds trust.
15. **"Who uses it" is shown, not claimed.** Logos (Excalidraw, Tailwind), a showcase page (Next.js), a projects list (Transformers), testimonials (Bun).
16. **An architecture picture only when the system is a composition.** Supabase and Transformers have one; the single-purpose tools do not. Draw the mechanism, not the org chart.
17. **Comparison tables anchor to something the reader knows.** Supabase against Firebase, Bun against Node and Deno, Gin against the other Go frameworks.
18. **Consistent section order.** What it is → quick start → features → docs → community → contributing → licence. Readers know where to look.
19. **Short README, deep docs.** Tailwind has three sections; Vue's README barely explains Vue. Depth is delegated, the front door stays light.
20. **Personality in one line only.** ohmyzsh's joke, Gin's emoji headers, Ollama's "Start building". One deliberate note of character, never a theme.

## What the portfolio deck does with this

| Pattern | In the deck |
|---|---|
| 1, 3, 4 | Hero: name, then a 14-word WHAT-first tagline |
| 2, 13 | The hero's "badge row" is four measured facts (13 studios, workstation date, € 0.015 per episode, 0 human steps) |
| 5, 8 | Every picture is a real screenshot of the running product, one per slide |
| 6, 7 | The invite page card holds a single cover frame; the film plays only when play is pressed, and the full presentation is its own page |
| 11, 18 | Chapter order: what a video is made of → the studios → the taught skill → how it is built → what it costs → what runs underneath → closing |
| 12 | Every slide: one-line WHAT plus at most three bullets |
| 14 | A "Known limits" slide (no local VLM sees an extra finger; identity spread is never continuity) |
| 15 | Numbers from the written portfolio, nothing invented |
| 16 | "What runs underneath" is one slide, not a diagram tour |
| 19 | The card stays light; depth lives in the chapters and the "more screens" index |
| 20 | One line of character at the close: "in all humbleness, I thank you for your time" |

The pictures play like a film because stills alone break patterns 5 and 6 the
moment there are 42 of them: the engine gives each one a Ken Burns drift, a
crossfade, a lower-third caption paced to reading time, and chapter cards, so
the deck reads as a single 8-9 minute piece rather than a gallery.
