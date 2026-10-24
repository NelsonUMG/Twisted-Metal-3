"""Bundle one MSI plus its English UI transform behind a language selector."""
import argparse,hashlib,shutil,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def digest(path):
 with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').digest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--msi',type=Path,default=ROOT/'build/msi/TM3Online-es.msi');p.add_argument('--transform',type=Path,default=ROOT/'build/msi/English.mst');p.add_argument('--output',type=Path,default=ROOT.parent/f'TM3Online-{(ROOT/"VERSION").read_text().strip()}-Setup.exe');args=p.parse_args()
 stub=ROOT/'build/installer-native/Release/TM3SetupLauncher.exe'
 with args.output.open('wb') as out:
  with stub.open('rb') as source:shutil.copyfileobj(source,out)
  offset=out.tell()
  with args.msi.open('rb') as source:shutil.copyfileobj(source,out)
  transform_offset=out.tell()
  with args.transform.open('rb') as source:shutil.copyfileobj(source,out)
  out.write(struct.pack('<8sQQQQ32s32s',b'TM3SET01',offset,args.msi.stat().st_size,transform_offset,args.transform.stat().st_size,digest(args.msi),digest(args.transform)))
 checksum=digest(args.output).hex();Path(str(args.output)+'.sha256').write_text(checksum+'  '+args.output.name+'\n',encoding='ascii');print(args.output)
if __name__=='__main__':main()
