/**
 * 回测报告查看器 + 在线触发
 *
 * 设计参考：docs/agents/quant/quant-backtest-runner-plan.md (v4.3)
 *
 * v4 核心特性：
 * - runner: 输入框触发 GitHub Actions workflow → 轮询 → 自动跳详情
 * - viewer: 列表/详情双态（v3.3 沿用）
 * - 状态机 6 态：loading/list/detail/empty/error/running
 * - URL 路由严格白名单 + DOMPurify 净化
 * - 完整 dialog a11y（focus trap/escape/恢复焦点）
 * - 关联 workflow run 用 UUID（无时钟依赖）
 */
(function (global) {
    'use strict';

    var STATES = ['loading', 'list', 'detail', 'empty', 'error', 'running'];
    var CODE_RE = /^(\d{6}|[A-Z]{2,10})$/;
    var NAME_RE = /^[一-龥A-Za-z0-9 ()（）·\-&]{1,30}$/;
    var REGIONS = ['cn', 'us', 'hk', 'btc'];
    var REGION_LABEL = {
        cn: '🇨🇳 A 股',
        us: '🇺🇸 美股',
        hk: '🇭🇰 港股',
        btc: '₿ 加密',
    };
    var FETCH_TIMEOUT_MS = 10000;
    var INDEX_PATH = 'backtest/index.json';
    var SS_KEY = 'quant_backtest_index_v1';

    // GitHub API 路径（QuantConfig.repo 是 {owner, name, branch} 对象）
    var REPO_CONF = (window.QuantConfig && QuantConfig.repo) || {owner: 'loopq', name: 'trend.github.io', branch: 'main'};
    var REPO = REPO_CONF.owner + '/' + REPO_CONF.name;
    var REPO_BRANCH = REPO_CONF.branch || 'main';
    var API_BASE = 'https://api.github.com/repos/' + REPO;
    var WORKFLOW_FILE = 'backtest.yml';

    var state = {
        current: 'loading',
        index: null,
        currentCode: null,
        markdown: null,
        listFilter: '',
        error: null,
        running: null,   // {code, name, region, requestId, runId, startedAt, workflowStatus}
    };

    // ============ 状态机 ============

    function setState(next, patch) {
        if (STATES.indexOf(next) < 0) throw new Error('invalid state: ' + next);
        if (patch) {
            for (var k in patch) {
                if (Object.prototype.hasOwnProperty.call(patch, k)) state[k] = patch[k];
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

    // ============ fetch 超时 ============

    function fetchWithTimeout(url, init, timeoutMs) {
        if (typeof init === 'number') { timeoutMs = init; init = undefined; }
        timeoutMs = timeoutMs || FETCH_TIMEOUT_MS;
        if (typeof AbortController === 'undefined') return fetch(url, init);
        var ctrl = new AbortController();
        var timer = setTimeout(function () { ctrl.abort(); }, timeoutMs);
        var opts = init ? Object.assign({}, init, { signal: ctrl.signal }) : { signal: ctrl.signal };
        return fetch(url, opts).finally(function () { clearTimeout(timer); });
    }

    // ============ 索引加载 + 路由 ============

    function loadIndex(forceRefresh) {
        // Issue #1 修复：forceRefresh=true 时强制走网络（用于 onBacktestSuccess 后轮询）
        if (!forceRefresh) {
            var cached = sessionStorage.getItem(SS_KEY);
            if (cached) {
                try { state.index = JSON.parse(cached); return Promise.resolve(state.index); }
                catch (e) { sessionStorage.removeItem(SS_KEY); }
            }
        } else {
            sessionStorage.removeItem(SS_KEY);
        }
        // 强制刷新时带 cache-buster query 避免 HTTP cache
        var url = forceRefresh ? (INDEX_PATH + '?_=' + Date.now()) : INDEX_PATH;
        return fetchWithTimeout(url)
            .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
            .then(function (txt) {
                state.index = JSON.parse(txt);
                sessionStorage.setItem(SS_KEY, txt);
                return state.index;
            });
    }

    function parseCodeFromURL() {
        var params = new URLSearchParams(window.location.search);
        var code = params.get('code');
        if (!code || !CODE_RE.test(code)) return null;
        return code;
    }

    function resolveReportFile(code) {
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

    // ============ 详情加载 + DOMPurify 净化 ============

    function safeMd(rawMd) {
        var html = marked.parse(rawMd);
        return DOMPurify.sanitize(html, {
            ALLOWED_TAGS: ['h1','h2','h3','h4','h5','h6','p','blockquote','strong','em',
                           'code','pre','table','thead','tbody','tr','th','td',
                           'ul','ol','li','a','hr','br','span'],
            ALLOWED_ATTR: ['href', 'target', 'rel'],
        });
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
            .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
            .then(function (md) {
                setState('detail', { currentCode: code, markdown: safeMd(md) });
            })
            .catch(function (err) {
                var msg = (err && err.name === 'AbortError')
                    ? '加载超时（>10s）'
                    : '加载失败: ' + (err && err.message ? err.message : err);
                setState('error', { error: { message: msg, retryFn: function () { loadDetail(code); }}});
            });
    }

    // ============ 触发回测 ============

    function genRequestId() {
        if (crypto && crypto.randomUUID) return crypto.randomUUID();
        var arr = new Uint8Array(16);
        (crypto || self.crypto).getRandomValues(arr);
        arr[6] = (arr[6] & 0x0f) | 0x40;
        arr[8] = (arr[8] & 0x3f) | 0x80;
        var hex = Array.prototype.map.call(arr, function (b) {
            return b.toString(16).padStart(2, '0');
        }).join('');
        return [hex.slice(0,8), hex.slice(8,12), hex.slice(12,16), hex.slice(16,20), hex.slice(20,32)].join('-');
    }

    function triggerBacktest(code, name, region) {
        // 字段校验
        if (!CODE_RE.test(code)) {
            alert('code 格式错误：仅 6 位数字或 2-10 位大写字母');
            return;
        }
        if (!NAME_RE.test(name)) {
            alert('name 含非法字符或长度超限：仅中英文/数字/空格/括号/连字符，长度 1-30');
            return;
        }
        if (REGIONS.indexOf(region) < 0) {
            alert('region 仅支持 cn/us/hk/btc');
            return;
        }

        // PAT 校验
        var pat = QuantWriter.getPat();
        if (!pat) {
            setState('error', { error: {
                message: '请先在 settings.html 配置 PAT（需 contents:write + actions:write）',
                retryFn: function () { location.href = 'settings.html'; }
            }});
            return;
        }

        // 已存在 → rerun 弹窗
        if (resolveReportFile(code)) {
            showRerunDialog(code, name, region);
            return;
        }

        // 触发前 confirm
        if (!confirm('确认触发回测：' + code + ' (' + name + ') · ' + REGION_LABEL[region] +
                     '\n\n这会调 GitHub API 启动 workflow，预计 60-180 秒。')) {
            return;
        }
        dispatchBacktest(code, name, region);
    }

    // Issue: writer.js setPat 不 trim，PAT 复制带换行/空格会让 header 非法 → fetch throw
    // 这里强制 trim + 白名单校验
    function getCleanPat() {
        var raw = QuantWriter.getPat() || '';
        var clean = raw.trim();
        // PAT 只能含 ASCII 字母数字 + 下划线 + 连字符
        if (!/^[A-Za-z0-9_\-]+$/.test(clean)) {
            throw new Error('PAT 含非法字符（粘贴时可能带了换行/空格/中文）。请去 settings.html 重新粘贴一次纯 PAT 字符串');
        }
        return clean;
    }

    function dispatchBacktest(code, name, region) {
        var requestId = genRequestId();
        setState('running', { running: {
            code: code, name: name, region: region,
            requestId: requestId,
            startedAt: Date.now(), runId: null,
            workflowStatus: 'dispatching',
        }});

        var cleanPat;
        try {
            cleanPat = getCleanPat();
        } catch (e) {
            closeRunningModal();
            setState('error', { error: {
                message: e.message,
                retryFn: function () { location.href = 'settings.html'; }
            }});
            return;
        }

        fetchWithTimeout(
            API_BASE + '/actions/workflows/' + WORKFLOW_FILE + '/dispatches',
            {
                method: 'POST',
                headers: {
                    'Authorization': 'Bearer ' + cleanPat,
                    'Accept': 'application/vnd.github+json',
                    'X-GitHub-Api-Version': '2022-11-28',
                },
                body: JSON.stringify({
                    ref: REPO_BRANCH,
                    inputs: { code: code, name: name, region: region, request_id: requestId }
                }),
            },
            15000
        )
        .then(function (r) {
            if (r.status === 401 || r.status === 403) {
                var err = new Error('PAT 权限不足（HTTP ' + r.status + '）。需 actions:read + actions:write + contents:write');
                err.fatal = true;
                throw err;
            }
            if (r.status !== 204) throw new Error('HTTP ' + r.status);
            // 按 request_id 精确匹配 run（UUID 唯一无时钟依赖）
            return findRunByRequestId(requestId, code, /* maxRetries */ 12, /* intervalMs */ 2000);
        })
        .then(function (runId) {
            state.running.runId = runId;
            state.running.workflowStatus = 'queued';
            renderRunningModal();
            startPolling();
        })
        .catch(function (err) {
            closeRunningModal();
            // 增强诊断：区分 fetch network 错误 vs HTTP 错误
            var msg = err && err.message ? err.message : String(err);
            if (msg === 'Failed to fetch' || msg === 'Load failed' || (err && err.name === 'TypeError')) {
                msg = '触发失败：浏览器 fetch 直接 reject（不是 HTTP 错误）。常见原因：\n' +
                    '1. PAT 已被 GitHub revoke（请去 settings.html 重填新 PAT）\n' +
                    '2. 浏览器扩展拦截 api.github.com（uBlock/Privacy Badger 等）\n' +
                    '3. 网络/代理问题。打开 DevTools Network 看 dispatches 请求详情';
            } else {
                msg = '触发失败: ' + msg;
            }
            setState('error', { error: {
                message: msg,
                retryFn: function () { triggerBacktest(code, name, region); }
            }});
        });
    }

    // Issue #6 修复：先验 r.ok，401/403 立刻 fail-fast（PAT 权限错误），其他错误正常 reject
    function checkApiResponse(r) {
        if (r.ok) return r.json();
        if (r.status === 401 || r.status === 403) {
            // PAT 权限不足是终态，不应继续重试
            var err = new Error('PAT 权限不足（HTTP ' + r.status + '）。需 actions:read + actions:write + contents:write');
            err.fatal = true;
            throw err;
        }
        // 其他错误（404/429/5xx）让上层重试
        throw new Error('GitHub API HTTP ' + r.status);
    }

    function findRunByRequestId(requestId, code, maxRetries, intervalMs) {
        var attempt = 0;
        var expectedRunName = 'backtest:' + code + ':' + requestId;
        return new Promise(function (resolve, reject) {
            function tryPage(page) {
                var pat;
                try { pat = getCleanPat(); }
                catch (e) { return Promise.reject(Object.assign(e, {fatal: true})); }
                return fetchWithTimeout(
                    API_BASE + '/actions/workflows/' + WORKFLOW_FILE + '/runs?per_page=30&page=' + page,
                    { headers: { 'Authorization': 'Bearer ' + pat }},
                    10000
                )
                .then(checkApiResponse)
                .then(function (data) {
                    var runs = data.workflow_runs || [];
                    var matched = runs.find(function (run) { return run.name === expectedRunName; });
                    if (matched) return matched.id;
                    if (page < 2 && runs.length === 30) return tryPage(page + 1);
                    return null;
                });
            }
            function tryFind() {
                attempt++;
                tryPage(1)
                    .then(function (id) {
                        if (id) resolve(id);
                        else if (attempt >= maxRetries)
                            reject(new Error('找不到 run-name=' + expectedRunName + '（重试 ' + attempt + ' 次）'));
                        else setTimeout(tryFind, intervalMs);
                    })
                    .catch(function (err) {
                        // Issue #6: PAT 错误立即停止重试
                        if (err && err.fatal) { reject(err); return; }
                        if (attempt >= maxRetries) reject(err);
                        else setTimeout(tryFind, intervalMs);
                    });
            }
            tryFind();
        });
    }

    var POLL_INTERVAL = 5000;
    var MAX_POLL_DURATION = 600000;  // 10 min

    function startPolling() {
        var startedAt = state.running.startedAt;
        var runId = state.running.runId;

        function tick() {
            if (Date.now() - startedAt > MAX_POLL_DURATION) {
                closeRunningModal();
                setState('error', { error: {
                    message: '回测超时（>10min），请检查 actions log',
                    retryFn: navigateToList,
                }});
                return;
            }
            var pollPat;
            try { pollPat = getCleanPat(); }
            catch (e) {
                closeRunningModal();
                setState('error', { error: { message: e.message,
                    retryFn: function () { location.href = 'settings.html'; }}});
                return;
            }
            fetchWithTimeout(
                API_BASE + '/actions/runs/' + runId,
                { headers: { 'Authorization': 'Bearer ' + pollPat }},
                10000
            )
            .then(checkApiResponse)
            .then(function (run) {
                state.running.workflowStatus = run.status;
                renderRunningModal();
                if (run.status === 'completed') {
                    if (run.conclusion === 'success') {
                        onBacktestSuccess(state.running.code);
                    } else {
                        closeRunningModal();
                        setState('error', { error: {
                            message: 'workflow 失败：' + run.conclusion + '（查看 actions log）',
                            retryFn: navigateToList,
                        }});
                    }
                } else {
                    setTimeout(tick, POLL_INTERVAL);
                }
            })
            .catch(function (err) {
                // Issue #6: PAT 错误立即停止轮询
                if (err && err.fatal) {
                    closeRunningModal();
                    setState('error', { error: {
                        message: err.message,
                        retryFn: function () { location.href = 'settings.html'; },
                    }});
                    return;
                }
                setTimeout(tick, POLL_INTERVAL);
            });
        }
        tick();
    }

    function onBacktestSuccess(code) {
        // Issue #1 修复：每次重试都强制刷新（不能依赖 sessionStorage cache）
        var attempts = 0;
        function tryReload() {
            attempts++;
            loadIndex(/* forceRefresh */ true)
                .then(function () {
                    if (resolveReportFile(code)) {
                        closeRunningModal();
                        navigateToCode(code);
                    } else if (attempts < 6) {
                        setTimeout(tryReload, 5000);
                    } else {
                        closeRunningModal();
                        setState('error', { error: {
                            message: '回测已完成，但 gh-pages 还未同步。30s 后刷新',
                            retryFn: function () { location.reload(); }
                        }});
                    }
                })
                .catch(function (err) {
                    if (attempts < 6) setTimeout(tryReload, 5000);
                    else {
                        closeRunningModal();
                        setState('error', { error: { message: err.message, retryFn: navigateToList }});
                    }
                });
        }
        tryReload();
    }

    // ============ Modal a11y ============

    var modalState = { lastFocus: null, escHandler: null };

    function openModal(html, escClosable) {
        closeModalIfOpen();
        modalState.lastFocus = document.activeElement;

        var backdrop = document.createElement('div');
        backdrop.className = 'quant-modal-backdrop';
        backdrop.id = 'quant-running-modal';
        backdrop.setAttribute('role', 'dialog');
        backdrop.setAttribute('aria-modal', 'true');
        backdrop.setAttribute('aria-labelledby', 'modal-title');
        backdrop.dataset.escClosable = String(!!escClosable);
        backdrop.innerHTML = html;
        document.body.appendChild(backdrop);

        // 初始焦点
        var firstFocusable = backdrop.querySelector('button, [tabindex="0"], input, select, a[href]');
        if (firstFocusable) firstFocusable.focus();
        else {
            var title = backdrop.querySelector('h3');
            if (title) { title.setAttribute('tabindex', '-1'); title.focus(); }
        }

        // Focus trap
        backdrop.addEventListener('keydown', function (e) {
            if (e.key !== 'Tab') return;
            var focusables = backdrop.querySelectorAll('button, [tabindex="0"], input, select, a[href]');
            if (!focusables.length) return;
            var first = focusables[0], last = focusables[focusables.length - 1];
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        });

        // Escape
        modalState.escHandler = function (e) {
            if (e.key === 'Escape' && backdrop.dataset.escClosable === 'true') {
                closeModalIfOpen();
            }
        };
        document.addEventListener('keydown', modalState.escHandler);
    }

    function closeModalIfOpen() {
        var existing = document.getElementById('quant-running-modal');
        if (existing) existing.remove();
        if (modalState.escHandler) {
            document.removeEventListener('keydown', modalState.escHandler);
            modalState.escHandler = null;
        }
        if (modalState.lastFocus && modalState.lastFocus.focus) {
            modalState.lastFocus.focus();
            modalState.lastFocus = null;
        }
    }

    function closeRunningModal() { closeModalIfOpen(); }

    function renderRunningModal() {
        var r = state.running;
        if (!r) return;
        var elapsed = Math.floor((Date.now() - r.startedAt) / 1000);
        var html =
          '<div class="quant-modal" aria-busy="true">' +
            '<h3 id="modal-title">🔄 回测进行中</h3>' +
            '<p>' + escapeHtml(r.name) + ' (' + escapeHtml(r.code) + ') · ' + escapeHtml(REGION_LABEL[r.region] || r.region) + '</p>' +
            '<p class="muted" aria-live="polite">已耗时 ' + elapsed + 's，预计 60-180s</p>' +
            '<p class="muted" aria-live="polite">workflow 状态：' + escapeHtml(r.workflowStatus || 'dispatching') + '</p>' +
            '<p class="muted">request_id: ' + escapeHtml(r.requestId.slice(0, 8)) + '...</p>' +
            '<div class="modal-actions">' +
              '<a href="https://github.com/' + REPO + '/actions" target="_blank" rel="noopener" class="btn btn-secondary">查看 actions log</a>' +
            '</div>' +
          '</div>';
        var existing = document.getElementById('quant-running-modal');
        if (existing) existing.innerHTML = html;
        else openModal(html, /* escClosable */ false);
    }

    function showRerunDialog(code, name, region) {
        var html =
          '<div class="quant-modal">' +
            '<h3 id="modal-title">报告已存在</h3>' +
            '<p>' + escapeHtml(code) + ' 已有报告。</p>' +
            '<div class="modal-actions">' +
              '<button class="btn btn-secondary" id="btn-view">查看现有</button>' +
              '<button class="btn btn-primary" id="btn-rerun">重新回测</button>' +
            '</div>' +
          '</div>';
        openModal(html, /* escClosable */ true);
        document.getElementById('btn-view').addEventListener('click', function () {
            closeModalIfOpen();
            navigateToCode(code);
        });
        document.getElementById('btn-rerun').addEventListener('click', function () {
            closeModalIfOpen();
            if (confirm('确认重新回测 ' + code + '？\n\n这会覆盖现有报告。')) {
                dispatchBacktest(code, name, region);
            }
        });
    }

    // ============ render ============

    function render() {
        var root = document.getElementById('viewer-root');
        if (!root) return;
        if (state.current === 'loading') {
            root.innerHTML = '<div class="loading-state" role="status">加载中…</div>';
        } else if (state.current === 'error') {
            renderError(root);
        } else if (state.current === 'list') {
            renderList(root);
        } else if (state.current === 'detail') {
            renderDetail(root);
        } else if (state.current === 'empty') {
            root.innerHTML = '<div class="empty-state">暂无报告</div>';
        }
        // 'running' 不替换 root（modal 叠加在 list/error 之上）
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
            if (state.error && typeof state.error.retryFn === 'function') state.error.retryFn();
        });
        document.getElementById('btn-back').addEventListener('click', navigateToList);
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

        var regionOptions = REGIONS.map(function (r) {
            return '<option value="' + r + '">' + REGION_LABEL[r] + '</option>';
        }).join('');

        var html = '';
        // 触发回测 toolbar（v4 新增）
        html += '<div class="trigger-bar" role="region" aria-label="触发回测">';
        html += '  <h3 class="bar-title">🚀 在线回测</h3>';
        html += '  <input id="trig-code" placeholder="code（如 HSTECH）" maxlength="10" aria-label="指数 code">';
        html += '  <input id="trig-name" placeholder="名称（如 恒生科技）" maxlength="30" aria-label="指数名称">';
        html += '  <select id="trig-region" aria-label="地域">' + regionOptions + '</select>';
        html += '  <button class="btn btn-primary" id="btn-trigger">触发回测</button>';
        html += '</div>';

        // 筛选 toolbar
        html += '<div class="viewer-toolbar">';
        html += '  <input id="filter-input" type="text" placeholder="筛选已有报告..." value="' + escapeHtml(state.listFilter || '') + '" aria-label="筛选">';
        html += '  <span class="muted">共 ' + reports.length + '，筛选后 ' + filtered.length + '</span>';
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

        // 绑定触发回测
        document.getElementById('btn-trigger').addEventListener('click', function () {
            var c = document.getElementById('trig-code').value.trim().toUpperCase();
            var n = document.getElementById('trig-name').value.trim();
            var r = document.getElementById('trig-region').value;
            triggerBacktest(c, n, r);
        });

        // 绑定筛选
        var input = document.getElementById('filter-input');
        if (input) {
            input.addEventListener('input', function (e) {
                state.listFilter = e.target.value;
                renderList(root);
            });
        }

        // 列表行点击
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

    function renderDetail(root) {
        var meta = state.index.reports.find(function (r) { return r.code === state.currentCode; });
        var html = '';
        html += '<div class="viewer-toolbar">';
        html += '  <button class="btn btn-secondary" id="btn-back">← 返回列表</button>';
        if (meta) {
            html += '  <span class="muted">' + escapeHtml(meta.code) + ' · ' + escapeHtml(meta.category || '-') + ' · 更新 ' + formatMtime(meta.mtime) + '</span>';
        }
        html += '  <button class="btn btn-secondary" id="btn-rerun-detail" title="重新回测当前指数">🔄 重新回测</button>';
        html += '</div>';
        html += '<div class="markdown-body">' + (state.markdown || '') + '</div>';
        root.innerHTML = html;
        document.getElementById('btn-back').addEventListener('click', navigateToList);
        document.getElementById('btn-rerun-detail').addEventListener('click', function () {
            if (!meta) return;
            triggerBacktest(meta.code, meta.name, meta.category in REGION_LABEL ? meta.category : 'cn');
        });
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
        } catch (e) { return iso; }
    }

    // ============ boot ============

    function boot() {
        loadIndex()
            .then(function () {
                var code = parseCodeFromURL();
                if (code) loadDetail(code);
                else setState('list');
            })
            .catch(function (err) {
                var msg = (err && err.name === 'AbortError')
                    ? '加载索引超时（>10s）'
                    : '索引加载失败：' + (err && err.message ? err.message : err);
                setState('error', { error: {
                    message: msg,
                    retryFn: function () {
                        sessionStorage.removeItem(SS_KEY);
                        boot();
                    },
                }});
            });
    }

    window.addEventListener('popstate', function () {
        var code = parseCodeFromURL();
        if (code) loadDetail(code);
        else setState('list');
    });

    global.BacktestViewer = { boot: boot, _state: state };
})(window);
