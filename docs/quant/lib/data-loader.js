// 数据加载器（§3.5.1 + §10 Phase 4.3）
// 所有页面统一通过本模块访问 data/quant/* 文件，禁止任何通配符 fetch。
// cache-busting：每个 fetch 加 ?t=${Date.now()} 防 GitHub raw CDN 缓存。
(function () {
    'use strict';

    var BASE = '../data/quant/';  // 相对 /docs/quant/ 子页路径

    function withBust(url) {
        var sep = url.indexOf('?') === -1 ? '?' : '&';
        return url + sep + 't=' + Date.now();
    }

    function fetchJson(path) {
        return fetch(withBust(BASE + path), { cache: 'no-store' })
            .then(function (resp) {
                if (!resp.ok) throw new Error('fetch ' + path + ' failed: ' + resp.status);
                return resp.json();
            });
    }

    function loadPositions() {
        return fetchJson('positions.json').catch(function () {
            return { version: 1, updated_at: '', paper_trading: true, buckets: {} };
        });
    }

    function loadTransactions() {
        return fetchJson('transactions.json').catch(function () {
            return { transactions: [] };
        });
    }

    function loadSignalsIndex() {
        return fetchJson('signals/index.json').catch(function () {
            return { version: 1, updated_at: '', entries: [] };
        });
    }

    // 按需加载某一日的信号文件（lazy load）
    function loadSignalsForDate(dateStr) {
        return fetchJson('signals/' + dateStr + '.json');
    }

    // 加载多日（并行）
    function loadSignalsForDates(dates) {
        return Promise.all(dates.map(function (d) {
            return loadSignalsForDate(d).catch(function () { return null; });
        })).then(function (results) {
            return results.filter(function (r) { return r !== null; });
        });
    }

    // transactions.json 数量超过 5000 时给警告
    function checkSizeWarning(transactionsObj) {
        var n = transactionsObj.transactions ? transactionsObj.transactions.length : 0;
        if (n > 5000) {
            console.warn('[quant] transactions.json 已超 5000 条，建议触发分片重构');
        }
        return n;
    }

    window.QuantData = {
        loadPositions: loadPositions,
        loadTransactions: loadTransactions,
        loadSignalsIndex: loadSignalsIndex,
        loadSignalsForDate: loadSignalsForDate,
        loadSignalsForDates: loadSignalsForDates,
        checkSizeWarning: checkSizeWarning,
        BASE: BASE,
    };
})();
