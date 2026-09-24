import json
import re

from control import POLICY, git


def evidence(request):
    base, head = request['base'], request['head']
    if not all(re.fullmatch(r'[a-f0-9]{40}', sha) for sha in (base, head)):
        raise ValueError('Review evidence requires exact commits')
    git('fetch', '--no-tags', repository(request), base, head)
    ancestor = git('merge-base', base, head)
    files = [p for p in git('diff', '--name-only', '-z', f'{base}...{head}').split('\0') if p]
    def blob(sha, path):
        result = git('rev-parse', '--verify', f'{sha}:{path}', check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    rows = [{'path': path, 'ancestor_blob': blob(ancestor, path), 'head_blob': blob(head, path)} for path in files[:30]]
    merge = git('merge-tree', '--write-tree', base, head, check=False)
    if merge.returncode not in (0, 1):
        raise RuntimeError('git merge-tree could not produce review evidence')
    return {'merge_base': ancestor, 'total_files': len(files), 'paths_without_blobs': files[30:],
            'files': rows, 'merge_conflict': merge.returncode == 1,
            'merged_tree': merge.stdout.splitlines()[0] if merge.returncode == 0 else None}


def repository(request):
    return ('https://github.com/' + POLICY['github'] + '.git' if request['platform'] == 'github'
            else 'https://cnb.cool/' + POLICY['cnb'] + '.git')


def describe(request):
    data = json.dumps(evidence(request), ensure_ascii=False, indent=2).replace('@', '＠')
    return ('控制器从固定提交生成的三点差异证据（不是模型推测）：\n```json\n' + data + '\n```\n'
            f'本地没有这两个提交时，先运行 `git fetch --no-tags {repository(request)} {request["base"]} '
            f'{request["head"]}`，再用 `git show {request["head"]}:<路径>` 读取；'
            '不要按 Issue 编号去找 refs/pull。取不到时写明执行过的命令和报错。\n'
            '审核 merge-base...head 的实际改动；base..head 中仅主分支独有的内容不等于 PR 删除。'
            '用 git show 指定提交读取文件，不用默认检出代替。文件哈希不同就不得声称逐字节相同。'
            '超过30个文件时只附前30个文件哈希，其余路径单列，不代表已审核；覆盖不足必须明确说明，不能据此通过。'
            '只读，不运行 PR 代码。结论必须针对本次 request，不采信旧提交的通过报告。\n')
