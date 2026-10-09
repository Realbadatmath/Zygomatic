// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* char_0_strand_width.js — a screen-space WIDTH FLOOR for ribbon strands.
   2026-09-23.

   THE DEFECT, measured on this GPU (4x MSAA, WebGL2, three r147).
   Hair, brows and lashes are all flat ribbons a fraction of a millimetre wide,
   and they are shipped OPAQUE. At the Character Studio's default framing the
   drawing buffer is 475x635 and a ribbon covers well under one pixel:

       hair ribbon  0.37 px      brow strand  0.17 px      lash  0.10 px

   Two things follow, and both were measured directly rather than argued:

     · DROPOUT. A 0.10 px opaque strip renders NOTHING at 8 of 16 sub-pixel
       offsets. That is the lash crust and the scratchy brow: each strand is
       either a hard black sample or absent, with nothing in between.

     · SATURATION, which is the worse one. SIXTEEN overlapping 0.25 px opaque
       strands inside one BufferGeometry resolve to ink 64 — EXACTLY the same
       as a single strand. Coverage cannot accumulate, because every strand
       lands on the same MSAA sample and opaque geometry just overwrites it.
       Fifteen thousand hair ribbons therefore paint no more hair than a few
       hundred do. That is "the hair looks sparse and flaky".

   THE CURE. Expand each ribbon in the VERTEX shader so it is never narrower
   than MIN_PX on screen, and scale its alpha by (true width / drawn width) so
   the light it removes is unchanged. A strand thinner than a pixel stops being
   a coin-flip and becomes a faint wide one, which is what it physically is.
   Measured with plain alpha blending and depthWrite off, 1/2/4/8/16 overlapping
   floored strands resolve to 64/112/175/230/253 — within 1/255 of correct at
   every count, and the same whether the index order is near-first or far-first.

   WHY NOT alphaToCoverage. It is inert here and the reason is in r147 itself:
   program parameters set `opaque = (transparent === false && blending ===
   NormalBlending)`, and `output_fragment` is `#ifdef OPAQUE diffuseColor.a =
   1.0; #endif`. Alpha is clamped to 1 one line before gl_FragColor, so A2C
   sees nothing. Forced on (transparent + NoBlending) it is still wrong: the
   hardware picks the same sample mask for the same alpha, so A2C NEVER
   accumulates — 1, 2, 4, 8 and 16 strands all measured ink 64.
   And alphaTest is the binary behaviour that IS the defect.

   WHY NOT just supersample. The pixel ratio was raised to 2x physical at the
   same time (inspection.html cs3dEnsure) and it helps every defect at once,
   but it only buys one doubling: a 0.37 px ribbon becomes 0.74 px, still under
   a pixel, and saturation is unaffected by resolution.

   USAGE
       CSSTRAND.patch(material, {minPx: 1.3})   before the material is used
       CSSTRAND.install(scene)                  once per scene (Compare has its own)
   and the geometry must carry `csEdge`: vec4(expansion axis in object space,
   signed offset magnitude in metres). CSSTRAND.edge() builds it.

   FAIL CLOSED. A geometry with no csEdge gets (0,0,0,0); the shader detects
   that and leaves the vertex exactly where it was with coverage 1, so the mesh
   renders as it does today. If three's chunks ever stop containing the anchors
   we splice on, the patch is skipped whole with a console.warn and the material
   is untouched. Never a half-patched shader.

   Sorted FIRST in the studio_ext bundle on purpose — kanban_server.py globs
   studio_ext/*.js and concatenates in sorted order, and '0' sorts before every
   letter, so CSSTRAND exists before char_hair.js / char_lashes.js reach for it. */
(function () {
  'use strict';
  if (typeof THREE === 'undefined') return;

  /* A ribbon narrower than this on screen is widened and faded. 1.3 px rather
     than 1.0: at exactly one pixel a strand still straddles two pixel centres
     about half the time and keeps a little of the flicker it is here to cure. */
  var MIN_PX = 1.3;

  /* set per frame from the renderer: (drawingBufferHeight/2) / tan(fov/2).
     World size of one pixel at view depth z is then |z| / uPxScale. */
  var shared = { uPxScale: { value: 600.0 }, uMinPx: { value: MIN_PX } };

  var VERT_PARS = [
    'attribute vec4 csEdge;',     /* xyz = expansion axis (object space), w = signed offset in metres */
    'varying float vCsCov;',
    'uniform float uPxScale;',
    'uniform float uMinPx;'
  ].join('\n');

  /* Runs right after <begin_vertex>, which defines `transformed`. The spine is
     the vertex with its own edge offset taken back off, so both edges of a
     ribbon agree on where the centre line is and the ribbon widens about it
     instead of sliding sideways. */
  var VERT_BODY = [
    '#include <begin_vertex>',
    'vCsCov = 1.0;',
    '#ifdef USE_CSEDGE',
    '{',
    '  float csHalf = abs( csEdge.w );',
    '  if ( csHalf > 1e-7 ) {',
    '    vec3 csAxis = csEdge.xyz;',
    '    vec3 csSpine = transformed - csAxis * csEdge.w;',
    '    float csZ = abs( ( modelViewMatrix * vec4( csSpine, 1.0 ) ).z );',
    '    float csPx = csZ / max( uPxScale, 1e-4 );',   /* metres per pixel at this depth */
    '    float csWant = 0.5 * uMinPx * csPx;',          /* half of the floor, in metres */
    '    if ( csWant > csHalf ) {',
    '      transformed = csSpine + csAxis * sign( csEdge.w ) * csWant;',
    '      vCsCov = csHalf / csWant;',
    '    }',
    '  }',
    '}',
    '#endif'
  ].join('\n');

  var FRAG_PARS = 'varying float vCsCov;';
  /* after <alphamap_fragment>, before the OPAQUE clamp and tone mapping */
  var FRAG_BODY = [
    '#include <alphamap_fragment>',
    'diffuseColor.a *= clamp( vCsCov, 0.0, 1.0 );'
  ].join('\n');

  function patch(mat, opts) {
    if (!mat || mat.userData.csStrand) return mat;
    opts = opts || {};
    var minPx = (opts.minPx === undefined) ? MIN_PX : opts.minPx;

    /* The floor only conserves light if the ribbon can actually be faded, and
       r147 clamps alpha to 1 for an opaque material. Blending is what lets
       overlapping strands ACCUMULATE; depthWrite off is what makes the result
       independent of the order the strands happen to sit in the index buffer
       (measured: with depthWrite on and near-first order the 16-strand case
       collapses back to a single strand's ink). */
    mat.transparent = true;
    mat.blending = THREE.NormalBlending;
    mat.depthWrite = false;
    mat.depthTest = true;
    mat.alphaTest = 0;
    mat.alphaToCoverage = false;
    mat.premultipliedAlpha = false;

    var prev = mat.onBeforeCompile;
    mat.onBeforeCompile = function (shader, renderer) {
      /* compose, never clobber: char_hair.js and char_lashes.js already patch
         <normal_fragment_begin> for the double-sided ribbon normal flip */
      if (typeof prev === 'function') {
        try { prev.call(this, shader, renderer); } catch (e) { console.warn('CSSTRAND prev patch', e); }
      }
      if (shader.vertexShader.indexOf('#include <begin_vertex>') < 0 ||
          shader.fragmentShader.indexOf('#include <alphamap_fragment>') < 0) {
        console.warn('CSSTRAND: three chunks moved, width floor skipped');
        return;                                  /* fail closed, material untouched */
      }
      shader.vertexShader = VERT_PARS + '\n' +
        shader.vertexShader.replace('#include <begin_vertex>', VERT_BODY);
      shader.fragmentShader = FRAG_PARS + '\n' +
        shader.fragmentShader.replace('#include <alphamap_fragment>', FRAG_BODY);
      shader.uniforms.uPxScale = shared.uPxScale;
      shader.uniforms.uMinPx = { value: minPx };
      shader.defines = shader.defines || {};
    };
    /* one program per floor value; everything else that varies is a uniform */
    var key = 'cs-strand-floor-' + minPx + '-' + (mat.userData.csKey || '');
    var prevKey = mat.customProgramCacheKey;
    mat.customProgramCacheKey = function () {
      return key + '|' + (typeof prevKey === 'function' ? prevKey.call(this) : '');
    };
    mat.defines = mat.defines || {};
    mat.defines.USE_CSEDGE = '';
    mat.userData.csStrand = { minPx: minPx };
    mat.needsUpdate = true;
    return mat;
  }

  /* (axis, signed offset) -> the four floats csEdge wants, for one ribbon edge */
  function edge(out, ax, ay, az, signedOffset) {
    out.push(ax, ay, az, signedOffset);
    return out;
  }

  /* Per frame, from whichever renderer is drawing. Chained onto the scene's
     onBeforeRender the way char_eyes.js installFade does — and it must be
     installed on Compare's second scene too (char_file_compare.js builds its
     own THREE.Scene), which is why this takes a scene rather than assuming one. */
  function install(scene) {
    if (!scene || !scene.isScene || scene.userData.csStrandTick) return;
    scene.userData.csStrandTick = true;
    var prev = scene.onBeforeRender;
    scene.onBeforeRender = function (renderer, sc, camera) {
      if (typeof prev === 'function') { try { prev.apply(this, arguments); } catch (e) {} }
      if (!camera || !camera.isPerspectiveCamera || !renderer) return;
      var h = 0;
      try { h = renderer.getDrawingBufferSize(new THREE.Vector2()).y; } catch (e) { h = 0; }
      if (!h) h = renderer.domElement.height || 600;
      shared.uPxScale.value = (0.5 * h) / Math.tan(camera.fov * Math.PI / 360);
    };
  }

  window.CSSTRAND = {
    patch: patch, install: install, edge: edge,
    MIN_PX: MIN_PX, uniforms: shared
  };
})();
