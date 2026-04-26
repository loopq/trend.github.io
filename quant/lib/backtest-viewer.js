/**
 * 回测报告查看器
 *
 * 设计参考：docs/agents/quant/quant-backtest-viewer-plan.md (v3.3)
 *
 * 核心特性：
 * - 状态机：loading / list / detail / empty / error（payload 写入契约）
 * - URL 路由严格白名单：仅 index.json 中的 code 可访问
 * - fetchWithTimeout(10s)：兑现文档承诺
 * - a11y：aria-live + 焦点管理 + retry 按钮
 */
(function (global) {
    'use strict';

    var STATES = ['loading', 'list', 'detail', 'empty', 'error'];
    var CODE_RE = /^(\d{6}|[A-Z]{2,10})$/;
    var FETCH_TIMEOUT_MS = 10000;
    var INDEX_PATH = 'backtest/index.json';
    var SS_KEY = 'quant_backtest_index_v1';

    var state = {
        current: 'loading',
        index: null,
        currentCode: null,
        markdown: null,
        listFilter: '',
        error: null,
    };

    // ============ 状态机：setState ============

    function setState(next, patch) {
        if (STATES.indexOf(next) < 0) {
            throw new Error('invalid state: ' + next);
        }
        if (patch) {
            for (var k in patch) {
                if (Object.prototype.hasOwnProperty.call(patch, k)) {
                    state[k] = patch[k];
                }
            }
        }
        state.current = next;

        // fail-safe：错误态必须有数据
        if (next === 'error') {
            if (!state.error) state.error = {};
            if (!state.error.message) state.error.message = '未知错误';
            if (!state.error.retryFn) state.error.retryFn = navigateToList;
        }

        var root = document.getElementById('viewer-root');
        if (root) root.setAttribute('aria-busy', String(next === 'loading'));
        render();
    }

    // ============ fetch 超时包装 ============

    function fetchWithTimeout(url, timeoutMs) {
        timeoutMs = timeoutMs || FETCH_TIMEOUT_MS;
        if (typeof AbortController === 'undefined') {
            // 老浏览器兜底
            return fetch(url);
        }
        var ctrl = new AbortController();
        var timer = setTimeout(function () { ctrl.abort(); }, timeoutMs);
        return fetch(url, { signal: ctrl.signal })
            .finally(function () { clearTimeout(timer); });
    }

    // ============ 索引加载 + 路由解析 ============

    function loadIndex() {
        // sessionStorage 缓存
        var cached = sessionStorage.getItem(SS_KEY);
        if (cached) {
            try {
                state.index = JSON.parse(cached);
                return Promise.resolve(state.index);
            } catch (e) {
                sessionStorage.removeItem(SS_KEY);
            }
        }
        return fetchWithTimeout(INDEX_PATH)
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.text();
            })
            .then(function (txt) {
                state.index = JSON.parse(txt);
                sessionStorage.setItem(SS_KEY, txt);
                return state.index;
            });
    }

    function parseCodeFromURL() {
        var params = new URLSearchParams(window.location.search);
        var code = params.get('code');
        if (!code) return null;
        if (!CODE_RE.test(code)) {
            console.warn('invalid code format:', code);
            return null;
        }
        return code;
    }

    function resolveReportFile(code) {
        // 严格白名单 — 不在 index 里的 code 一律不 fetch
        if (!state.index) return null;
        var found = state.index.reports.find(function (r) { return r.code === code; });
        return found ? found.file : null;
    }

    function navigateToList() {
        history.pushState({}, '', 'backtest.html');
        setState('list');
    }

    function navigateToCode(code) {
        history.pushState({}, '', 'backtest.html?code=' + encodeURIComponent(code));
        loadDetail(code);
    }

    function loadDetail(code) {
        setState('loading');
        var file = resolveReportFile(code);
        if (!file) {
            setState('error', { error: {
                message: '报告 ' + code + ' 不在白名单',
                retryFn: navigateToList,
            }});
            return;
        }
        fetchWithTimeout('backtest/' + file)
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.text();
            })
            .then(function (md) {
                setState('detail', {
                    currentCode: code,
                    markdown: marked.parse(md),
                });
            })
            .catch(function (err) {
                var msg = (err && err.name === 'AbortError')
                    ? '网络超时（>10s）'
                    : '加载失败: ' + (err && err.message ? err.message : err);
                setState('error', { error: {
                    message: msg,
                    retryFn: function () { loadDetail(code); },
                }});
            });
    }

    // ============ render ============

    function render() {
        var root = document.getElementById('viewer-root');
        if (!root) return;

        if (state.current === 'loading') {
            root.innerHTML = '<div class="loading-state" role="status">加载中…</div>';
            return;
        }
        if (state.current === 'error') {
            renderError(root);
            return;
        }
        if (state.current === 'list') {
            renderList(root);
            return;
        }
        if (state.current === 'detail') {
            renderDetail(root);
            return;
        }
        if (state.current === 'empty') {
            root.innerHTML = '<div class="empty-state">暂无报告</div>';
            return;
        }
    }

    function renderError(root) {
        var msg = (state.error && state.error.message) || '未知错误';
        root.innerHTML =
            '<div class="error-state" role="alert">' +
              '<h2 id="err-title" tabindex="-1">⚠️ ' + escapeHtml(msg) + '</h2>' +
              '<div class="error-actions">' +
                '<button class="btn btn-primary" id="btn-retry">重试</button>' +
                '<button class="btn btn-secondary" id="btn-back">返回列表</button>' +
              '</div>' +
            '</div>';
        document.getElementById('btn-retry').addEventListener('click', function () {
            if (state.error && typeof state.error.retryFn === 'function') {
                state.error.retryFn();
            }
        });
        document.getElementById('btn-back').addEventListener('click', navigateToList);
        // 焦点移到错误标题
        var title = document.getElementById('err-title');
        if (title) title.focus();
    }

    function renderList(root) {
        var reports = state.index ? state.index.reports : [];
        var filter = (state.listFilter || '').toLowerCase().trim();
        var filtered = filter
            ? reports.filter(function (r) {
                return r.code.toLowerCase().indexOf(filter) >= 0
                    || r.name.toLowerCase().indexOf(filter) >= 0
                    || (r.category && r.category.toLowerCase().indexOf(filter) >= 0);
            })
            : reports;

        var html = '';
        html += '<div class="viewer-toolbar">';
        html += '  <input id="filter-input" type="text" placeholder="输入 code 或名称..." value="' + escapeHtml(state.listFilter || '') + '" aria-label="筛选回测报告">';
        html += '  <button class="btn btn-primary" id="btn-go">查看</button>';
        html += '  <span class="muted">共 ' + reports.length + ' 个，筛选后 ' + filtered.length + '</span>';
        html += '</div>';

        if (filtered.length === 0) {
            html += '<div class="empty-state">无匹配报告</div>';
        } else {
            html += '<div class="report-list">';
            filtered.forEach(function (r) {
                html += '<div class="report-row" data-code="' + escapeHtml(r.code) + '" tabindex="0" role="button">';
                html += '  <span class="name">' + escapeHtml(r.name) + '</span>';
                html += '  <span class="code">' + escapeHtml(r.code) + '</span>';
                html += '  <span class="category">' + escapeHtml(r.category || '-') + '</span>';
                html += '  <span class="version">v9</span>';
                html += '  <span class="mtime">' + formatMtime(r.mtime) + '</span>';
                html += '</div>';
            });
            html += '</div>';
        }
        root.innerHTML = html;

        // 事件绑定
        var input = document.getElementById('filter-input');
        var btn = document.getElementById('btn-go');
        if (input) {
            input.addEventListener('input', function (e) {
                state.listFilter = e.target.value;
                renderList(root);
            });
            input.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') goByInput();
            });
        }
        if (btn) btn.addEventListener('click', goByInput);
        document.querySelectorAll('.report-row').forEach(function (el) {
            el.addEventListener('click', function () {
                navigateToCode(el.getAttribute('data-code'));
            });
            el.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    navigateToCode(el.getAttribute('data-code'));
                }
            });
        });
    }

    function goByInput() {
        var input = document.getElementById('filter-input');
        var v = (input && input.value || '').trim().toUpperCase();
        if (!v) return;
        if (CODE_RE.test(v)) {
            // 是 code 格式 → 跳详情
            if (resolveReportFile(v)) {
                navigateToCode(v);
            } else {
                setState('error', { error: {
                    message: '报告 ' + v + ' 不在白名单',
                    retryFn: navigateToList,
                }});
            }
        }
        // 非 code 格式：保持列表 + filter 已应用
    }

    function renderDetail(root) {
        var meta = state.index.reports.find(function (r) { return r.code === state.currentCode; });
        var html = '';
        html += '<div class="viewer-toolbar">';
        html += '  <button class="btn btn-secondary" id="btn-back">← 返回列表</button>';
        if (meta) {
            html += '  <span class="muted">' + escapeHtml(meta.code) + ' · ' + escapeHtml(meta.category || '-') + ' · 更新 ' + formatMtime(meta.mtime) + '</span>';
        }
        html += '</div>';
        html += '<div class="markdown-body">' + (state.markdown || '') + '</div>';
        root.innerHTML = html;
        document.getElementById('btn-back').addEventListener('click', navigateToList);
    }

    // ============ utils ============

    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function formatMtime(iso) {
        if (!iso) return '-';
        try {
            var d = new Date(iso);
            return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
        } catch (e) {
            return iso;
        }
    }

    // ============ boot ============

    function boot() {
        loadIndex()
            .then(function () {
                var code = parseCodeFromURL();
                if (code) {
                    loadDetail(code);
                } else {
                    setState('list');
                }
            })
            .catch(function (err) {
                var msg = (err && err.name === 'AbortError')
                    ? '加载索引超时（>10s），请检查网络'
                    : '索引加载失败：' + (err && err.message ? err.message : err) +
                      '。请先生成数据：python scripts/quant/build_quant_backtest.py';
                setState('error', { error: {
                    message: msg,
                    retryFn: function () {
                        sessionStorage.removeItem(SS_KEY);
                        boot();
                    },
                }});
            });
    }

    // 浏览器后退/前进
    window.addEventListener('popstate', function () {
        var code = parseCodeFromURL();
        if (code) {
            loadDetail(code);
        } else {
            setState('list');
        }
    });

    global.BacktestViewer = { boot: boot, _state: state };  // _state 仅 debug
})(window);
