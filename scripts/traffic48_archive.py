#!/usr/bin/env python3
"""Lossless, bounded-memory tar.zst parts with a per-file SHA256 inventory."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

CHUNK = 1024 * 1024
PART = 48 * CHUNK

def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(CHUNK), b''): h.update(b)
    return h.hexdigest()

def pack(root, output, sources):
    output.mkdir(parents=True, exist_ok=True)
    if list(output.glob('raw.tar.zst.part-*')): raise ValueError('archive already exists')
    paths = sorted(p for s in sources for p in (root/s).rglob('*') if p.is_file())
    if not paths: raise ValueError('no input files')
    if any(p.is_symlink() for p in paths): raise ValueError('symlinks are not supported')
    files = [{'path':str(p.relative_to(root)), 'bytes':p.stat().st_size, 'sha256':sha(p)} for p in paths]
    # Split subprocess drains zstd concurrently, with no archive buffered in RAM.
    split = subprocess.Popen(['split','-b',str(PART),'-d','-a','3','-',str(output/'raw.tar.zst.part-')], stdin=subprocess.PIPE)
    zstd = subprocess.Popen(['zstd','-q','-T2','-6','-c'], stdin=subprocess.PIPE, stdout=split.stdin)
    split.stdin.close()
    with tarfile.open(fileobj=zstd.stdin, mode='w|', format=tarfile.PAX_FORMAT) as tar:
        for p in paths:
            info = tar.gettarinfo(str(p), str(p.relative_to(root)))
            info.uid=info.gid=0; info.uname=info.gname=''; info.mtime=0; info.mode=0o644
            with open(p,'rb') as f: tar.addfile(info,f)
    zstd.stdin.close()
    if zstd.wait() or split.wait(): raise RuntimeError('compression failed')
    parts = [{'path':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(output.glob('raw.tar.zst.part-*'))]
    manifest = dict(format='tar.zst split at 48 MiB', sources=sources, files=files, parts=parts,
                    file_count=len(files), raw_bytes=sum(f['bytes'] for f in files), compressed_bytes=sum(f['bytes'] for f in parts))
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('files','parts')}),flush=True)

def verify(archive, destination=None):
    manifest=json.loads((archive/'manifest.json').read_text())
    expected={f['path']:f for f in manifest['files']}
    if len(expected)!=len(manifest['files']): raise ValueError('duplicate manifest paths')
    parts=[]
    for part in manifest['parts']:
        if Path(part['path']).name != part['path']: raise ValueError('unsafe part name')
        path=archive/part['path']
        if path.stat().st_size!=part['bytes'] or sha(path)!=part['sha256']: raise ValueError('part checksum mismatch')
        parts.append(str(path))
    if destination:
        destination.mkdir(parents=True,exist_ok=True)
        if any(destination.iterdir()): raise ValueError('restore destination must be empty')
    cat=subprocess.Popen(['cat',*parts],stdout=subprocess.PIPE)
    zstd=subprocess.Popen(['zstd','-q','-d','-c'],stdin=cat.stdout,stdout=subprocess.PIPE)
    cat.stdout.close()
    seen=set()
    try:
        with tarfile.open(fileobj=zstd.stdout,mode='r|') as tar:
            for entry in tar:
                path=PurePosixPath(entry.name)
                if not entry.isfile() or path.is_absolute() or '..' in path.parts or entry.name not in expected or entry.name in seen:
                    raise ValueError('unsafe or unexpected tar member')
                h=hashlib.sha256(); count=0; out=None
                if destination:
                    target=destination/entry.name; target.parent.mkdir(parents=True,exist_ok=True); out=target.open('xb')
                try:
                    with tar.extractfile(entry) as f:
                        for b in iter(lambda:f.read(CHUNK),b''):
                            h.update(b);count+=len(b)
                            if out: out.write(b)
                finally:
                    if out: out.close()
                item=expected[entry.name]
                if count!=item['bytes'] or h.hexdigest()!=item['sha256']: raise ValueError('file checksum mismatch: '+entry.name)
                seen.add(entry.name)
        # Drain tar padding so both subprocess exit statuses remain meaningful.
        while zstd.stdout.read(CHUNK): pass
        if zstd.wait() or cat.wait(): raise ValueError('decompression failed')
    finally:
        for proc in [zstd,cat]:
            if proc.poll() is None: proc.terminate()
            proc.wait()
    if seen!=set(expected): raise ValueError('missing files')
    print(json.dumps(dict(verified_files=len(seen),verified_bytes=manifest['raw_bytes'],parts=len(parts),restored=bool(destination))))

def main():
    p=argparse.ArgumentParser(); s=p.add_subparsers(dest='cmd',required=True)
    a=s.add_parser('pack');a.add_argument('--root',type=Path,required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('sources',nargs='+')
    a=s.add_parser('verify');a.add_argument('archive',type=Path)
    a=s.add_parser('restore');a.add_argument('archive',type=Path);a.add_argument('destination',type=Path)
    a=p.parse_args()
    if a.cmd=='pack':pack(a.root,a.output,a.sources)
    else:verify(a.archive,getattr(a,'destination',None))
if __name__=='__main__':main()
