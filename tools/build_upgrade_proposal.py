"""开发工具，不参与产品运行：将升级提案生成离线单页和私有研究交付包。"""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/plans/v3-upgrade'
RESEARCH = ROOT / '_archive/upgrade-research-20261025'
REPORTS = ('windows-market.md', 'mac-patterns.md', 'current-capabilities.md',
           'blank-slate-ideas.md', 'idea-screening.md', 'decision-rubric.md',
           'prototype-review.md', 'RESEARCH_OVERVIEW.md', 'VALIDATION.md')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    created = datetime.now(timezone(timedelta(hours=8)))
    output = RESEARCH / 'deliverables' / (
        'r1-' + created.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
    html = (SOURCE / 'index.html').read_text(encoding='utf-8')
    css = (SOURCE / 'prototype.css').read_text(encoding='utf-8')
    js = (SOURCE / 'prototype.js').read_text(encoding='utf-8')
    for image in sorted(SOURCE.glob('icon-*.svg')):
        uri = 'data:image/svg+xml;base64,' + base64.b64encode(image.read_bytes()).decode()
        html, js = html.replace(image.name, uri), js.replace(image.name, uri)
    html = html.replace('<link rel="stylesheet" href="prototype.css">', '<style>' + css + '</style>')
    html = html.replace('<script src="prototype.js" defer></script>', '')
    # Inline scripts run after their DOM exists, just as the source's defer did.
    html = html.replace('</body>', '<script>' + js + '</script></body>')
    assert '<script src=' not in html and 'href="prototype.css"' not in html
    files = {'ClawBoard-升级方案-离线预览.html': html.encode('utf-8')}
    for source in sorted(SOURCE.iterdir()):
        if source.is_file():
            files['proposal/' + source.name] = source.read_bytes()
    for name in REPORTS:
        files['research/' + name] = (RESEARCH / name).read_bytes()
    for image in sorted(RESEARCH.glob('preview-*.png')):
        files['previews/' + image.name] = image.read_bytes()
    readme = ('ClawBoard 大版本升级提案 R1\n\n'
              '双击同层的“ClawBoard-升级方案-离线预览.html”即可查看，不需要启动服务器。\n'
              'proposal/PLAN.md 是主方案，research/ 含14项官方产品调研、15项独立脑暴和筛选。\n'
              '页面全部为合成数据，未接入系统剪贴板。浏览器选项可持久化，正式产品的新功能尚未实施。\n'
              '该包含内部竞品研究，按项目规则仅本机留存，不上传公开Git。\n')
    files['先看这里.txt'] = readme.encode('utf-8')
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True,
                              capture_output=True, text=True).stdout.strip()
    branch = subprocess.run(['git', 'branch', '--show-current'], cwd=ROOT, check=True,
                            capture_output=True, text=True).stdout.strip()
    manifest = dict(format=1, revision='proposal-r1', created_at=created.isoformat(),
                    source_commit=revision, branch=branch, stage='proposal-not-released',
                    files={name: dict(size=len(data), sha256=sha(data)) for name, data in files.items()})
    encoded_manifest = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    files['MANIFEST.json'] = encoded_manifest
    output.mkdir(parents=True, exist_ok=False)
    offline = output / 'ClawBoard-升级方案-离线预览.html'
    offline.write_bytes(files[offline.name])
    (output / 'MANIFEST.json').write_bytes(encoded_manifest)
    archive = output / 'ClawBoard-大版本升级提案-R1.zip'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert set(bundle.namelist()) == set(files)
        for name, data in files.items():
            assert sha(bundle.read(name)) == sha(data), name
    result = dict(directory=str(output), offline_preview=str(offline), archive=str(archive),
                  archive_sha256=sha(archive.read_bytes()), source_commit=revision,
                  file_count=len(files), verified=True)
    (RESEARCH / 'LATEST_DELIVERY.json').write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                                 encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
