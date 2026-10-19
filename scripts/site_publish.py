#!/usr/bin/env python3
"""
主站发布准备（update.yml 使用）

gh-pages 有两个写入方：update.yml 发布主站文件，backtest.yml 发布 quant/ 与 data/。
主站只发布自己拥有的文件，并在生成前从 gh-pages 恢复历史归档，配合 keep_files 永不抹掉线上内容。

Usage:
    python -m scripts.site_publish restore origin/gh-pages docs   # 生成前：恢复归档（失败即非零退出）
    python -m scripts.site_publish stage docs /tmp/site-publish    # 生成后：组装发布目录
"""

import argparse
import io
import os
import shutil
import subprocess
import tarfile

# 主站拥有的发布内容；新增站点页面（如 futures/）在此登记
SITE_FILES = ["index.html", "CNAME"]
SITE_DIRS = ["css", "archive", "futures"]


def restore_archives(ref: str, docs_dir: str, repo: str = ".") -> int:
    """把 ref（如 origin/gh-pages）上的 archive/ 解包到 docs_dir/archive/，返回文件数。

    ref 不存在或无 archive/ 时抛 CalledProcessError —— 宁可不部署，也不能用残缺的归档覆盖线上。
    """
    tar = subprocess.run(["git", "archive", "--format=tar", ref, "archive"],
                         cwd=repo, check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
        files = [m for m in tf.getmembers() if m.isfile()]
        tf.extractall(docs_dir, members=files, filter="data")
    return len(files)


def stage(docs_dir: str, out_dir: str) -> None:
    """组装发布目录：只含主站文件，不含 quant/、data/（归 backtest.yml 发布）"""
    shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir)
    for name in SITE_FILES:
        shutil.copy2(os.path.join(docs_dir, name), out_dir)
    for name in SITE_DIRS:
        shutil.copytree(os.path.join(docs_dir, name), os.path.join(out_dir, name))


def main():
    parser = argparse.ArgumentParser(description="主站发布准备")
    sub = parser.add_subparsers(dest="cmd", required=True)
    restore = sub.add_parser("restore", help="从发布分支恢复历史归档")
    restore.add_argument("ref")
    restore.add_argument("docs_dir")
    restore.add_argument("--repo", default=".")
    staging = sub.add_parser("stage", help="组装只含主站文件的发布目录")
    staging.add_argument("docs_dir")
    staging.add_argument("out_dir")
    args = parser.parse_args()

    if args.cmd == "restore":
        print(f"restored {restore_archives(args.ref, args.docs_dir, args.repo)} archive files from {args.ref}")
    else:
        stage(args.docs_dir, args.out_dir)
        print(f"staged site files into {args.out_dir}")


if __name__ == "__main__":
    main()
