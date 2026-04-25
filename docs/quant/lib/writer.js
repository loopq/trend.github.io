// 前端 writer：单 commit 多文件原子提交（§3.7 + §10 Phase 4.5）
//
// 流程（GitHub Git Data API）：
//   1. GET /git/refs/heads/main → base_sha
//   2. GET /git/commits/{base_sha} → base_tree_sha
//   3. POST /git/blobs * N → blob_sha[]
//   4. POST /git/trees with {base_tree, tree:[...{path,mode,type,sha}]}
//   5. POST /git/commits with {message, tree, parents:[base_sha]}
//   6. PATCH /git/refs/heads/main with {sha:new_commit_sha}
//      失败（parent SHA 不一致 = 422）→ 重新拉 + 重 apply + 重试，最多 3 次
//
// PAT：从 localStorage 读 'github_pat'；401 → 抛错让上层弹出 PAT 输入框
(function () {
    'use strict';

    // 仓库与存储键统一从 QuantConfig 读取（M-4 review fix）
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
        // unescape(encodeURIComponent) 是处理 UTF-8 → base64 的经典 trick
        return btoa(unescape(encodeURIComponent(str)));
    }

    function commitAtomic(opts) {
        // opts: { files: [{path, content}], message, owner?, repo?, branch?, token? }
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
                            // POST blobs in parallel
                            var blobPromises = opts.files.map(function (f) {
                                return ghApi('POST', prefix + '/git/blobs', {
                                    content: utf8ToBase64(f.content),
                                    encoding: 'base64',
                                }, token).then(function (blob) {
                                    return { path: f.path, mode: '100644', type: 'blob', sha: blob.sha };
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
                                    return { commit_sha: newCommit.sha, files: opts.files.map(function (f) { return f.path; }) };
                                });
                            });
                        });
                })
                .catch(function (err) {
                    // parent SHA 冲突（422）→ 重试
                    if (err.status === 422 && retriesLeft > 0) {
                        return attempt(retriesLeft - 1);
                    }
                    throw err;
                });
        }

        return attempt(MAX_RETRY);
    }

    window.QuantWriter = {
        commitAtomic: commitAtomic,
        getPat: getPat,
        setPat: setPat,
        clearPat: clearPat,
    };
})();
