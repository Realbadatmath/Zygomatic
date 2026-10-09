// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * Dashboard tab: Users
 * Three columns (Users, Permissions, Login Credentials), role rows, add-user form, avatar upload.
 */
(function () {
    'use strict';

    var ROLES = [
        { id: 'admins', label: 'Admins', permissions: 'Full control', credentials: 'ID + Password' },
        { id: 'operators', label: 'Operators', permissions: 'Create Tasks, Create Schedules.', credentials: 'ID + Password' },
        { id: 'ai_operators', label: 'Ai Operators', permissions: 'Create Tasks, Create Schedules.', credentials: 'ID + Password' },
        { id: 'spectators', label: 'Spectators', permissions: 'View only', credentials: 'None' }
    ];

    function byId(id) { return document.getElementById(id); }

    function render(container) {
        if (!container) return;
        var loginMethodIds = ['id_password_sms', 'id_password_phone', 'microsoft_code', 'retinal_scan', 'finger_scan'];
        var loginMethodLabels = ['ID/Password + Sms', 'ID/Password + Phone Call', 'Microsoft Code', 'Retinal Scan', 'Finger Scan'];
        container.innerHTML = [
            '<div class="dashboard-users-layout" id="dashboard-users-main-layout">',
            '  <button type="button" class="btn dashboard-btn" id="dashboard-users-add-login-method-btn">Add Login Method</button>',
            '  <div class="dashboard-users-three-col">',
            '    <div class="dashboard-users-col"><strong>Users</strong></div>',
            '    <div class="dashboard-users-col"><strong>Permissions</strong></div>',
            '    <div class="dashboard-users-col"><strong>Login Credentials</strong></div>',
            '  </div>',
            ROLES.map(function (r) {
                return '<div class="dashboard-users-row" data-role="' + r.id + '">' +
                    '<div class="dashboard-users-col"><span class="dashboard-users-role-label">' + r.label + '</span><button type="button" class="dashboard-btn-edit">Edit</button></div>' +
                    '<div class="dashboard-users-col">' + r.permissions + '</div>' +
                    '<div class="dashboard-users-col">' + r.credentials + '</div>' +
                    '</div>';
            }).join(''),
            '</div>',
            '<div id="dashboard-users-login-method-view" class="dashboard-users-subview" style="display:none;">',
            '  <button type="button" class="btn dashboard-btn btn-secondary dashboard-users-back-btn">← Back</button>',
            '  <h4 class="dashboard-settings-panel-title">Add Login Method</h4>',
            '  <ul class="dashboard-users-login-method-options">' +
            loginMethodIds.map(function (id, i) {
                return '<li><label><input type="checkbox" class="dashboard-login-method-cb" data-method="' + id + '"> ' + loginMethodLabels[i] + '</label></li>';
            }).join('') + '</ul>',
            '  <button type="button" class="btn dashboard-btn" id="dashboard-users-login-method-apply">Apply</button>',
            '</div>',
            '<div id="dashboard-users-detail" class="dashboard-users-detail" style="display:none;">',
            '  <button type="button" class="dashboard-users-back">← Back to list</button>',
            '  <div id="dashboard-users-detail-content"></div>',
            '  <div id="dashboard-users-profile" class="dashboard-users-subview" style="display:none;">',
            '    <button type="button" class="btn dashboard-btn btn-secondary dashboard-users-profile-back">← Back</button>',
            '    <h4 id="dashboard-users-profile-title">User profile</h4>',
            '    <div class="form-group"><label>Name</label><input type="text" id="up-name" class="dashboard-input" /></div>',
            '    <div class="form-group"><label>E-mail</label><input type="email" id="up-email" class="dashboard-input" /></div>',
            '    <div id="up-single-password-group" class="form-group">',
            '      <div class="form-group"><label>Current Password</label><div class="dashboard-pw-wrap"><input type="password" id="up-current-password" readonly class="dashboard-input" placeholder="••••••••" /><button type="button" class="dashboard-eye-btn" id="up-current-password-eye" aria-label="Reveal password"><svg class="dashboard-eye-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg></button></div></div>',
            '      <div class="form-group"><label>Password (leave blank to keep)</label><div class="dashboard-pw-wrap"><input type="password" id="up-password" class="dashboard-input" /><button type="button" class="dashboard-eye-btn" id="up-password-eye" aria-label="Reveal password"><svg class="dashboard-eye-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg></button></div></div>',
            '      <div class="form-group"><label>Re-enter Password</label><div class="dashboard-pw-wrap"><input type="password" id="up-password2" class="dashboard-input" /><button type="button" class="dashboard-eye-btn" id="up-password2-eye" aria-label="Reveal password"><svg class="dashboard-eye-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg></button></div></div>',
            '    </div>',
            '    <div id="up-multi-passwords-group" class="form-group" style="display:none;">',
            '      <label>Passwords (any of these can be used to log in)</label>',
            '      <p class="dashboard-help-text" style="margin:4px 0 8px 0;font-size:12px;color:#666;">Add multiple passwords so you can still log in if you forget one.</p>',
            '      <div id="up-passwords-list"></div>',
            '      <button type="button" class="btn dashboard-btn btn-secondary" id="up-add-password" style="margin-top:8px;">Add another password</button>',
            '    </div>',
            '    <div class="form-group"><label>Login method</label><select id="up-login-method" class="dashboard-input"><option value="id_password">ID/Password</option><option value="id_password_sms">ID/Password + Sms</option><option value="id_password_phone">ID/Password + Phone Call</option><option value="microsoft_code">Microsoft Code</option><option value="retinal_scan">Retinal Scan</option><option value="finger_scan">Finger Scan</option></select></div>',
            '    <div class="form-group"><button type="button" class="btn dashboard-btn" id="up-change-picture">Add / Change picture</button></div>',
            '    <button type="button" class="btn dashboard-btn" id="up-save">Save</button>',
            '  </div>',
            '</div>'
        ].join('');

        var addLoginBtn = container.querySelector('#dashboard-users-add-login-method-btn');
        if (addLoginBtn) addLoginBtn.addEventListener('click', function () {
            byId('dashboard-users-main-layout').style.display = 'none';
            var detail = byId('dashboard-users-detail');
            if (detail) detail.style.display = 'none';
            var loginView = byId('dashboard-users-login-method-view');
            if (loginView) {
                loginView.style.display = 'block';
                loginView.querySelectorAll('.dashboard-login-method-cb').forEach(function (cb) { cb.checked = false; });
            }
        });
        var loginBackBtn = container.querySelector('#dashboard-users-login-method-view .dashboard-users-back-btn');
        if (loginBackBtn) loginBackBtn.addEventListener('click', function () {
            var loginView = byId('dashboard-users-login-method-view');
            if (loginView) loginView.style.display = 'none';
            byId('dashboard-users-main-layout').style.display = '';
        });
        var loginApplyBtn = container.querySelector('#dashboard-users-login-method-apply');
        if (loginApplyBtn) loginApplyBtn.addEventListener('click', function () {
            var checked = [];
            container.querySelectorAll('.dashboard-login-method-cb:checked').forEach(function (cb) {
                checked.push(cb.getAttribute('data-method'));
            });
            if (checked.length) {
                try { localStorage.setItem('dashboard_login_methods', JSON.stringify(checked)); } catch (e) {}
            }
            byId('dashboard-users-login-method-view').style.display = 'none';
            byId('dashboard-users-main-layout').style.display = '';
        });

        container.querySelectorAll('.dashboard-users-row').forEach(function (row) {
            row.addEventListener('click', function (e) {
                if (e.target.classList.contains('dashboard-btn-edit')) return;
                var role = this.getAttribute('data-role');
                showRoleDetail(container, role);
            });
            row.querySelector('.dashboard-btn-edit').addEventListener('click', function (e) {
                e.stopPropagation();
                showRoleDetail(container, row.getAttribute('data-role'));
            });
        });

        var backBtn = container.querySelector('.dashboard-users-back');
        if (backBtn) backBtn.addEventListener('click', function () {
            container.querySelector('.dashboard-users-layout').style.display = '';
            byId('dashboard-users-detail').style.display = 'none';
        });
    }

    function showRoleDetail(container, roleId) {
        container.querySelector('.dashboard-users-layout').style.display = 'none';
        var detail = byId('dashboard-users-detail');
        var content = byId('dashboard-users-detail-content');
        if (!detail || !content) return;
        detail.style.display = 'block';
        content.innerHTML = '';

        fetch('/api/dashboard/users').then(function (r) { return r.json(); }).then(function (data) {
            var users = data[roleId] || [];
            if (!window._dashboardUsersCache) window._dashboardUsersCache = {};
            window._dashboardUsersCache[roleId] = users;
            var roleLabel = ROLES.find(function (r) { return r.id === roleId; });
            roleLabel = roleLabel ? roleLabel.label : roleId;

            var html = '<h3>' + roleLabel + '</h3>';
            html += '<div class="dashboard-users-avatars">';
            html += '<div class="dashboard-user-avatar-add" title="Add user">';
            html += '<div class="dashboard-user-avatar-ring dashboard-user-avatar-empty"><span class="dashboard-user-avatar-plus">+</span></div>';
            html += '<span class="dashboard-user-avatar-name">Add user</span></div>';

            users.forEach(function (u) {
                var avatarUrl = u.avatar_url || '';
                var name = u.name || u.id || 'Unknown';
                html += '<div class="dashboard-user-avatar-block" data-user-id="' + (u.id || '') + '" title="Click to edit user">';
                html += '<div class="dashboard-user-avatar-ring" style="' + (avatarUrl ? 'background-image:url(' + avatarUrl + ');background-size:cover;' : '') + '"></div>';
                html += '<span class="dashboard-user-avatar-name">' + name + '</span>';
                html += '</div>';
            });
            html += '</div>';
            content.innerHTML = html;

            content.querySelector('.dashboard-user-avatar-add').addEventListener('click', function () {
                openAddUserForm(roleId, content, users);
            });
            content.querySelectorAll('.dashboard-user-avatar-block').forEach(function (block) {
                var userId = block.getAttribute('data-user-id');
                var user = users.find(function (u) { return (u.id || '') === userId; });
                if (!user) return;
                block.addEventListener('click', function () {
                    showUserProfile(container, roleId, user, users);
                });
            });
        }).catch(function () {
            content.innerHTML = '<p>Failed to load users.</p>';
        });
    }

    function togglePasswordVisibility(inputId, isCurrentPassword) {
        var input = byId(inputId);
        if (!input) return;
        if (isCurrentPassword) {
            var revealed = input.getAttribute('data-revealed') === '1';
            var real = input.getAttribute('data-current-password') || '';
            if (revealed) {
                input.value = real ? '••••••••' : '';
                input.setAttribute('data-revealed', '0');
                input.type = 'password';
            } else {
                input.value = real || '(not stored)';
                input.setAttribute('data-revealed', '1');
                input.type = 'text';
            }
        } else {
            input.type = input.type === 'password' ? 'text' : 'password';
        }
    }

    function getPasswordsArray(user) {
        if (user.passwords && Array.isArray(user.passwords)) return user.passwords.slice();
        if (user.password != null && user.password !== '') return [String(user.password)];
        return [];
    }

    function buildPasswordRow(value, index, listEl, roleId) {
        var wrap = document.createElement('div');
        wrap.className = 'dashboard-pw-wrap dashboard-pw-row';
        wrap.style.display = 'flex';
        wrap.style.alignItems = 'center';
        wrap.style.gap = '8px';
        wrap.style.marginBottom = '8px';
        var input = document.createElement('input');
        input.type = 'password';
        input.className = 'dashboard-input';
        input.placeholder = '••••••••';
        input.setAttribute('data-pw-index', index);
        if (value) input.setAttribute('data-stored-value', value);
        input.value = value ? '••••••••' : '';
        var eye = document.createElement('button');
        eye.type = 'button';
        eye.className = 'dashboard-eye-btn';
        eye.setAttribute('aria-label', 'Reveal password');
        eye.innerHTML = '<svg class="dashboard-eye-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';
        eye.onclick = function () {
            var stored = input.getAttribute('data-stored-value');
            if (stored) {
                if (input.type === 'password') { input.type = 'text'; input.value = stored; } else { input.type = 'password'; input.value = '••••••••'; }
            } else { input.type = input.type === 'password' ? 'text' : 'password'; }
        };
        var removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'btn dashboard-btn btn-secondary';
        removeBtn.textContent = 'Remove';
        removeBtn.style.flexShrink = '0';
        removeBtn.onclick = function () { wrap.remove(); };
        wrap.appendChild(input);
        wrap.appendChild(eye);
        wrap.appendChild(removeBtn);
        listEl.appendChild(wrap);
    }

    function showUserProfile(container, roleId, user, users) {
        var content = byId('dashboard-users-detail-content');
        var profile = byId('dashboard-users-profile');
        if (!content || !profile) return;
        content.style.display = 'none';
        profile.style.display = 'block';
        byId('dashboard-users-profile-title').textContent = user.name || user.id || 'User profile';
        byId('up-name').value = user.name || '';
        byId('up-email').value = user.email || '';
        byId('up-password').value = '';
        byId('up-password2').value = '';
        byId('up-login-method').value = user.login_method || 'id_password';

        var singleGroup = byId('up-single-password-group');
        var multiGroup = byId('up-multi-passwords-group');
        var passwordsList = byId('up-passwords-list');
        if (roleId === 'admins') {
            if (singleGroup) singleGroup.style.display = 'none';
            if (multiGroup) multiGroup.style.display = 'block';
            if (passwordsList) {
                passwordsList.innerHTML = '';
                var pwArray = getPasswordsArray(user);
                if (pwArray.length === 0) pwArray.push('');
                pwArray.forEach(function (val, i) { buildPasswordRow(val, i, passwordsList, roleId); });
            }
            var addPwBtn = byId('up-add-password');
            if (addPwBtn) {
                addPwBtn.onclick = function () {
                    if (passwordsList) buildPasswordRow('', passwordsList.children.length, passwordsList, roleId);
                };
            }
        } else {
            if (singleGroup) singleGroup.style.display = 'block';
            if (multiGroup) multiGroup.style.display = 'none';
        }

        var currentPwInput = byId('up-current-password');
        if (currentPwInput) {
            var currentPw = (user.password != null && user.password !== '') ? String(user.password) : '';
            currentPwInput.setAttribute('data-current-password', currentPw);
            currentPwInput.value = currentPw ? '••••••••' : '';
            currentPwInput.type = 'password';
            currentPwInput.setAttribute('data-revealed', '0');
        }
        var currentEye = byId('up-current-password-eye');
        if (currentEye) {
            currentEye.onclick = function () { togglePasswordVisibility('up-current-password', true); };
        }
        var pwEye = byId('up-password-eye');
        if (pwEye) {
            pwEye.onclick = function () { togglePasswordVisibility('up-password', false); };
        }
        var pw2Eye = byId('up-password2-eye');
        if (pw2Eye) {
            pw2Eye.onclick = function () { togglePasswordVisibility('up-password2', false); };
        }

        profile.querySelector('.dashboard-users-profile-back').onclick = function () {
            profile.style.display = 'none';
            content.style.display = '';
            showRoleDetail(container, roleId);
        };
        byId('up-change-picture').onclick = function () {
            var block = content.querySelector('.dashboard-user-avatar-block[data-user-id="' + (user.id || '') + '"]');
            openAvatarUpload(user.id || '', roleId, block, container);
        };
        byId('up-save').onclick = function () {
            var name = byId('up-name').value.trim();
            var email = byId('up-email').value.trim();
            if (!name) { alert('Name is required.'); return; }
            user.name = name;
            user.email = email || undefined;
            user.login_method = byId('up-login-method').value;

            if (roleId === 'admins') {
                var collected = [];
                if (passwordsList) {
                    var rows = passwordsList.querySelectorAll('.dashboard-pw-row input');
                    for (var i = 0; i < rows.length; i++) {
                        var inp = rows[i];
                        var stored = inp.getAttribute('data-stored-value');
                        var typed = inp.value.trim();
                        var v = (typed && typed !== '••••••••') ? typed : (stored || '');
                        if (v) collected.push(v);
                    }
                }
                user.passwords = collected.length ? collected : [];
                user.password = user.passwords[0] || '';
            } else {
                var p1 = byId('up-password').value;
                var p2 = byId('up-password2').value;
                if (p1 !== p2) { alert('Passwords do not match.'); return; }
                if (p1) user.password = p1;
            }

            fetch('/api/dashboard/users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role: roleId, users: users })
            }).then(function (r) { return r.json(); }).then(function (res) {
                if (res.success) {
                    profile.style.display = 'none';
                    content.style.display = '';
                    showRoleDetail(container, roleId);
                } else alert('Save failed.');
            }).catch(function () { alert('Save failed.'); });
        };
    }

    function openAddUserForm(roleId, contentEl, currentUsers) {
        var formHtml = '<div class="dashboard-add-user-form">' +
            '<h4>Add user</h4>' +
            '<label>Name: <input type="text" id="au-name" /></label>' +
            '<label>Id: <input type="text" id="au-id" /></label>' +
            '<label>Password: <input type="password" id="au-password" /></label>' +
            '<label>Re-enter Password: <input type="password" id="au-password2" /></label>' +
            '<label>E-mail (Optional): <input type="email" id="au-email" /></label>' +
            '<button type="button" class="btn dashboard-btn" id="au-submit">Add</button>' +
            '</div>';
        var wrap = document.createElement('div');
        wrap.className = 'dashboard-modal-overlay';
        wrap.innerHTML = '<div class="dashboard-modal">' + formHtml + '</div>';
        wrap.addEventListener('click', function (e) { if (e.target === wrap) wrap.remove(); });
        document.body.appendChild(wrap);

        document.getElementById('au-submit').addEventListener('click', function () {
            var name = document.getElementById('au-name').value.trim();
            var id = document.getElementById('au-id').value.trim();
            var p1 = document.getElementById('au-password').value;
            var p2 = document.getElementById('au-password2').value;
            var email = document.getElementById('au-email').value.trim();
            if (!name || !id) { alert('Name and Id are required.'); return; }
            if (p1 !== p2) { alert('Passwords do not match.'); return; }
            var newUser = { name: name, id: id, email: email || undefined };
            if (p1) newUser.password = p1;
            currentUsers.push(newUser);
            fetch('/api/dashboard/users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role: roleId, users: currentUsers })
            }).then(function (r) { return r.json(); }).then(function (res) {
                if (res.success) {
                    wrap.remove();
                    showRoleDetail(document.getElementById('panel-users'), roleId);
                } else alert('Save failed.');
            }).catch(function () { alert('Save failed.'); });
        });
    }

    function openAvatarUpload(userId, roleId, blockEl, containerForRefresh) {
        var input = document.createElement('input');
        input.type = 'file';
        input.accept = 'image/*';
        input.onchange = function () {
            if (!input.files || !input.files[0]) return;
            var fd = new FormData();
            fd.append('file', input.files[0]);
            fd.append('user_id', userId);
            fetch('/api/dashboard/users/avatar/' + encodeURIComponent(userId), {
                method: 'POST',
                body: fd
            }).then(function (r) { return r.json(); }).then(function (res) {
                if (res.success && res.url) {
                    var ring = blockEl && blockEl.querySelector && blockEl.querySelector('.dashboard-user-avatar-ring');
                    if (ring) {
                        ring.style.backgroundImage = 'url(' + res.url + ')';
                        ring.style.backgroundSize = 'cover';
                        var plus = ring.querySelector('.dashboard-user-avatar-plus');
                        if (plus) plus.remove();
                    }
                    var users = (window._dashboardUsersCache && window._dashboardUsersCache[roleId]) || [];
                    var u = users.find(function (x) { return (x.id || '') === userId; });
                    if (u) {
                        u.avatar_url = res.url;
                        fetch('/api/dashboard/users', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ role: roleId, users: users })
                        }).catch(function () {});
                    }
                    if (containerForRefresh) showRoleDetail(containerForRefresh, roleId);
                }
            });
        };
        input.click();
    }

    window.DashboardTabUsers = { render: render };
})();
