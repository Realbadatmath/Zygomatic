// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* v3probe — the SEAM's own test fixture, not a drawing tool.

   One kind, `v3probe`: a 2 m x 2 m quad in plan whose far edge is lifted by the
   NUMBER OF `box` RECORDS IN THE DRAWING, with its four vertices coloured red,
   green, blue and white. It exists to prove two things the v3 sculpted ground
   depends on, in all three engines at once:

     · kit.records — a geometry function can see the OTHER records. Without it a
       `ground` record could never be the sum of the drawing's sculpts.
     · part.vcolors — a part may carry one colour per vertex, so ONE mesh can be
       grass, rock, sand and snow at the same time.

   The same arithmetic lives in arch_blender_ext/v3probe.py (Blender) and
   arch_assistant_ext/v3probe.py (the assistant's HEIGHTS). If the three ever
   disagree, tests_arch_ext/test_v3_seam.py says so.

   Local frame: the record's x/z is the CENTRE in plan, the ground is y=0, up is
   +Y. Vertex order is the same in every engine: (-1,0,-1), (1,0,-1), (1,h,1),
   (-1,h,1). */
(function(){
  function boxCount(k){
    var recs = (k && k.records) || [], n = 0;
    for(var i=0;i<recs.length;i++) if(recs[i] && recs[i].kind==='box') n++;
    return n;
  }
  AR_EXT.geom.v3probe = function(p, k){
    var h = boxCount(k);
    var pos = [-1, 0, -1,   1, 0, -1,   1, h, 1,   -1, h, 1];
    var col = [1, 0, 0,     0, 1, 0,    0, 0, 1,    1, 1, 1];
    var g = new k.THREE.BufferGeometry();
    g.setAttribute('position', new k.THREE.Float32BufferAttribute(pos, 3));
    g.setIndex([0, 1, 2, 0, 2, 3]);
    g.computeVertexNormals();
    return [{g: g, vcolors: new Float32Array(col)}];
  };
  AR_EXT.label.v3probe = 'v3 seam probe';
})();
