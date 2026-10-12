"""Self-contained local HTML; no network requests or third-party scripts."""
import html
import json
from pathlib import Path


def write_html(path, report, *, repair=None, comparison=None, manifest=None):
    report = report.to_dict() if hasattr(report, 'to_dict') else report
    payload = {'report': report, 'repair': repair, 'comparison': comparison, 'manifest': manifest}
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    rows = []
    for test in report['tests']:
        for issue in test['issues']:
            rows.append('<tr>' + ''.join(f'<td>{html.escape(str(x))}</td>' for x in (
                test['test_name'], issue.get('actor_id'), issue.get('joint_ids'),
                f"{issue['start_frame']}–{issue['end_frame']}", issue['metric'], issue['value'], issue['threshold'], issue['severity'])) + '</tr>')
    tests = ''.join(f"<tr><td>{html.escape(t['test_name'])}</td><td>{t['status']}</td><td>{t['score']}</td><td>{html.escape(t['metrics'].get('evaluation_status', 'legacy'))}</td></tr>" for t in report['tests'])
    content = '''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>MotionLint 质量报告</title>
<style>body{font:16px system-ui;max-width:1200px;margin:auto;padding:24px;color:#172436;background:#f4f7fb}table{border-collapse:collapse;background:white;width:100%;margin:16px 0}td,th{text-align:left;padding:9px;border:1px solid #dde3eb}pre{white-space:pre-wrap;overflow-wrap:anywhere}button{padding:8px}h1,h2{color:#133e68}.badge{background:#e0eafd;padding:10px}details{margin:18px 0}</style>
<h1>MotionLint 质量报告</h1><p class="badge">候选改善与整体达标分别判断。此报告可离线打开；真实动作未提供人工缺陷真值。</p>
<h2>六项检测</h2><table><tr><th>项目</th><th>状态</th><th>分数</th><th>覆盖</th></tr>__TESTS__</table>
<h2>问题区间</h2><table><tr><th>类型</th><th>人物</th><th>关节</th><th>帧区间</th><th>物理量</th><th>数值</th><th>阈值</th><th>严重度</th></tr>__ROWS__</table>
<details open><summary>来源与冻结上下文</summary><pre id="meta"></pre></details>
<details><summary>修复候选、拒绝理由和残余问题</summary><pre id="repair"></pre></details>
<details><summary>完整回归审查</summary><pre id="compare"></pre></details>
<details><summary>产物和哈希</summary><pre id="manifest"></pre></details><button id="download">下载本报告 JSON</button>
<script id="data" type="application/json">__DATA__</script><script>const p=JSON.parse(document.getElementById('data').textContent);for(const [id,v] of Object.entries({meta:p.report.metadata,repair:p.repair,compare:p.comparison,manifest:p.manifest}))document.getElementById(id).textContent=JSON.stringify(v,null,2);document.getElementById('download').onclick=()=>{const u=URL.createObjectURL(new Blob([JSON.stringify(p,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download='motionlint-report.json';a.click();URL.revokeObjectURL(u)};</script></html>'''
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.replace('__TESTS__', tests).replace('__ROWS__', ''.join(rows)).replace('__DATA__', data), encoding='utf-8')
    return path
