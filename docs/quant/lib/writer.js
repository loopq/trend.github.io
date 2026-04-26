// 前端 writer：单 commit 多文件原子提交（§3.7）+ mergeFn 合同 + operation_id 幂等键 + 错误协议
//
// 流程（GitHub Git Data API）：
//   1. GET /git/refs/heads/main → base_sha
//   2. 对每个 file：GET 当前 content → 调 mergeFn(currentContent) → 拿 newContent + operation_id
//      mergeFn 返回 ok:false → 业务错误，直接抛 MergeContractError 给前端（不重试）
//      mergeFn 返回 ok:true  → 收集
//   3. POST /git/blobs * N → blob_sha[]
//   4. POST /git/trees with {base_tree, tree:[{path,mode,type,sha}]}
//   5. POST /git/commits with {message, tree, parents:[base_sha]}
//   6. PATCH /git/refs/heads/main with {sha:new_commit_sha, force=false}
//      失败 422（parent 冲突）→ 整体重试（重新拉 base + 重新 mergeFn）最多 3 次
//
// MergeResult 协议：
//   { ok: true,  newContent: string, operation_id: string }
//   { ok: false, code: 'NOT_FOUND' | 'ALREADY_DONE' | 'SCHEMA_INVALID' | 'CONFLICT', message: string }
(function () {
    'use strict';

    function cfg() {
        if (!window.QuantConfig) {
            throw new Error('QuantConfig 未加载，请确保 lib/config.js 在 lib/writer.js 之前引入');
        }
        return window.QuantConfig;
    }
    var MAX_RETRY = 3;

    function getPat() {
        try { return window.localStorage.getItem(cfg().storage.patKey) || ''; } catch (e) { return ''; }
    }
    function setPat(token) {
        try { window.localStorage.setItem(cfg().storage.patKey, token); } catch (e) { /* ignore */ }
    }
    function clearPat() {
        try { window.localStorage.removeItem(cfg().storage.patKey); } catch (e) { /* ignore */ }
    }

    function MergeContractError(path, code, message) {
        var e = new Error('[' + path + '] ' + code + ': ' + message);
        e.code = code;
        e.path = path;
        e.name = 'MergeContractError';
        return e;
    }

    function ghApi(method, path, body, token) {
        return fetch('https://api.github.com' + path, {
            method: method,
            headers: {
                'Authorization': 'Bearer ' + token,
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
            },
            body: body ? JSON.stringify(body) : undefined,
        }).then(function (resp) {
            if (resp.status === 401) {
                var e = new Error('PAT 失效或权限不足');
                e.code = 'UNAUTHORIZED';
                throw e;
            }
            if (!resp.ok) {
                return resp.text().then(function (text) {
                    var e = new Error('GitHub API ' + method + ' ' + path + ' failed: ' + resp.status + ' ' + text);
                    e.status = resp.status;
                    throw e;
                });
            }
            return resp.json();
        });
    }

    function utf8ToBase64(str) {
        return btoa(unescape(encodeURIComponent(str)));
    }
    function base64ToUtf8(b64) {
        return decodeURIComponent(escape(atob(b64)));
    }

    // 拉文件最新内容（基于某个 ref）
    function getFileContent(owner, repo, branch, filePath, token) {
        var url = '/repos/' + owner + '/' + repo + '/contents/' + filePath + '?ref=' + branch;
        return ghApi('GET', url, null, token).then(function (resp) {
            if (resp.encoding !== 'base64') {
                throw new Error('unexpected encoding: ' + resp.encoding);
            }
            return base64ToUtf8(resp.content);
        }).catch(function (err) {
            if (err.status === 404) return '';   // 文件不存在 → 空字符串，让 mergeFn 决定如何初始化
            throw err;
        });
    }

    function commitAtomic(opts) {
        // opts: { files: [{path, mergeFn(latestRaw) -> MergeResult}], message, owner?, repo?, branch?, token? }
        var token = opts.token || getPat();
        if (!token) {
            return Promise.reject(Object.assign(new Error('请先在设置页输入 GitHub PAT'), { code: 'NO_PAT' }));
        }
        var c = cfg();
        var owner = opts.owner || c.repo.owner;
        var repo = opts.repo || c.repo.name;
        var branch = opts.branch || c.repo.branch;
        var prefix = '/repos/' + owner + '/' + repo;

        function attempt(retriesLeft) {
            return ghApi('GET', prefix + '/git/refs/heads/' + branch, null, token)
                .then(function (ref) {
                    var baseSha = ref.object.sha;
                    return ghApi('GET', prefix + '/git/commits/' + baseSha, null, token)
                        .then(function (commit) {
                            var baseTreeSha = commit.tree.sha;
                            // 对每个 file：拉最新 → 调 mergeFn → 拿 newContent
                            var mergePromises = opts.files.map(function (f) {
                                return getFileContent(owner, repo, branch, f.path, token).then(function (latestRaw) {
                                    var result = f.mergeFn(latestRaw);
                                    if (!result.ok) {
                                        throw MergeContractError(f.path, result.code, result.message);
                                    }
                                    return { path: f.path, content: result.newContent, operation_id: result.operation_id };
                                });
                            });
                            return Promise.all(mergePromises).then(function (mergedFiles) {
                                // POST blobs
                                var blobPromises = mergedFiles.map(function (mf) {
                                    return ghApi('POST', prefix + '/git/blobs', {
                                        content: utf8ToBase64(mf.content),
                                        encoding: 'base64',
                                    }, token).then(function (blob) {
                                        return { path: mf.path, mode: '100644', type: 'blob', sha: blob.sha };
                                    });
                                });
                                return Promise.all(blobPromises).then(function (treeItems) {
                                    return ghApi('POST', prefix + '/git/trees', {
                                        base_tree: baseTreeSha,
                                        tree: treeItems,
                                    }, token);
                                }).then(function (newTree) {
                                    return ghApi('POST', prefix + '/git/commits', {
                                        message: opts.message,
                                        tree: newTree.sha,
                                        parents: [baseSha],
                                    }, token);
                                }).then(function (newCommit) {
                                    return ghApi('PATCH', prefix + '/git/refs/heads/' + branch, {
                                        sha: newCommit.sha,
                                        force: false,
                                    }, token).then(function () {
                                        return {
                                            commit_sha: newCommit.sha,
                                            files: mergedFiles.map(function (mf) { return mf.path; }),
                                            operation_ids: mergedFiles.map(function (mf) { return mf.operation_id; }),
                                        };
                                    });
                                });
                            });
                        });
                })
                .catch(function (err) {
                    // MergeContractError 不重试（业务错误）
                    if (err.name === 'MergeContractError') throw err;
                    // parent SHA 冲突（422）→ 重新拉 base + 重新 mergeFn → 重试
                    if (err.status === 422 && retriesLeft > 0) {
                        return attempt(retriesLeft - 1);
                    }
                    throw err;
                });
        }

        return attempt(MAX_RETRY);
    }

    // 帮助函数：根据 MergeResult.code 返回用户可见提示文案
    function describeError(err) {
        if (err.name !== 'MergeContractError') return null;
        switch (err.code) {
            case 'ALREADY_DONE':   return { type: 'info', msg: '此操作已完成，无需重复' };
            case 'NOT_FOUND':      return { type: 'error', msg: '目标对象已消失（可能已过期），请刷新页面' };
            case 'CONFLICT':       return { type: 'error', msg: '状态冲突（可能已被其他操作处理），请刷新查看最新状态' };
            case 'SCHEMA_INVALID': return { type: 'error', msg: '数据格式异常，请联系管理员检查' };
        }
        return { type: 'error', msg: err.message };
    }

    // 生成 operation_id（带 nonce 防重复）
    function generateOpId(action, signalId) {
        var nonce = Math.random().toString(36).slice(2, 10);
        return action + '-' + signalId + '-' + nonce;
    }

    window.QuantWriter = {
        commitAtomic: commitAtomic,
        getPat: getPat,
        setPat: setPat,
        clearPat: clearPat,
        describeError: describeError,
        generateOpId: generateOpId,
    };
})();
