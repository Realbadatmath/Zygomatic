// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

/**
 * CSRF protection: inject X-CSRF-Token header for state-changing same-origin requests.
 * Token comes from meta name="csrf-token" or GET /api/csrf-token.
 * Load this script early so it patches fetch before other scripts run.
 */
(function () {
    'use strict';

    var token = null;
    var tokenPromise = null;

    function getToken() {
        if (token) return Promise.resolve(token);
        var meta = document.querySelector('meta[name="csrf-token"]');
        if (meta && meta.getAttribute('content')) {
            token = meta.getAttribute('content');
            return Promise.resolve(token);
        }
        if (tokenPromise) return tokenPromise;
        tokenPromise = fetch('/api/csrf-token', { credentials: 'same-origin' })
            .then(function (r) {
                if (r.ok) return r.json();
                return {};
            })
            .then(function (data) {
                token = (data && data.csrf_token) || '';
                return token;
            })
            .catch(function () {
                token = '';
                return token;
            });
        return tokenPromise;
    }

    function needsCsrf(url, method) {
        if (!method || method.toUpperCase() === 'GET') return false;
        try {
            var u = new URL(url, window.location.origin);
            return u.origin === window.location.origin && u.pathname.startsWith('/api/');
        } catch (e) {
            return false;
        }
    }

    var origFetch = window.fetch;
    window.fetch = function (url, opts) {
        opts = opts || {};
        var method = (opts.method || 'GET').toUpperCase();
        if (needsCsrf(typeof url === 'string' ? url : url.url || '', method)) {
            return getToken().then(function (t) {
                opts = Object.assign({}, opts);
                opts.headers = Object.assign({}, opts.headers || {});
                if (t) opts.headers['X-CSRF-Token'] = t;
                return origFetch.call(window, url, opts);
            });
        }
        return origFetch.call(window, url, opts);
    };
})();
