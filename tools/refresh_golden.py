#!/usr/bin/env python3
"""重新匯入 golden fixture。

用法：python3 tools/refresh_golden.py --host claude|codex|agy|grok|opencode --from <repo> --ref <sha>
      opencode 另需 --extra-from <dotfile repo> --extra-ref <sha>（catalog.json / routing.json 的來源）
      python3 tools/refresh_golden.py --host <host> --from-dist
        （切換後的模式：從本 repo 的 DIST_DIRS[host] 複製，SOURCE 記 shoal@<HEAD sha>，
        golden 變成 regression fixture，不再對照舊 host repo）
會清空 tests/golden/<host>/ 後重建，並寫入 SOURCE 記錄來源。
"""
from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import DIST_DIRS  # noqa: E402
# 各 host 的 golden 來源：[(哪個 repo, 匯出的路徑, 從 golden 相對路徑剝掉的前綴)]。
# "primary" 對應 --from/--ref，"extra" 對應 --extra-from/--extra-ref。
SOURCES = {
    "claude": [("primary", ["templates"], "templates")],
    "codex": [("primary", ["templates"], "templates")],
    "agy": [("primary", ["plugins/pilotfish-agy/templates"], "plugins/pilotfish-agy/templates")],
    "grok": [("primary", ["plugins/pilotfish-grok/templates"], "plugins/pilotfish-grok/templates")],
    "opencode": [
        ("primary", ["roles"], ""),
        ("extra", [".opencode/pilotfish/catalog.json", ".opencode/pilotfish/routing.json"], ".opencode/pilotfish"),
    ],
}


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def write_golden(target: Path, files: dict[Path, bytes], records: list[str]) -> int:
    if target.exists():
        shutil.rmtree(target)
    for rel, data in files.items():
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        (target / rel).write_bytes(data)
    (target / "SOURCE").write_text("\n".join(records), encoding="utf-8")
    print(f"已匯入 {len(files)} 個檔案到 {target}")
    return 0


def import_from_dist(host: str, root: Path) -> tuple[dict[Path, bytes], str]:
    """讀 root 的 DIST_DIRS[host]，回傳 (檔案, SOURCE 內容)。ref 為 root 目前的 HEAD；
    dist 若有未 commit 的變更，記 dirty: true，代表 fixture 來自比 ref 更新的工作樹。"""
    dist = root / DIST_DIRS[host]
    commit = git(root, "rev-parse", "--verify", "HEAD").decode().strip()
    dirty = bool(git(root, "status", "--porcelain", "--", DIST_DIRS[host]).strip())
    files = {p.relative_to(dist): p.read_bytes() for p in sorted(dist.rglob("*")) if p.is_file()}
    record = f"repo: shoal\nref: shoal@{commit[:7]}\ncommit: {commit}\npath: {DIST_DIRS[host]}\ndirty: {str(dirty).lower()}\n"
    return files, record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", required=True, choices=sorted(SOURCES))
    parser.add_argument("--from", dest="repo", type=Path)
    parser.add_argument("--ref")
    parser.add_argument("--from-dist", action="store_true", help="從本 repo 的 dist 匯入（SOURCE 記 shoal@<sha>）")
    parser.add_argument("--extra-from", dest="extra_repo", type=Path, help="第二個來源 repo（opencode 的 dotfile）")
    parser.add_argument("--extra-ref")
    parser.add_argument("--root", type=Path, default=REPO, help="repo 根目錄（測試用）")
    args = parser.parse_args(argv)

    if args.from_dist:
        try:
            files, record = import_from_dist(args.host, args.root)
        except subprocess.CalledProcessError as exc:
            print(f"git 失敗: {exc.stderr.decode().strip()}", file=sys.stderr)
            return 2
        return write_golden(args.root / "tests" / "golden" / args.host, files, [record])
    if args.repo is None or args.ref is None:
        print("需要 --from 與 --ref，或改用 --from-dist", file=sys.stderr)
        return 2

    given = {"primary": (args.repo, args.ref), "extra": (args.extra_repo, args.extra_ref)}
    target = args.root / "tests" / "golden" / args.host
    files: dict[Path, bytes] = {}
    records = []
    try:
        for which, paths, strip in SOURCES[args.host]:
            repo, ref = given[which]
            if repo is None or ref is None:
                print(f"{args.host} 需要 --extra-from 與 --extra-ref", file=sys.stderr)
                return 2
            repo = repo.expanduser().resolve()
            commit = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
            archive = git(repo, "archive", commit, *paths)
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                for member in tar.getmembers():
                    if member.isfile():
                        rel = Path(member.name).relative_to(strip) if strip else Path(member.name)
                        files[rel] = tar.extractfile(member).read()
            records.append(f"repo: {repo}\nref: {ref}\ncommit: {commit}\npath: {' '.join(paths)}\n")
    except subprocess.CalledProcessError as exc:
        print(f"git 失敗: {exc.stderr.decode().strip()}", file=sys.stderr)
        return 2

    return write_golden(target, files, records)


if __name__ == "__main__":
    sys.exit(main())
