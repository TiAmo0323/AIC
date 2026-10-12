"""Copy a verified Vite build into package data without installing Node for users."""
from pathlib import Path
import shutil
import re

root = Path(__file__).resolve().parents[1]
source = root / 'project/dist'
target = root / 'motionlint/static'
if not (source / 'index.html').exists():
    raise ValueError('Run npm ci and npm run build in project first')
target.mkdir(exist_ok=True)
old_files = {p.relative_to(target) for p in target.rglob('*') if p.is_file()}
new_files = {p.relative_to(source) for p in source.rglob('*') if p.is_file()
             and (p.relative_to(source).parts[0] == 'assets' or p.name in {'index.html', 'favicon.svg'})}
for rel in new_files:
    dest = target / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / rel, dest)
    if rel == Path('index.html'):
        content = dest.read_text(encoding='utf-8')
        content = re.sub(r'<link\s[^>]*https://fonts\.[^>]*>', '', content, flags=re.S)
        content = '\n'.join(line.rstrip() for line in content.splitlines()) + '\n'
        dest.write_text(content, encoding='utf-8')
for rel in old_files - new_files:
    checked = (target / rel).resolve()
    if not checked.is_relative_to(target.resolve()):
        raise ValueError('Invalid stale package asset')
    checked.unlink()
print('Workbench assets:', len(new_files))
