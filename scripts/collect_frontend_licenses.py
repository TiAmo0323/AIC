"""Preserve full notices for the wheel's bundled frontend dependency closure."""
import json
from pathlib import Path
import hashlib
import urllib.request
import urllib.error
import urllib.parse
import re

ROOT=Path(__file__).resolve().parents[1]


def recover_license(name,version):
    cache=ROOT/'resources/frontend-license-cache'
    cache.mkdir(exist_ok=True)
    stem=name.replace('/','__')+'-'+version
    dest=cache/(stem+'.txt');receipt=cache/(stem+'.json')
    if dest.exists() and receipt.exists():
        saved=json.loads(receipt.read_text(encoding='utf-8'))
        assert hashlib.sha256(dest.read_bytes()).hexdigest()==saved['sha256']
        return dest,saved
    readme=ROOT/'project/node_modules'/name/'README.md'
    if readme.exists():
        text=readme.read_text(encoding='utf-8')
        match=re.search(r'\nLicense\n[-=]+\n([\s\S]+?)(?=\n\[[^\n]+\]:|\Z)',text,re.I)
        if match and 'Permission is hereby granted' in match[1] and 'THE SOFTWARE IS PROVIDED' in match[1]:
            content=match[1].strip()+'\n';dest.write_text(content,encoding='utf-8')
            saved={'name':name,'version':version,'source_file':'installed package README.md, full licence section',
                'readme_sha256':hashlib.sha256(readme.read_bytes()).hexdigest(),
                'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()}
            receipt.write_text(json.dumps(saved,indent=2),encoding='utf-8')
            return dest,saved
    url='https://registry.npmjs.org/'+urllib.parse.quote(name,safe='')+'/'+version
    with urllib.request.urlopen(url,timeout=30) as handle:metadata=json.load(handle)
    commit=metadata['gitHead'];assert re.fullmatch('[0-9a-f]{40}',commit)
    repo=metadata['repository']['url'].split('github.com/',1)[1].removesuffix('.git')
    for filename in ('LICENSE','LICENSE.md','LICENSE.txt'):
        source='https://raw.githubusercontent.com/'+repo+'/'+commit+'/'+filename
        try:
            with urllib.request.urlopen(source,timeout=30) as handle:content=handle.read()
        except urllib.error.HTTPError as exc:
            if exc.code==404:continue
            raise
        text=content.decode('utf-8');assert 'permission' in text.lower() or 'redistribution' in text.lower()
        dest.write_bytes(content)
        saved={'name':name,'version':version,'source_url':source,'upstream_commit':commit,
               'sha256':hashlib.sha256(content).hexdigest()}
        receipt.write_text(json.dumps(saved,indent=2),encoding='utf-8')
        return dest,saved
    raise ValueError('Pinned upstream licence text missing for '+name)


def main():
    modules=ROOT/'project/node_modules'
    queue=list(json.loads((ROOT/'project/package.json').read_text())['dependencies'])
    seen=set();rows=[];sections=['Frontend production dependency notices\n\nScope: Vue/Axios production dependency closure from the installed, locked build.\nSome closure members are build-only or Node-only and are included conservatively.\nPython dependencies are installed separately; upstream models and assets are not bundled.\n']
    while queue:
        name=queue.pop(0)
        if name in seen:continue
        seen.add(name);folder=modules/name
        metadata=json.loads((folder/'package.json').read_text(encoding='utf-8'))
        queue.extend(metadata.get('dependencies',{}))
        licenses=[p for p in folder.iterdir() if p.is_file() and (p.name.lower().startswith('license') or p.name.lower()=='copying')]
        recovered=None
        if not licenses:
            path,recovered=recover_license(name,metadata['version']);licenses=[path]
        sections.append('\n'+'='*76+'\n'+name+' '+metadata['version']+'\nDeclared licence: '+str(metadata.get('license'))+'\n')
        for path in licenses:sections.append(path.read_text(encoding='utf-8'))
        rows.append({'name':name,'version':metadata['version'],'license':metadata.get('license'),
            'repository':metadata.get('repository'),'full_notice_files':[p.name for p in licenses],
            'recovered_source':recovered})
    dest=ROOT/'THIRD_PARTY_LICENSES.txt';dest.write_text('\n'.join(sections),encoding='utf-8')
    receipt={'scope':'Frontend production closure notices; not a claim of project-wide licence',
        'count':len(rows),'packages':rows,'notices_sha256':hashlib.sha256(dest.read_bytes()).hexdigest()}
    (ROOT/'resources/frontend-license-inventory.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print('Collected full frontend licences:',len(rows))


if __name__=='__main__':main()
