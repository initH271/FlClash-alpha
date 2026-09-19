import hashlib
import json
import pathlib
import re
import sys

from control import CNB, GH, POLICY, all_issues, api, comment, sign, verify
from security_scan import key

MARKER = 'flclash-security'


def record(issue):
    author = issue.get('author') or {}
    if author.get('username') != POLICY['approver'] or author.get('is_npc') is not False:
        return None
    match = re.search(r'<!-- flclash-security (\{[^\r\n]+\}) -->', issue.get('body', ''))
    if not match:
        return None
    try:
        return verify(json.loads(match[1]))
    except (ValueError, KeyError, TypeError):
        return None


def groups(report):
    result = {}
    for finding in report['findings']:
        group = result.setdefault(key(finding), [])
        if not any(set(f['aliases']) & set(finding['aliases']) and f['version'] == finding['version'] for f in group):
            group.append(finding)
    return result


def cnb_risks():
    risks = {}
    for page in range(1, 101):
        rows = api(f'{CNB}/code/issues?risk_level=all&page={page}&page_size=100')['list']
        for row in rows:
            if not row['rule'].startswith('VUL_'):
                continue
            detail = api(f'{CNB}/code/issues/{row["id"]}')
            if detail.get('state') != 'open':
                continue
            for alias in re.findall(r'CVE-\d{4}-\d+|GHSA-[a-z0-9-]+', detail.get('description', '')):
                risks[(row['file_path'], alias)] = row['risk_level']
        if len(rows) < 100:
            return risks
    raise ValueError('CNB findings pagination exceeded limit')


def monitor(report):
    if report.get('complete') is not True or report.get('schema') != 1:
        raise ValueError('Incomplete scan cannot create or close security work')
    if api(f'{GH}/git/ref/heads/main')['object']['sha'] != report['sha']:
        raise ValueError('Main changed after scanning; rerun before updating security Issues')
    active = groups(report)
    risks = cnb_risks()
    existing = {}
    for item in all_issues():
        issue = api(f'{CNB}/issues/{item["number"]}')
        payload = record(issue)
        if payload:
            existing[payload['key']] = (issue, payload)
    scanned = {key(p) for p in report['packages']}
    unknown = {key(p) for p in report['unscanned']}
    for identity, (issue, payload) in existing.items():
        if issue['state'] == 'open' and identity not in active and identity not in unknown:
            comment(issue['number'], f'当前 main `{report["sha"]}` 完整 OSV 复扫未再发现该依赖的已知漏洞。'
                    + ('已核对解析版本。' if identity in scanned else '该依赖已不在本次完整清单中。')
                    + '关闭跟踪记录；这不代表所有平台行为已经实测。')
            api(f'{CNB}/issues/{issue["number"]}', 'PATCH', {'state': 'closed', 'state_reason': 'completed'})
    def priority(entry):
        findings = entry[1]
        levels = [risks.get((f['file'], a), '') for f in findings for a in f['aliases']]
        return min([{'fatal': 0, 'error': 1, 'warning': 2, 'info': 3}.get(v, 4) for v in levels] or [4])
    dispatched, created = 0, 0
    for identity, findings in sorted(active.items(), key=priority):
        old = existing.get(identity)
        aliases = sorted({a for f in findings for a in f['aliases']})
        if old and old[0]['state'] == 'closed':
            continue
        if old:
            issue, payload = old
        else:
            if created >= 10:
                continue
            item = findings[0]
            payload = {'key': identity, 'file': item['file'], 'package': item['name'],
                       'ecosystem': item['ecosystem'], 'aliases': aliases}
            body = (f'当前提交 `{report["sha"]}` 的完整依赖复扫发现风险。\n\n'
                    f'依赖文件：`{item["file"]}`；组件：`{item["name"]}`。\n\n'
                    + '\n'.join(f'- {f["id"]}：版本 `{f["version"]}`；修复版本候选 '
                                f'`{", ".join(f["fixed"]) or "暂无"}`；{f["url"]}' for f in findings)
                    + '\n\n依赖命中不等于运行时可利用；需要核对 Go 实际调用路径、mihomo 本地替换、Rust 平台条件和公告。'
                    '仅允许兼容范围内最小修复 PR；无修复版本、跨大版本或兼容性不明时停止并说明。'
                    '不得忽略扫描告警、删除测试、修改签名/CI 权限、直接推 main、合并或发版。\n\n'
                    + '<!-- flclash-security ' + json.dumps(sign(payload)) + ' -->')
            issue = api(f'{CNB}/issues', 'POST', {'title': f'[安全修复] {item["name"]}：{item["file"]}',
                        'body': body, 'assignees': [POLICY['approver']], 'work_mode': False})
            created += 1
        revision = hashlib.sha256(json.dumps(aliases).encode()).hexdigest()[:16]
        marker = '<!-- security-work-requested ' + identity + ':' + revision + ' -->'
        from control import pages
        comments = list(pages(f'{CNB}/issues/{issue["number"]}/comments'))
        if dispatched < 2 and not any(marker in c.get('body', '')
                and c.get('author', {}).get('username') == POLICY['approver']
                and c.get('author', {}).get('is_npc') is False for c in comments):
            comment(issue['number'], marker + '\n\n'
                + f'本次复扫提交 `{report["sha"]}`；当前漏洞标识：{", ".join(aliases)}。\n\n'
                f'@{POLICY["cnb"]}(开发助手) 已授权你评估本 Issue 的公开依赖漏洞并尝试兼容范围内的最小修复。'
                f'从最新 main 创建 `security/fix-{identity[:12]}` 分支，先核对当前版本及官方公告。'
                'Go 用解析后的模块图和 govulncheck 核实调用路径；Rust 核对 Cargo.lock、平台条件及官方修复。'
                '不要直接照抄旧扫描版本。能安全修复则更新必要的依赖及锁文件，运行相关 Go/Rust 测试和复扫后提交 CNB PR，'
                'PR 使用清晰中文标题，关联本 Issue，列出验证证据和未验证项。不能安全修复则回复原因，不强行升级。'
                '修复 PR 会自动接受双模型审核；不自行合并或发布，不修改自动化/权限，不隐瞒或忽略告警，不重复编译 APK。', True)
            dispatched += 1
    print(f'Tracked {len(active)} dependency groups; started {dispatched} bounded repair tasks')


if __name__ == '__main__':
    monitor(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')))
