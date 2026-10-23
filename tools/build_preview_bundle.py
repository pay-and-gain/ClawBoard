"""开发工具，不参与产品运行：构建固定七文件的公开重构预览包。

--check 只读取固定来源并输出计划；只有显式 --build 才创建新目录与 ZIP。
不导入产品、不扫描用户目录、不复制数据、不启动程序或执行安装。
失败可能保留 .partial 文件；只有完整验证后才生成最终 .zip 成品。
"""
import argparse
import ast
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import uuid
import zipfile


ROOT = Path(__file__).absolute().parents[1]
VERSION = '2.6.1'
BRANCH = 'refactor/services-and-responsiveness'
PUBLIC_NAMES = (
    'ClawBoard.exe', 'ClawBoard-2.6.1-refactor-preview-setup.exe',
    'LICENSE.txt', 'README.zh-CN.txt', 'README.en.txt',
    'BUILD-INFO.txt', 'SHA256SUMS.txt',
)
SOURCE_PATHS = {
    'ClawBoard.exe': 'dist/windows-validation/portable-17779fd3a1cb4925b39d302d76a7bec2/ClawBoard.exe',
    'ClawBoard-2.6.1-refactor-preview-setup.exe': (
        'dist/windows-validation/installer-noicons-8c7e0b0668dc4934901a05937adebd55/'
        'stage/release/ClawBoard-2.6.1-setup.exe'),
    'LICENSE.txt': 'LICENSE',
    'README.zh-CN.txt': 'packaging/preview/README.zh-CN.txt',
    'README.en.txt': 'packaging/preview/README.en.txt',
}
FIXED_SHA256 = {
    'ClawBoard.exe': '9ad6cc71ab1cb80f9283568cbe20efb098781ea0bb6f033b419ab17cccaea45b',
    'ClawBoard-2.6.1-refactor-preview-setup.exe': (
        '6ed12498f446272e6b35f2b701dfdf672bd942662836c95d0ec660a7b9a0302f'),
}


class BundleError(ValueError):
    pass


@dataclass(frozen=True)
class BundlePlan:
    root: Path
    revision: str
    output_dir: Path
    archive_name: str
    archive_root: str
    # (public filename, fixed source path, SHA256 at planning time)
    sources: tuple


def _reparse(info):
    return (stat.S_ISLNK(info.st_mode)
            or bool(getattr(info, 'st_file_attributes', 0) & 0x400))


def _plain_path(root, path, *, missing=False, file=False):
    """Check every existing component before following a path within the repo."""
    root, path = Path(root).absolute(), Path(path).absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise BundleError('path must stay inside this repository') from error
    if '..' in relative.parts:
        raise BundleError('parent traversal is not permitted')
    current = root
    for part in (None, *relative.parts):
        if part is not None:
            current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if missing:
                continue
            raise BundleError('required source is missing: ' + str(current))
        if _reparse(info):
            raise BundleError('symlink/reparse paths are not permitted: ' + str(current))
        if current != path and not stat.S_ISDIR(info.st_mode):
            raise BundleError('path parent is not a directory')
    if file and not stat.S_ISREG(path.lstat().st_mode):
        raise BundleError('source must be an ordinary file')
    return path


def _read_source(root, relative):
    path = _plain_path(root, root / relative, file=True)
    before = path.lstat()
    with path.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise BundleError('source identity changed while opening: ' + str(path))
        data = stream.read()
    # Recheck after opening too; no directory walk or fixture discovery is used.
    _plain_path(root, path, file=True)
    after = path.lstat()
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
        raise BundleError('source changed while reading: ' + str(path))
    return path, data


def _version(root):
    _, raw = _read_source(root, 'clawboard/config.py')
    tree = ast.parse(raw.decode('utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == 'APP_VER'
                for target in node.targets):
            version = ast.literal_eval(node.value)
            if version != VERSION:
                raise BundleError('candidate package requires APP_VER=' + VERSION)
            return version
    raise BundleError('APP_VER is missing')


def make_plan(root, revision):
    root = Path(root).absolute()
    if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-fA-F]{40}', revision):
        raise BundleError('--revision must be exactly 40 hexadecimal characters')
    revision = revision.lower()
    _version(root)
    if (set(SOURCE_PATHS) != set(PUBLIC_NAMES) - {'BUILD-INFO.txt', 'SHA256SUMS.txt'}
            or set(FIXED_SHA256) != set(PUBLIC_NAMES[:2])):
        raise BundleError('public source allowlist was changed unexpectedly')
    sources = []
    for name, relative in SOURCE_PATHS.items():
        path, data = _read_source(root, relative)
        digest = hashlib.sha256(data).hexdigest()
        if name in FIXED_SHA256 and digest != FIXED_SHA256[name]:
            raise BundleError('candidate SHA256 does not match: ' + name)
        sources.append((name, path, digest))
    destination = root / 'dist' / 'delivery'
    _plain_path(root, destination, missing=True)
    label = 'ClawBoard-%s-refactor-preview-%s' % (VERSION, revision[:12])
    output = destination / (label + '-' + uuid.uuid4().hex)
    if output.exists() or output.is_symlink():
        raise BundleError('output must be a unique new directory')
    return BundlePlan(root, revision, output, label + '.zip', label, tuple(sources))


def describe_plan(plan):
    return dict(mode='read-only-check', version=VERSION, official_release=False,
                source_revision=plan.revision, source_branch=BRANCH,
                output_directory=str(plan.output_dir), archive=plan.archive_name,
                public_files=list(PUBLIC_NAMES),
                sources=[dict(name=name, path=str(path), sha256=digest)
                         for name, path, digest in plan.sources],
                writes_performed=False)


def payload_bytes(plan):
    """Read only the five allowlisted files; build the two public text records."""
    _version(plan.root)
    payload = {}
    for name, path, expected in plan.sources:
        allowed = plan.root / SOURCE_PATHS[name]
        if path != allowed:
            raise BundleError('source path does not match the fixed allowlist')
        _, data = _read_source(plan.root, SOURCE_PATHS[name])
        if hashlib.sha256(data).hexdigest() != expected:
            raise BundleError('source changed after the plan was checked: ' + name)
        if name in FIXED_SHA256 and expected != FIXED_SHA256[name]:
            raise BundleError('candidate SHA256 no longer matches the fixed value')
        payload[name] = data
    info = (
        'ClawBoard %s - refactor-preview\n\n'
        'Application version: %s (unchanged)\n'
        'Source branch: %s\n'
        'Maintainer-supplied source revision: %s\n'
        'Review: https://github.com/pay-and-gain/ClawBoard/pull/1\n'
        'Status: evaluation package; no official Release and no main merge.\n\n'
        'Build tools: Python 3.14.5; Tcl/Tk 8.6; PyInstaller 6.22.3; Inno Setup 6.7.3.\n'
        'The binaries are the fixed, hash-verified Windows validation candidates.\n'
        'Portable launch, local-directory silent install, NO_SAVE startup and data-preserving uninstall passed.\n'
        'Interactive setup, GUI save/restart and virtual-machine installation are not certified.\n'
        'Only the seven named public files are included. User data, fixtures, backups and logs are excluded.\n'
    ) % (VERSION, VERSION, BRANCH, plan.revision)
    payload['BUILD-INFO.txt'] = info.encode('utf-8')
    payload['SHA256SUMS.txt'] = ''.join(
        hashlib.sha256(payload[name]).hexdigest() + '  ' + name + '\n'
        for name in PUBLIC_NAMES if name != 'SHA256SUMS.txt').encode('utf-8')
    if set(payload) != set(PUBLIC_NAMES):
        raise BundleError('payload must contain exactly the seven public files')
    return payload


def verify_archive(archive, plan, expected):
    """Verify the final ZIP without extracting it to disk."""
    names = {plan.archive_root + '/' + name for name in PUBLIC_NAMES}
    with zipfile.ZipFile(archive, 'r') as package:
        entries = package.infolist()
        if len(entries) != len(names) or {entry.filename for entry in entries} != names:
            raise BundleError('ZIP manifest differs from the seven-file allowlist')
        for entry in entries:
            relative = PurePosixPath(entry.filename)
            if (entry.is_dir() or relative.is_absolute() or '..' in relative.parts
                    or '\\' in entry.filename or stat.S_ISLNK(entry.external_attr >> 16)):
                raise BundleError('ZIP contains an unsafe member')
            name = relative.name
            if package.read(entry) != expected[name]:
                raise BundleError('ZIP content/hash mismatch: ' + name)


def _new_output(plan):
    base = plan.root / 'dist' / 'delivery'
    if plan.output_dir.parent != base or not plan.output_dir.name.startswith(plan.archive_root + '-'):
        raise BundleError('output must be a unique child of repository dist/delivery')
    _plain_path(plan.root, base, missing=True)
    for parent in (plan.root / 'dist', base):
        if not parent.exists():
            parent.mkdir()
        _plain_path(plan.root, parent)
        if not parent.is_dir():
            raise BundleError('output parent must be an ordinary directory')
    plan.output_dir.mkdir(exist_ok=False)
    _plain_path(plan.root, plan.output_dir)


def _publish_partial(plan, partial, archive):
    _plain_path(plan.root, partial, file=True)
    _plain_path(plan.root, archive, missing=True)
    if os.name == 'nt':
        # Windows rename is atomic and refuses an existing destination.
        os.rename(partial, archive)
    else:
        # POSIX rename overwrites, so publish exclusively via a same-directory link.
        os.link(partial, archive, follow_symlinks=False)
        try:
            partial.unlink()
        except OSError:
            # Publication succeeded; a leftover .partial is harmless and not a product.
            pass


def build_bundle(plan):
    # Recheck every source before making even the empty output directory.
    payload = payload_bytes(plan)
    _new_output(plan)
    archive = plan.output_dir / plan.archive_name
    partial = plan.output_dir / (plan.archive_name + '.' + uuid.uuid4().hex + '.partial')
    _plain_path(plan.root, archive, missing=True)
    _plain_path(plan.root, partial, missing=True)
    # Exclusive creation cannot replace an existing file, even if a plan is reused.
    with partial.open('xb') as stream:
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as package:
            for name in PUBLIC_NAMES:
                info = zipfile.ZipInfo(plan.archive_root + '/' + name, (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                package.writestr(info, payload[name])
    _plain_path(plan.root, partial, file=True)
    verify_archive(partial, plan, payload)
    digest = hashlib.sha256(partial.read_bytes()).hexdigest()
    _publish_partial(plan, partial, archive)
    return dict(archive=str(archive), sha256=digest,
                source_revision=plan.revision, version=VERSION, public_files=list(PUBLIC_NAMES))


def make_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check', action='store_true', help='read-only plan; writes no files')
    modes.add_argument('--build', action='store_true', help='write .partial; publish ZIP only after verification')
    parser.add_argument('--revision', required=True, help='full 40-hex source revision')
    return parser


def main(argv=None):
    args = make_parser().parse_args(argv)
    plan = make_plan(ROOT, args.revision)
    result = describe_plan(plan) if args.check else build_bundle(plan)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
