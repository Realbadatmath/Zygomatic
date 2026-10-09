# Commercial 3D-gen / capture / motion SERVICES within 150 EUR — research notes (2026-09-02)

Tags: MEASURED (I observed it), VERIFIED-AT-SOURCE (read on vendor page today), CLAIMED (third-party page / search snippet), ASSUMED (my prior, not checked).
FX: EUR figures assume 1 USD = 0.925 EUR (ASSUMED; 2026-09 rate not checked). Prices are ex-VAT unless the vendor says otherwise (ASSUMED).

## Framing
- Goal A (identity through video) is served locally: mesh -> per-frame depth via mesh_control.py is MEASURED WORKING (FACTS). No service below addresses goal A directly; a 3D-gen service only feeds goal B, whose mesh then feeds goal A.
- Goal B (faithful 3D from a 2D canon pair) is where multi-view input matters. Local null model = TRELLIS.2 single-front result (radial-extent 49% further from anchor than a sphere; tail absent) and the "do-nothing" sphere.
- Photogrammetry / splat services are out by construction: the creature-sheet cells contradict each other (front h/w 0.82 vs back 1.29, FACTS) and geom/mvconsist.py already measures "is this one rigid object" — generated sheets fail it. Only the 2 anchors are reference; no reconstructor can invent what they don't show.

## Multi-view 3D generation

### Meshy (Meshy LLC, California)
- Pricing VERIFIED-AT-SOURCE https://www.meshy.ai/pricing : Free $0 (100 cr/mo); Pro $20/mo; Premium $40; Ultra $100; Studio $70. API from Pro. "If you are on a premium plan, you own all assets you create with Meshy." Free plan: CC BY 4.0, must credit Meshy.
- Terms VERIFIED-AT-SOURCE https://www.meshy.ai/terms-of-use (last updated March 7, 2026): Free: "Provider owns all right, title, and interest, including all intellectual property rights, in and to the AI Customer Output" (licensed back CC BY 4.0). Paid: private ownership retained. Governing law California; no territory clause. "Meshy may use Customer Inputs and Customer Outputs from non Enterprise Customers ... to train, validate, test, or improve Services unless otherwise agreed to in the Order." Ban: "use generated digital assets to train, develop, or improve AI models that are competitive with Meshy" (our LoRA training on Meshy renders is NOT competitive with Meshy -> fine, ASSUMED reading).
- Multi-image: Meshy 6 (GA 18 Jan 2026) takes 1-8 reference images; a full gen = 20 credits; rigging/animation 0 credits; Smart Remesh retopo — all CLAIMED (third-party pages, not read on meshy.ai).
- EUR: Pro ~18.5/mo; 3 months ~55; 6 months ~111. Within budget.
- Risks: vendor trains on our canon anchors + outputs (IP leak of channel characters, not a licence blocker). Multi-image does not label views (front/side) — the model decides; CLAIMED.

### Tripo (VAST AI Research, Beijing)
- Site bot-blocked: MEASURED HTTP 403 on /terms, /terms-of-service and the blog; platform docs render empty. ToS content UNVERIFIED. Search snippet: ToS last updated July 11, 2025; Free plan public models CC BY 4.0; paid users have "broad rights to use, modify, distribute, license, and monetize their inputs and outputs" (CLAIMED, quoted via search).
- Tencent affiliation: none found; VAST is a separate Beijing company (ASSUMED). NOTE the FACTS caveat: their OPEN-SOURCE TripoSG carries a Tencent-EU-excluded file; the hosted service's territory clause is UNVERIFIED — a human must read https://www.tripo3d.ai/terms in a browser before paying.
- Pricing CLAIMED: Free 200 cr/mo; Pro $19.90/mo (3,000 cr, ~120 models); 1 credit = $0.01; API is separate pay-as-you-go via platform.tripo3d.ai.
- Multi-view: "text, image and multiview" input CLAIMED; API multiview_to_model takes front + optional left/back/right (ASSUMED from prior knowledge; SDK README 404'd).
- EUR: ~18.4/mo.

### Hyper3D Rodin (Deemos Corporation, Delaware)
- Terms VERIFIED-AT-SOURCE https://hyper3d.ai/legal/terms : Delaware law; Rodin Output: "We will not limit your use of such Output, subject to any restrictions set forth in these Agreements, the Applicable Laws and any third-party terms and conditions"; ChatAvatar free = personal only; no explicit territory clause; ban on using the Services to train competing AI; no date shown.
- Pricing VERIFIED-AT-SOURCE https://hyper3d.ai/pricing : Free $0 ("generate for free before confirmation"); Creator $30/mo ($24/mo yearly); Business $120/mo. "Multi-image to 3D" = Creator+ feature. API = Business+ ONLY. FAQ: "Paid plans include broader export and usage rights." 7-day trial link present. Free-tier outputs personal-use (CLAIMED via search).
- Multi-view: Gen-2 "concat" mode accepts multi-view images of one object in any order (CLAIMED, developer.hyper3d.ai snippet).
- EUR: Creator ~27.8/mo monthly; 3 months ~83; 5 months ~139. No API within budget (web UI only).

### Rejected 3D-gen: Kaedim (Starter $150/mo, Indie $300/mo CLAIMED; over budget). Luma Genie (ToS VERIFIED 2026-05-14: "The Services are intended for visitors located within the United States"; Genie absent from ToS; discontinued CLAIMED). CSM (MEASURED: DNS ENOTFOUND for csm.ai and www.csm.ai; acquired by Google Jan 2026 CLAIMED). Sloyd (parametric props, not identity; ASSUMED). Krea 3D (single-image; ASSUMED). Adobe Substance 3D Sampler (single-image image-to-3D; CC subscription; ASSUMED).

## Motion / capture

### DeepMotion Animate 3D — pricing page partially VERIFIED https://www.deepmotion.com/pricing-animate3d : "To have licensed animation, you must have a premium subscription plan"; 1 credit = 1 s (+0.5 for face, +0.5 for hands); export FBX/BVH/MP4/GLB; API contact-only. Freemium non-commercial 60 s/mo, Freelancer $48/mo with commercial licence (CLAIMED; third-party numbers disagree with each other). EUR ~44/mo.
- Role: driver clip -> BVH pose track -> retarget onto anny for anny_animate per-frame depth. Null model: SAM 3D Body per frame (local, 1.2 s/img, per-joint rotations) + temporal smoothing. Would only "beat what we have" if jitter/foot-slide are measurably lower on the same clip.

### Rokoko Vision — product page VERIFIED https://www.rokoko.com/products/vision : Starter free: record/export FBX, 30 s/month Vision AI video processing; Basic $10/mo annual / $12 monthly. Terms page MEASURED 403 — commercial use on free tier UNVERIFIED. No API. EUR ~11/mo.
- Same role/null as DeepMotion. 30 s/month is enough for a measurement, not for production.

### Move One (Move AI) — docs page 404 (MEASURED). CLAIMED: s1 single-camera $0.012/s, min $0.10/job; Move One $15/mo = 2,250 credits ~375 s. iPhone app capture (ASSUMED). Output terms UNVERIFIED (only the Move Pro desktop EULA surfaced). EUR ~14/mo.

### Cascadeur — CLAIMED via search of cascadeur.com/plans + EULA quote: Free = no commercial use; Indie ~$8/mo, EULA: "If you registered for an 'Indie' Licence Type, your aggregate gross revenue or funding ... in the twelve months ending on the date when you download the Software ... must be less than US $100,000.00"; Pro $33/mo no cap; annual Indie/Pro converts to perpetual after 1 year. Linux build exists (ASSUMED). Role: hand-keyed pose tracks with physics for shots without a driver clip. Revenue-cap compliance is the operator's call.

### Rejected motion/capture: Anything World Animate Anything (from $50/mo CLAIMED, terms unverified; Blender rigs the pufferball for free). RealityScan 2.x (free under $1M USD revenue VERIFIED on realityscan.com/license snippet; Windows-only ASSUMED; photogrammetry of generated views fails by the FACTS measurement). Polycam / Kiri Engine (real-object capture; subjects are 2D canon; ASSUMED). Postshot (Indie EUR 17/mo, free is non-commercial+watermark CLAIMED; needs real multi-view; Windows ASSUMED).

### Rejected motion-transfer APIs (closed models; our Wan LoRAs cannot be loaded; identity comes from one reference image; post-hoc wan_face_restore already exists locally): Runway Act-Two API $0.0525/s, commercial on paid plans (CLAIMED). Kling Motion Control $0.07-0.14/s via resellers (CLAIMED); Kuaishou (China) — EU terms UNVERIFIED. Viggle (not searched; ASSUMED closed). A free-credit null comparison is cheap if the orchestrator wants one, but it cannot become the pipeline.

## Measurement protocol (recommended before spending anything)
Subjects: pufferball (operator front + side anchors), cornelis (front anchor; side if present).
Arms per service (free tiers: Meshy 100 cr = 5 gens; Tripo 200 cr; Rodin generate-before-confirm / 7-day trial):
 1. front-only  2. front+side  (the delta isolates the multi-view contribution from raw model quality)
Controls: TRELLIS.2 single-front GLB (existing), unit sphere (do-nothing null), a rendered turntable of the returned GLB through geom/mvconsist.py (must pass — it is a control that the scorer works, not a test of the service).
Scores: (a) radial-extent profile vs anchor silhouette, reported as distance-from-anchor relative to the sphere null (TRELLIS.2 = +49%); (b) DINOv2 view-rank: render the GLB with geom/mv_render.py at the 16 sheet angles, embed with creature_identity.py (DINOv2 CLS cosine), rank of the true-angle render vs anchor — chance 8.5/16, klein-depth control got 2/16; (c) binary geometry checks the anchors demand: tail present, mouth present; (d) for cornelis, face RMS against the fitted GNM head in mm (existing 4.1-5.1 mm baseline).
Ledger: PASS / FAIL / UNMEASURED / CONTROL-FAILED per (service, subject, arm, score).
Decision rule: buy Meshy Pro (or Rodin Creator if Meshy fails and Rodin passes) only if front+side beats TRELLIS.2 on (a) AND (b) on the pufferball and adds the tail; otherwise buy nothing — the FACTS "buy nothing" verdict stands because the anchors disagree about the mouth.
Never use free-tier outputs in production (Meshy free: Meshy owns IP; Rodin free: personal use).
