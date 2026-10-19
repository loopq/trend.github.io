# 归档恢复清单（2026-10-19）

> 关联 plan：`agents/plans/2026-10-19-site-refactor-futures-entry-slot.md` §3 B4
> 来源：`origin/gh-pages` = `5dedf2f5c47324088a6e5acb39acbcf3e8892086`（部署前若需回退，以此 SHA 为准）
> 算法：`git rev-list` 由新到旧遍历，每个 commit `git ls-tree archive/`，每个日期取首次遇到（最新）的 blob；不依赖 rename 检测
> 候选：不在 main `docs/archive/` 的日期页；交易日以 000300 日线为准

| 动作 | 数量 |
|---|---|
| 恢复（写入 `docs/archive/`） | 115 |
| 跳过（已在线） | 1 |
| 排除（非交易日） | 5 |
| 候选合计 | 121 |

校验：115 个恢复文件的 blob 哈希与清单一致、`<title>` 日期与文件名一致 —— 全部通过

| 日期 | commit | blob | 当前树已有 | 动作 | 原因 |
|---|---|---|---|---|---|
| 2026-01-17 | `b144208` | `9e8f3002cd` | 否 | 排除 | 非 A 股交易日（Sat） |
| 2026-01-31 | `14e6043` | `6a7c7f4cef` | 否 | 排除 | 非 A 股交易日（Sat） |
| 2026-02-02 | `b34f1ae` | `6aea4687e2` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-02-16 | `2a42517` | `a80a453db6` | 否 | 排除 | 非 A 股交易日（Mon） |
| 2026-04-25 | `83bdfc2` | `c82e5c1b23` | 否 | 排除 | 非 A 股交易日（Sat） |
| 2026-04-26 | `2a5eaa8` | `7453304649` | 否 | 排除 | 非 A 股交易日（Sun） |
| 2026-04-27 | `bc76d63` | `4eb1da1422` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-04-28 | `05f16f5` | `e97e9c9453` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-04-29 | `9b99043` | `7ee0a757e7` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-04-30 | `fd51a74` | `bd08bfc82f` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-06 | `ec58a08` | `4194c6917e` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-07 | `ad63ef3` | `17702c0c22` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-08 | `88fcb4b` | `4cfa82c080` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-11 | `990a519` | `4e07f09202` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-12 | `4459221` | `c6fde3c05b` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-13 | `0668daa` | `a76fda6c8e` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-14 | `ab75eca` | `a3e01355c3` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-15 | `040cbff` | `5f105015a5` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-18 | `515631c` | `84771d2686` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-19 | `aea3bbd` | `4371070a23` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-20 | `b123875` | `c698f4f303` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-21 | `f0fc4c5` | `d6d9792983` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-22 | `1640239` | `c6ecefe0ea` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-25 | `d99a5f5` | `b555dcc54e` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-26 | `6391b7c` | `1071ad9ec0` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-27 | `82529ab` | `3f7982215d` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-28 | `fbbe1e3` | `bf2b94005f` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-05-29 | `5a8ee3d` | `0ac9ce1f83` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-01 | `548ebcf` | `51004dd27f` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-02 | `0688c37` | `ab385c4e62` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-03 | `14a1ac2` | `de5c313ba8` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-04 | `5637f57` | `ed605807b8` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-05 | `bface6c` | `bb3dd0a5e1` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-08 | `ce95907` | `f28717ee95` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-09 | `1e298cc` | `e31c42c3f7` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-10 | `797d6d1` | `1b941429d3` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-11 | `ef82331` | `0d7467ee55` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-12 | `efbc804` | `ecff8f6ef9` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-15 | `9fd1bf2` | `a6c017ff5a` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-16 | `4d1944a` | `daa67dd9c4` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-17 | `0112232` | `3372a1027c` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-18 | `bc83a72` | `7b44784a8b` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-22 | `18eee0d` | `8c3a34f68e` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-23 | `c5b6a31` | `2c177198a5` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-24 | `025ff90` | `e55eee1ceb` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-25 | `64cc442` | `21cb433664` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-26 | `a259401` | `b0d36812be` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-29 | `afb2fee` | `f6d7ae39c4` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-06-30 | `c020466` | `f9c4b23bc1` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-01 | `853cd00` | `8eefc02ef6` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-02 | `0a6ca28` | `51688a2980` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-03 | `0c73fd9` | `4d9eacd6b5` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-06 | `84f006e` | `304ffc6aa2` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-07 | `0e141e1` | `452a489069` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-08 | `1f8cac6` | `0741a05389` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-09 | `e195861` | `abafe1b439` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-10 | `92fa550` | `cd986325e1` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-13 | `7b9d55a` | `5ab4ba84b9` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-14 | `42d8a45` | `4e32631f83` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-15 | `46072f3` | `25d5375e64` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-16 | `eaff961` | `85d4dd5c2c` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-17 | `001a88a` | `3fc8c29fa6` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-20 | `f2d085b` | `138d44e781` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-21 | `5ce630d` | `d32f164343` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-22 | `1f58cb0` | `7fa8e9666a` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-23 | `db68ea4` | `70e5f067e5` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-24 | `20bb7be` | `f6ef061e04` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-27 | `892acab` | `4233d175d5` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-28 | `db141ca` | `c56af23281` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-29 | `eeb9ad5` | `a3a057871d` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-30 | `95c1d77` | `099d60d2b5` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-07-31 | `bbd99bc` | `54578cdcb8` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-03 | `6f14fe8` | `27f371079e` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-04 | `df45458` | `b00ad25f51` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-05 | `932eead` | `e34075f947` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-06 | `3dc0c37` | `d11bcf3fbb` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-07 | `585ca7a` | `cce2820ae0` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-10 | `9aa6c5d` | `5ba642efe0` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-11 | `eaf70e9` | `54c78a660a` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-12 | `b31c61f` | `22fc03edee` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-13 | `f4e918f` | `11d895e09e` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-14 | `a1e29a5` | `1dd351d168` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-17 | `8215d90` | `5d88ce1c28` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-18 | `fb69949` | `9b9077708c` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-19 | `906e57b` | `09c17336d7` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-20 | `dd88514` | `b512a70fd9` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-21 | `dc557f3` | `95897fcdc3` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-24 | `4b372ba` | `71c65b1b4d` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-25 | `76ac755` | `a8fa2807df` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-26 | `39a7d76` | `f375772b52` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-27 | `fe88710` | `0a113cc110` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-28 | `b362760` | `7d3faed246` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-08-31 | `a5e71f3` | `3f82ff9061` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-01 | `e9f8b48` | `cbfe55881d` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-02 | `f795e62` | `09c6ca35c0` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-03 | `aeb1aef` | `caafb71960` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-04 | `6e23af6` | `4ad3f7e3b4` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-07 | `3afb0f4` | `f08ca24aa6` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-08 | `bcd7110` | `7996d8ab4e` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-09 | `832a5c1` | `8d5e1c563d` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-10 | `37f0b16` | `8f1ce1523a` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-11 | `68d029f` | `f57d98e583` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-14 | `756acbd` | `9781c70ab0` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-15 | `a0d2ad9` | `dfc277a567` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-16 | `39e531e` | `67a4d1780c` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-17 | `c16bdc9` | `0af985f694` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-18 | `60c1c4b` | `5ec80a12bc` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-21 | `ed6750c` | `d7be8cd05d` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-22 | `6c92907` | `a7ffcd885e` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-23 | `9299fdf` | `89b5e45c26` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-24 | `700c449` | `0e8300115c` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-28 | `2266f0d` | `2ef5803e45` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-29 | `e2ddd4b` | `b2fe643566` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-09-30 | `1847e18` | `76526cc192` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-10-08 | `f9aada0` | `1e1a319b88` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-10-09 | `9acb60b` | `3ec4b8f2bb` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-10-12 | `94c67fd` | `be88f7a4b1` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-10-13 | `5ce844e` | `f0e765b4ed` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-10-14 | `ef59095` | `1f5061df9b` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-10-15 | `9cff826` | `e8ae806b60` | 否 | 恢复 | 交易日归档，被 keep_files=false 部署抹掉 |
| 2026-10-16 | `5dedf2f` | `bf96f04640` | 是 | 跳过 | 已在 gh-pages 当前树，由 update.yml restore 保留 |
