// 量化前端共享配置（M-4 review fix：消除 owner/repo/branch 多处硬编码）
// 所有页面 / lib 通过 window.QuantConfig 访问；唯一可信来源
(function () {
    'use strict';

    // 13 指数基线（与 docs/agents/backtest/v9-summary.md / scripts/quant/config.yaml 一致）
    var INDICES = [
        { code: '931151', name: '光伏产业', etfCode: '515790', etfName: '光伏 ETF' },
        { code: '000819', name: '有色金属', etfCode: '512400', etfName: '有色金属 ETF' },
        { code: '399997', name: '中证白酒', etfCode: '161725', etfName: '招商中证白酒 ETF' },
        { code: '399989', name: '中证医疗', etfCode: '512170', etfName: '易方达中证医疗 ETF' },
        { code: '931079', name: '5G 通信', etfCode: '515050', etfName: '5G 通信 ETF' },
        { code: '399808', name: '中证新能', etfCode: '516160', etfName: '国泰中证新能源 ETF' },
        { code: '931071', name: '人工智能', etfCode: '515980', etfName: 'AI ETF' },
        { code: '930721', name: 'CS 智汽车', etfCode: '516520', etfName: '智能汽车 ETF' },
        { code: '399967', name: '中证军工', etfCode: '512660', etfName: '军工 ETF' },
        { code: '399673', name: '创业板 50', etfCode: '159949', etfName: '华安创业板 50 ETF' },
        { code: '000688', name: '科创 50', etfCode: '588000', etfName: '科创 50 ETF' },
        { code: '000813', name: '细分化工', etfCode: '159870', etfName: '化工 ETF' },
        { code: '399976', name: 'CS 新能车', etfCode: '515030', etfName: '新能源车 ETF' },
    ];

    var BY_CODE = {};
    INDICES.forEach(function (i) { BY_CODE[i.code] = i; });

    function nameOf(code) {
        var i = BY_CODE[code];
        return i ? i.name : code;
    }

    function infoOf(code) {
        return BY_CODE[code] || { code: code, name: code, etfCode: '?', etfName: '?' };
    }

    function formatBucket(bucketId) {
        // 把 "399997-D" 显示为 "中证白酒(399997)·D"
        var parts = bucketId.split('-');
        var code = parts[0], freq = parts[1];
        var name = nameOf(code);
        return name + '(' + code + ')·' + freq;
    }

    window.QuantConfig = Object.freeze({
        repo: {
            owner: 'loopq',
            name: 'trend.github.io',
            branch: 'main',
        },
        site: {
            base: 'https://loopq.github.io/trend.github.io',
            quantBase: 'https://loopq.github.io/trend.github.io/quant/',
        },
        storage: {
            authKey: 'quant_auth',
            patKey: 'github_pat',
        },
        authHash: 'eaf4f812fc1a6abc3e9b8182171ffc21',
        indices: INDICES,
        nameOf: nameOf,
        infoOf: infoOf,
        formatBucket: formatBucket,
    });
})();
