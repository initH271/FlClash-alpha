import json
import pathlib
import re
import sys

from control import CNB, GH, POLICY, all_issues, api, comment, sign, verify
from security_scan import key
from security_groups import GROUPS, group_for, payload_for

def record(issue):
    author = issue.get('author') or {}
    if author.get('username') != POLICY['approver'] or author.get('is_npc') is not False:
        return None
    match = re.search(r'<!-- flclash-security(?:-group)? (\{[^\r\n]+\}) -->', issue.get('body', ''))
    if not match:
        return None
    try:
        return verify(json.loads(match[1]))
    except (ValueError, KeyError, TypeError):
        return None


def groups(report):
    result = {}
    for finding in report['findings']:
        group = result.setdefault(group_for(finding), [])
        if not any(key(f) == key(finding) and set(f['aliases']) & set(finding['aliases'])
                   and f['version'] == finding['version'] for f in group):
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


def scan_history(previous, findings, unscanned):
    unknown = {key(p) for p in unscanned}
    fields = ('file', 'name', 'ecosystem', 'id', 'aliases', 'version', 'fixed', 'url')
    rows = [dict({k: f[k] for k in fields}, state='待评估（扫描命中）') for f in findings]
    for old in previous:
        if any(key(old) == key(f) and set(old['aliases']) & set(f['aliases']) for f in findings):
            continue
        rows.append(dict({k: old[k] for k in fields},
                         state='待核实（无索引替换）' if key(old) in unknown else '复扫未命中'))
    return rows


def snapshot_body(issue, payload, report):
    rows = payload['history']
    table = '| 组件 | 漏洞 | 扫描状态 | 修复版本候选 |\n|---|---|---|---|\n'
    table += '\n'.join(f'| `{f["name"]}` | [{f["id"]}]({f["url"]}) | {f["state"]} | '
                       f'{", ".join(f["fixed"]) or "暂无"} |' for f in rows)
    block = (f'<!-- security-snapshot:start -->\n当前复扫提交：`{report["sha"]}`。'
             '扫描命中不等于可利用；不可达、暂无修复和待确认项须逐条给证据。\n\n'
             + table + '\n<!-- security-snapshot:end -->')
    body = issue.get('body', '')
    if '<!-- security-snapshot:start -->' in body:
        body = re.sub(r'<!-- security-snapshot:start -->.*?<!-- security-snapshot:end -->',
                      lambda _: block, body, flags=re.S)
    else:
        body += '\n\n' + block
    body = re.sub(r'<!-- flclash-security-group .*? -->', '', body)
    envelope = json.dumps(sign(payload)).replace('<', r'\u003c').replace('>', r'\u003e')
    return body.rstrip() + '\n\n<!-- flclash-security-group ' + envelope + ' -->'


def migrate_legacy(legacy, parents):
    for issue, payload in legacy:
        slug = group_for(payload)
        if slug not in parents or issue['state'] != 'open':
            continue
        parent = parents[slug]
        comment(issue['number'], f'已归并到统一任务 #{parent}：https://cnb.cool/{POLICY["cnb"]}/-/issues/{parent}。'
                '原漏洞、讨论和证据保留；此记录因归并关闭，不表示漏洞已修复。')
        api(f'{CNB}/issues/{issue["number"]}', 'PATCH', {'state': 'closed', 'state_reason': 'not_planned'})


def unresolved_group(payload, report):
    return (any(row['state'] != '复扫未命中' for row in payload['history'])
            or bool(set(payload.get('component_keys', [])) & {key(p) for p in report['unscanned']}))


def active_developer(issue, comments):
    state = None
    for item in [issue] + sorted(comments, key=lambda c: (c.get('created_at', ''), int(c['id']))):
        for entry in (item.get('statuses') or {}).get('npc', []):
            context = entry.get('context') or {}
            if context.get('npc.slug') == POLICY['cnb'] and context.get('npc.name') == '开发助手':
                statuses = entry.get('statuses') or []
                if statuses:
                    state = statuses[-1].get('state')
    return state is not None and state not in ('success', 'error', 'failure', 'cancel', 'cancelled')


def monitor(report):
    if report.get('complete') is not True or report.get('schema') != 1:
        raise ValueError('Incomplete scan cannot update security tasks')
    if api(f'{GH}/git/ref/heads/main')['object']['sha'] != report['sha']:
        raise ValueError('Main changed after scanning; rerun before updating security Issues')
    active, existing, legacy = groups(report), {}, []
    risks = cnb_risks()
    for item in all_issues():
        issue = api(f'{CNB}/issues/{item["number"]}')
        payload = record(issue)
        if not payload:
            continue
        if payload.get('group') in GROUPS:
            current = existing.get(payload['group'])
            rank = lambda i: (i['state'] == 'open', int(i['number']))
            if not current or rank(issue) > rank(current[0]):
                existing[payload['group']] = (issue, payload)
        else:
            legacy.append((issue, payload))
    parents = {}
    def priority(entry):
        findings = active.get(entry[0], [])
        levels = [{'fatal': 0, 'error': 1, 'warning': 2, 'info': 3}.get(risks.get((f['file'], a)), 4)
                  for f in findings for a in f['aliases']]
        levels += [{'CRITICAL': 0, 'HIGH': 1, 'MODERATE': 2, 'MEDIUM': 2, 'LOW': 3}.get(
            str(f.get('severity', '')).upper(), 4) for f in findings]
        return min(levels or [5])
    for slug, (title, path, _) in sorted(GROUPS.items(), key=priority):
        findings = active.get(slug, [])
        old = existing.get(slug)
        if not old and not findings:
            continue
        if old:
            issue, payload = old
            parents[slug] = issue['number']
            if issue['state'] == 'closed' and not (payload.get('auto_resolved') and issue.get('state_reason') == 'completed'):
                continue
        else:
            payload = payload_for(slug)
            links = '\n'.join(f'- 原记录 #{i["number"]}：https://cnb.cool/{POLICY["cnb"]}/-/issues/{i["number"]}'
                              for i, p in legacy if group_for(p) == slug)
            body = f'统一处理 `{path}` 的相关依赖，一组一个开发任务和修复分支。\n\n{links}\n\n'
            body += '允许有证据的部分修复，剩余漏洞逐条保留，不忽略告警、不自行合并或发布。'
            issue = {'body': body}
            payload['history'] = scan_history([], findings, report['unscanned'])
            issue = api(f'{CNB}/issues', 'POST', {'title': '[安全修复] ' + title,
                        'body': snapshot_body(issue, payload, report),
                        'assignees': [POLICY['approver']], 'work_mode': False})
        parents[slug] = issue['number']
        for member, data in legacy:
            url = f'https://cnb.cool/{POLICY["cnb"]}/-/issues/{member["number"]}'
            if group_for(data) == slug and not re.search(re.escape(url) + r'(?!\d)', issue['body']):
                issue['body'] += f'\n- 归并原记录 #{member["number"]}：{url}'
        payload['component_keys'] = sorted(set(payload.get('component_keys', []))
            | {p['key'] for _, p in legacy if group_for(p) == slug} | {key(f) for f in findings})
        payload['history'] = scan_history(payload.get('history', []), findings, report['unscanned'])
        unresolved = unresolved_group(payload, report)
        payload['auto_resolved'] = not unresolved
        update = {'body': snapshot_body(issue, payload, report)}
        if not unresolved:
            update.update(state='closed', state_reason='completed')
        elif issue['state'] == 'closed':
            update.update(state='open', state_reason='reopened')
        if any(issue.get(k) != v for k, v in update.items()):
            api(f'{CNB}/issues/{issue["number"]}', 'PATCH', update)
    migrate_legacy(legacy, parents)
    from security_queue import reconcile
    reconcile()
    print(f'Tracked {len(parents)} repair groups; reconciled worker queue')


if __name__ == '__main__':
    monitor(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')))
