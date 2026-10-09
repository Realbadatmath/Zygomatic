// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

            (function(){
              function _loadDisk(){
                fetch('/api/disk_usage').then(r=>r.json()).then(d=>{
                  ['home','root'].forEach(function(k){
                    var info = d[k]; if(!info||info.error) return;
                    var pct = info.used_pct;
                    var color = pct > 90 ? 'linear-gradient(90deg,#ef4444,#f97316)'
                              : pct > 75 ? 'linear-gradient(90deg,#f59e0b,#eab308)'
                              : 'linear-gradient(90deg,#3b82f6,#06b6d4)';
                    var fill = document.getElementById('am-disk-'+k+'-fill');
                    var txt  = document.getElementById('am-disk-'+k+'-txt');
                    if(fill){ fill.style.width = pct+'%'; fill.style.background = color; }
                    if(txt) txt.textContent = info.free_gb+' GB free / '+info.total_gb+' GB  ('+pct+'% used)';
                  });
                }).catch(function(){});
              }
              _loadDisk();
              document.querySelector('[data-tab="asset_manager"]') &&
                document.querySelector('[data-tab="asset_manager"]').addEventListener('click', _loadDisk);
            })();
