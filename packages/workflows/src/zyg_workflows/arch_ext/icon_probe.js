// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/* icon_probe — the worked example of the ICON seam (2026-09-07).
   Wires Select ▸ Previous (s_last): go back to the selection as it was before
   the last change; press again to come forward. One tool, assist-pressable,
   no prompt. Everything it touches is a studio global (AR, arSelect, arToast);
   nothing in inspection.html was edited to make this icon real. */
AR_EXT.ready.push(function(){
  /* selection history: wrap the studio's own arSelect. Function declarations
     are writable globals, so every later call in the page reaches this one. */
  var base = arSelect;
  AR._selHist = AR._selHist || [];
  arSelect = function(ids, add){
    var before = AR.sel.slice();
    base(ids, add);
    if(JSON.stringify(before) !== JSON.stringify(AR.sel)){
      AR._selHist.push(before);
      if(AR._selHist.length > 20) AR._selHist.shift();
    }
  };
});
AR_EXT.tools.s_last = {
  assist: 1,
  tip: 'Previous selection — back to what was selected before the last change; press again to come forward',
  act: function(opt){
    var h = AR._selHist || [];
    if(!h.length){ arToast('No previous selection to go back to.'); return; }
    var prev = h.pop();
    arSelect(prev);            /* the wrapper pushes the current selection, so a second press returns */
    arToast('Selection restored: '+prev.length+' object'+(prev.length===1?'':'s')+'.');
  }
};
