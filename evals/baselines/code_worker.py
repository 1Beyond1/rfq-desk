"""Child interpreter policy for cooperative benchmark code, not a hostile-code OS sandbox.

No project checkout, gold, credentials or model client is copied into this working dir.
Audit controls filesystem/network/process access; parent enforces wall time/output budget.
"""
import sys,os,json,math,decimal,statistics,itertools,collections,re,datetime,pathlib,builtins,io
import email.message,email.parser,email.policy,email.encoders,csv,html.parser,xml.etree.ElementTree,zipfile,base64,hashlib

root=pathlib.Path.cwd().resolve()
runtime=pathlib.Path(sys.base_prefix).resolve()
allowed_modules={'json','math','decimal','statistics','itertools','collections','re','datetime','pathlib','email','csv','html','xml','zipfile','base64','hashlib','io'}
original_import=builtins.__import__
def limited_import(name,*args,**kwargs):
    if name.split('.')[0] not in allowed_modules:raise PermissionError('Import denied: '+name)
    return original_import(name,*args,**kwargs)
def within(path,parent):
    try:path.relative_to(parent);return True
    except ValueError:return False
def audit(event,args):
    if event=='open':
        name,mode,flags=args
        if isinstance(name,int):return
        path=pathlib.Path(name).resolve()
        writing=bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if not within(path,root) and (writing or not within(path,runtime)):raise PermissionError('File access outside work directory denied')
    if event in ('os.mkdir','os.remove','os.rmdir','os.listdir','os.scandir'):
        if not within(pathlib.Path(args[0] or '.').resolve(),root):raise PermissionError('Directory access outside work directory denied')
    if event=='os.rename':
        if any(not within(pathlib.Path(p).resolve(),root) for p in args[:2]):raise PermissionError('Rename outside work directory denied')
    if event.startswith(('socket.','subprocess.','ctypes.','winreg.')) or event in ('os.system','os.exec','os.spawn','os.chdir','os.link','os.symlink'):
        raise PermissionError('Operation denied: '+event)
payload=json.loads(sys.stdin.read())
class CappedOutput:
    def __init__(self,target):self.target=target;self.written=0
    def write(self,text):
        self.written+=len(text.encode('utf-8'))
        if self.written>payload.get('output_limit',32000):raise ValueError('Output byte budget exceeded')
        return self.target.write(text)
    def flush(self):self.target.flush()
sys.stdout=CappedOutput(sys.stdout)
sys.stderr=CappedOutput(sys.stderr)
original_open=builtins.open
written_bytes=[0]
class CappedFile:
    def __init__(self,file):self.file=file
    def write(self,value):
        written_bytes[0]+=len(value.encode('utf-8') if isinstance(value,str) else value)
        if written_bytes[0]>1048576:raise ValueError('Scratch write byte budget exceeded')
        return self.file.write(value)
    def writelines(self,values):
        for value in values:self.write(value)
    def __enter__(self):return self
    def __exit__(self,*args):self.file.close()
    def __getattr__(self,name):return getattr(self.file,name)
def capped_open(file,mode='r',*args,**kwargs):
    result=original_open(file,mode,*args,**kwargs)
    return CappedFile(result) if any(m in str(mode) for m in 'wax+') else result
sys.addaudithook(audit)
builtins.open=capped_open
io.open=capped_open
builtins.__import__=limited_import
namespace={'__name__':'__main__','data':payload.get('data',{})}
try:exec(compile(payload['code'],'<agent-code>','exec'),namespace)
except BaseException as exc:
    print(json.dumps({'error':type(exc).__name__,'message':str(exc)}));sys.exit(2)
