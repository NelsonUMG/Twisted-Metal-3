"""Per-file release updates and recoverable file replacement."""
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

MANIFEST = 'TM3Online-update.json'
PROTECTED = {'userdata','saves','save','captures','memorycards','.git','assets'}

def destination(root, name):
    if not isinstance(name,str) or not name or '\\' in name or ':' in name:
        raise ValueError('Ruta inválida')
    parts=name.split('/')
    if any(p in ('','.','..') or p.endswith((' ','.')) or os.path.isreserved(p) for p in parts):
        raise ValueError('Ruta inválida')
    if parts[0].lower() in PROTECTED or name.lower().endswith(('.ini','.bin','.cue','.iso','.rom','.mcr','.srm')):
        raise ValueError('Archivo personal o juego excluido')
    root=Path(root).resolve(); target=root.joinpath(*parts)
    for candidate in (target,*target.parents):
        if candidate==root: break
        if candidate.is_symlink() or (hasattr(candidate,'is_junction') and candidate.is_junction()):
            raise ValueError('Enlace de archivos no permitido')
    if not target.resolve().is_relative_to(root): raise ValueError('Ruta fuera de instalación')
    return target

def sha(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()

def validate_manifest(manifest, root):
    if manifest.get('schema')!=1 or not isinstance(manifest.get('files'),list) or not 1<=len(manifest['files'])<=20000:
        raise ValueError('Manifiesto inválido')
    seen=set();total=0
    for item in manifest['files']:
        name=item['path'];destination(root,name)
        if name.casefold() in seen: raise ValueError('Archivo duplicado')
        seen.add(name.casefold())
        if not re.fullmatch('[0-9a-f]{64}',item['sha256']): raise ValueError('SHA256 inválido')
        if type(item['size']) is not int or not 0<=item['size']<=512*1024*1024: raise ValueError('Tamaño inválido')
        total+=item['size']
    if total>4*1024**3: raise ValueError('Actualización demasiado grande')
    if not {'tm3lobby.exe','tm3update.exe','version'}<=seen: raise ValueError('Faltan componentes de actualización')
    return manifest

def changed_files(manifest, root):
    validate_manifest(manifest,root)
    return [item for item in manifest['files'] if not (destination(root,item['path']).is_file() and destination(root,item['path']).stat().st_size==item['size'] and sha(destination(root,item['path']))==item['sha256'])]

def download_files(update, root, cache, progress=None, cancelled=None):
    from release_updater import download_installer
    manifest_asset=update['manifest']
    if progress: progress(0,manifest_asset['size'],MANIFEST)
    manifest_path=download_installer(manifest_asset,Path(cache)/'manifest',cancelled=cancelled)
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('version')!=update['version']: raise ValueError('Versión del manifiesto incorrecta')
    changed=changed_files(manifest,root);total=sum(i['size'] for i in changed)
    stage=Path(cache)/('stage-'+update['version']);stage.mkdir(parents=True,exist_ok=True)
    groups={}
    for item in changed: groups.setdefault(item['sha256'],[]).append(item)
    for digest,items in groups.items():
        asset=update['assets'].get('tm3-'+digest)
        if not asset or asset['sha256']!=digest or any(asset['size']!=i['size'] for i in items):
            raise ValueError('Asset no coincide con manifiesto')
    progress_lock=threading.Lock();active={};completed_bytes=0
    class Cancellation:
        def __init__(self): self.aborted=threading.Event()
        def is_set(self): return self.aborted.is_set() or bool(cancelled and cancelled.is_set())
        def wait(self,timeout):
            deadline=time.monotonic()+timeout
            while not self.is_set():
                remaining=deadline-time.monotonic()
                if remaining<=0: return False
                time.sleep(min(.1,remaining))
            return True
    cancel=Cancellation()
    def fetch(digest,items):
        nonlocal completed_bytes
        item=items[0];asset=update['assets']['tm3-'+digest]
        if progress:
            with progress_lock:
                active[digest]=0
                progress(completed_bytes+sum(active.values()),total,item['path'])
        def report(current,_size):
            if progress:
                with progress_lock:
                    active[digest]=current
                    progress(completed_bytes+sum(active.values()),total,item['path'])
        blob=download_installer(asset,stage/digest,report if progress else None,cancel)
        with progress_lock:
            completed_bytes+=asset['size']
            active.pop(digest,None)
            if progress: progress(completed_bytes+sum(active.values()),total,item['path'])
        return blob
    futures={}
    try:
        with ThreadPoolExecutor(max_workers=min(4,len(groups) or 1),
                                thread_name_prefix='tm3-update') as executor:
            for digest,items in groups.items():
                futures[executor.submit(fetch,digest,items)]=(digest,items)
            try:
                for future in as_completed(futures):
                    digest,items=futures[future]
                    blob=future.result()
                    for item in items: item['staged']=str(blob.resolve())
            except BaseException:
                cancel.aborted.set()
                for future in futures: future.cancel()
                raise
    except BaseException:
        cancel.aborted.set()
        raise
    # Always stage the tiny standalone helper, even when its installed version is unchanged.
    helper=next(i for i in manifest['files'] if i['path']=='TM3Update.exe')
    helper_item=next((i for i in changed if i['path']=='TM3Update.exe'),None)
    helper_path=Path(helper_item['staged']) if helper_item else destination(root,'TM3Update.exe')
    if sha(helper_path)!=helper['sha256']: raise ValueError('Aplicador alterado')
    executable=stage/'TM3Update.exe';shutil.copy2(helper_path,executable)
    plan=dict(root=str(Path(root).resolve()),files=changed,version=update['version'])
    plan_path=stage/'plan.json';plan_path.write_text(json.dumps(plan),encoding='utf-8')
    return dict(plan=str(plan_path.resolve()),helper=str(executable.resolve()),files=[i['path'] for i in changed],helper_sha256=helper['sha256'])

def apply_plan(plan, work):
    root=Path(plan['root']).resolve();items=plan['files'];seen=set()
    for item in items:
        name=item['path'];destination(root,name)
        if name.casefold() in seen: raise ValueError('Archivo duplicado')
        seen.add(name.casefold())
        source=Path(item['staged'])
        if source.stat().st_size!=item['size'] or sha(source)!=item['sha256']: raise ValueError('Descarga alterada')
    backups=Path(work)/'rollback'
    record=Path(work)/'transaction.json'
    if record.exists():
        recovery=json.loads(record.read_text(encoding='utf-8'))
        if recovery['root']!=str(root): raise ValueError('Transacción de otra instalación')
        for entry in reversed(recovery['entries']):
            target=destination(root,entry['path'])
            backup=backups/str(entry['index'])
            if entry['existed']:
                if not backup.is_file(): raise RuntimeError('Falta copia de recuperación')
                if not target.is_file() or sha(target)!=sha(backup): shutil.copy2(backup,target)
            else: target.unlink(missing_ok=True)
            target.with_name(target.name+'.tm3-update').unlink(missing_ok=True)
        record.unlink();shutil.rmtree(backups)
    if backups.exists(): shutil.rmtree(backups)
    backups.mkdir(parents=True,exist_ok=False)
    recovery=dict(root=str(root),entries=[])
    journal=[]
    try:
        for n,item in enumerate(sorted(items,key=lambda i:i['path']=='VERSION')):
            target=destination(root,item['path']);target.parent.mkdir(parents=True,exist_ok=True)
            backup=backups/str(n) if target.exists() else None
            if backup: shutil.copy2(target,backup)
            temporary=target.with_name(target.name+'.tm3-update')
            recovery['entries'].append(dict(path=item['path'],index=n,existed=backup is not None))
            record_temp=record.with_suffix('.tmp')
            record_temp.write_text(json.dumps(recovery),encoding='utf-8');os.replace(record_temp,record)
            journal.append((target,backup,temporary))
            shutil.copy2(item['staged'],temporary)
            if sha(temporary)!=item['sha256']: raise ValueError('Fallo al escribir archivo actualizado')
            os.replace(temporary,target)
    except BaseException:
        for target,backup,temporary in reversed(journal):
            if backup:
                if not target.is_file() or sha(target)!=sha(backup): shutil.copy2(backup,target)
            else: target.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)
        record.unlink(missing_ok=True);shutil.rmtree(backups)
        raise
    else:
        record.unlink(missing_ok=True);shutil.rmtree(backups)

def launch_apply(result):
    if sha(result['helper'])!=result['helper_sha256']: raise ValueError('Aplicador alterado')
    return subprocess.Popen([result['helper'],'--plan',result['plan'],'--wait-pid',str(os.getpid())],shell=False)

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--plan',required=True);parser.add_argument('--wait-pid',type=int,required=True);args=parser.parse_args()
    work=Path(args.plan).resolve().parent
    try:
        import ctypes as C
        kernel=C.windll.kernel32;kernel.OpenProcess.restype=C.c_void_p
        kernel.WaitForSingleObject.argtypes=[C.c_void_p,C.c_uint];kernel.CloseHandle.argtypes=[C.c_void_p]
        handle=kernel.OpenProcess(0x100000,False,args.wait_pid)
        if handle:
            try:
                if kernel.WaitForSingleObject(handle,60000)!=0: raise TimeoutError('El emulador no cerró')
            finally:kernel.CloseHandle(handle)
        plan=json.loads(Path(args.plan).read_text(encoding='utf-8'));apply_plan(plan,work)
        subprocess.Popen([str(Path(plan['root'])/'TM3Lobby.exe')],cwd=plan['root'],shell=False)
    except Exception as exc:
        (work/'update-error.txt').write_text(str(exc),encoding='utf-8')
        import ctypes as C
        C.windll.user32.MessageBoxW(None,str(exc),'No se pudo actualizar TM3 Online',0x10)
        return 1
    return 0

if __name__=='__main__':sys.exit(main())
