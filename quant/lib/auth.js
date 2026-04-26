// 入口密码 gate（mvp-plan §3.6 / §5.0）
// 密码 weiaini → MD5 eaf4f812fc1a6abc3e9b8182171ffc21
// localStorage 永久生效，季度轮换
//
// 用法：在每个 quant 页面 <head> 中：
//   <script src="lib/md5.min.js"></script>
//   <script src="lib/auth.js"></script>
//   <script>QuantAuth.gate();</script>
(function () {
    'use strict';

    // 配置统一从 QuantConfig 读取（M-4 review fix）
    function _cfg() {
        if (window.QuantConfig) return window.QuantConfig;
        // 回退：保留兼容性，避免 config.js 未加载时整个 gate 失效
        return {
            authHash: 'eaf4f812fc1a6abc3e9b8182171ffc21',
            storage: { authKey: 'quant_auth' },
        };
    }
    var EXPECTED_HASH = _cfg().authHash;
    var STORAGE_KEY = _cfg().storage.authKey;

    function isAuthorized() {
        try {
            return window.localStorage.getItem(STORAGE_KEY) === '1';
        } catch (e) {
            return false;
        }
    }

    function setAuthorized() {
        try {
            window.localStorage.setItem(STORAGE_KEY, '1');
        } catch (e) {
            console.warn('localStorage write failed', e);
        }
    }

    function clearAuthorized() {
        try {
            window.localStorage.removeItem(STORAGE_KEY);
        } catch (e) { /* ignore */ }
    }

    function showOverlay(onSubmit) {
        // 移除已有 overlay（防止重复弹）
        var existing = document.getElementById('quant-auth-overlay');
        if (existing) existing.remove();

        var overlay = document.createElement('div');
        overlay.id = 'quant-auth-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.style.cssText = [
            'position:fixed', 'inset:0', 'background:rgba(0,0,0,0.55)',
            'display:flex', 'align-items:center', 'justify-content:center',
            'z-index:99999', 'font-family:-apple-system,BlinkMacSystemFont,sans-serif'
        ].join(';');

        var modal = document.createElement('div');
        modal.style.cssText = 'background:#fff;border-radius:12px;padding:32px;min-width:320px;max-width:480px;box-shadow:0 12px 40px rgba(0,0,0,0.25);';
        modal.innerHTML = [
            '<h2 style="margin:0 0 8px;font-size:20px;color:#222;">量化信号系统</h2>',
            '<p style="margin:0 0 20px;color:#888;font-size:14px;">访问验证</p>',
            '<input id="quant-auth-input" type="password" placeholder="访问密码" style="width:100%;padding:12px;border:1px solid #ddd;border-radius:8px;font-size:15px;box-sizing:border-box;">',
            '<div id="quant-auth-error" style="color:#e74c3c;font-size:13px;margin-top:8px;min-height:18px;"></div>',
            '<button id="quant-auth-submit" style="width:100%;margin-top:16px;padding:12px;background:#2c7a7b;color:#fff;border:0;border-radius:8px;font-size:15px;cursor:pointer;">确认</button>'
        ].join('');
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        var input = document.getElementById('quant-auth-input');
        var err = document.getElementById('quant-auth-error');
        var btn = document.getElementById('quant-auth-submit');

        function handle() {
            var pwd = input.value;
            if (!pwd) {
                err.textContent = '请输入密码';
                return;
            }
            if (typeof md5 !== 'function') {
                err.textContent = 'md5 库未加载';
                return;
            }
            var hash = md5(pwd);
            if (hash === EXPECTED_HASH) {
                setAuthorized();
                overlay.remove();
                if (typeof onSubmit === 'function') onSubmit();
            } else {
                err.textContent = '密码错误';
                input.value = '';
                input.focus();
            }
        }

        btn.addEventListener('click', handle);
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') handle();
        });
        setTimeout(function () { input.focus(); }, 50);
    }

    function gate(opts) {
        opts = opts || {};
        if (isAuthorized()) {
            if (opts.onAuthorized) opts.onAuthorized();
            return true;
        }
        showOverlay(opts.onAuthorized || function () { window.location.reload(); });
        return false;
    }

    window.QuantAuth = {
        gate: gate,
        isAuthorized: isAuthorized,
        clearAuthorized: clearAuthorized,
        EXPECTED_HASH: EXPECTED_HASH,
    };
})();
