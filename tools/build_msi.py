"""Build a per-user MSI from the same verified release payload."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import uuid
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
NS='http://wixtoolset.org/schemas/v4/wxs'; UI='http://wixtoolset.org/schemas/v4/wxs/ui'
ET.register_namespace('',NS);ET.register_namespace('ui',UI)
def element(parent,tag,**attrs):return ET.SubElement(parent,'{'+NS+'}'+tag,{k:str(v) for k,v in attrs.items()})
def identifier(prefix,value):return prefix+hashlib.sha256(value.encode()).hexdigest()[:24]
def main():
 p=argparse.ArgumentParser();p.add_argument('--wix',type=Path,default=ROOT/'build/toolchain/wix/wix.exe');p.add_argument('--version',default=(ROOT/'VERSION').read_text().strip());p.add_argument('--output',type=Path);p.add_argument('--include-game',action='store_true');p.add_argument('--cmake',type=Path,default=Path(r'C:/Program Files/Microsoft Visual Studio/18/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe'));args=p.parse_args()
 payload=ROOT/'build/payload';work=ROOT/'build/msi';work.mkdir(parents=True,exist_ok=True)
 native=ROOT/'build/installer-native'
 subprocess.run([str(args.cmake),'--build',str(native),'--config','Release'],check=True) if (native/'CMakeCache.txt').exists() else None
 if not (native/'CMakeCache.txt').exists():
  subprocess.run([str(args.cmake),'-S',str(ROOT/'installer/native'),'-B',str(native),'-G','Visual Studio 18 2026','-A','x64'],check=True)
  subprocess.run([str(args.cmake),'--build',str(native),'--config','Release'],check=True)
 output=args.output or ROOT.parent/f'TM3Online-{args.version}-x64{"-Completo" if args.include_game else ""}.msi';output.parent.mkdir(parents=True,exist_ok=True)
 wix=ET.Element('{'+NS+'}Wix');package=element(wix,'Package',Name='TM3 Online',Manufacturer='NelsonUMG',Version=args.version,UpgradeCode='DC41DB35-71C6-4CCD-BBFA-10B3240C7E62',Scope='perUser',Language='3082',Codepage='1252')
 element(package,'Binary',Id='ModernFolderPicker',SourceFile=str(native/'Release/TM3InstallerUI.dll'))
 element(package,'CustomAction',Id='PickInstallFolder',BinaryRef='ModernFolderPicker',DllEntry='PickInstallFolder',Execute='immediate',Return='check')
 element(package,'MajorUpgrade',AllowSameVersionUpgrades='yes',DowngradeErrorMessage='Ya hay una versión más reciente instalada.')
 element(package,'MediaTemplate',EmbedCab='yes',CompressionLevel='medium')
 remembered=element(package,'Property',Id='INSTALLFOLDER',Secure='yes')
 element(remembered,'RegistrySearch',Id='PreviousInstallDirectory',Root='HKCU',Key='Software\\NelsonUMG\\TM3Online',Name='InstallDirectory',Type='raw')
 local=element(package,'StandardDirectory',Id='LocalAppDataFolder');programs=element(local,'Directory',Id='LocalPrograms',Name='Programs');install=element(programs,'Directory',Id='INSTALLFOLDER',Name='TM3Online')
 directories={'':install};feature=element(package,'Feature',Id='Main',Title='TM3 Online',Level='1')
 location=element(install,'Component',Id='RememberInstallDirectory',Guid='C1AF3B1E-4F4B-4DAA-BF90-64828E0B9B97')
 element(location,'RegistryValue',Root='HKCU',Key='Software\\NelsonUMG\\TM3Online',Name='InstallDirectory',Type='string',Value='[INSTALLFOLDER]',KeyPath='yes')
 element(feature,'ComponentRef',Id='RememberInstallDirectory')
 paths=[(path.relative_to(payload).as_posix(),path) for path in sorted(payload.rglob('*')) if path.is_file()]
 if args.include_game:
  for directory in ('runtime/game','runtime/system256'):
   for source in sorted((ROOT/directory).glob('*')):
    if source.suffix.lower() in ('.bin','.cue'):
     paths.append((source.relative_to(ROOT).as_posix(),source))
 paths.append(('runtime/TM3Console.ini',ROOT/'config/TM3Console.example.ini'))
 binaries={}
 for name,source in paths:
  parts=name.split('/')
  for depth in range(1,len(parts)):
   path='/'.join(parts[:depth]);parent='/'.join(parts[:depth-1])
   if path not in directories:directories[path]=element(directories[parent],'Directory',Id=identifier('D',path),Name=parts[depth-1])
  cid=identifier('C',name);attrs=dict(Id=cid,Guid=str(uuid.uuid5(uuid.NAMESPACE_URL,'https://tm3online.local/msi/'+name)).upper())
  if name.endswith('.ini'):attrs.update(Permanent='yes',NeverOverwrite='yes')
  component=element(directories['/'.join(parts[:-1])],'Component',**attrs)
  duplicate=None
  if source.suffix.lower()=='.bin':
   with source.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
   duplicate=binaries.get(digest)
   if not duplicate:binaries[digest]='LobbyExe' if name=='TM3Lobby.exe' else identifier('F',name)
  if duplicate:
   element(component,'CopyFile',Id=identifier('Copy',name),FileId=duplicate,DestinationDirectory=directories['/'.join(parts[:-1])].get('Id'),DestinationName=parts[-1])
  else: element(component,'File',Id='LobbyExe' if name=='TM3Lobby.exe' else identifier('F',name),Name=parts[-1],Source=str(source.resolve()))
  element(component,'RegistryValue',Root='HKCU',Key='Software/NelsonUMG/TM3Online/Installer'.replace('/','\\'),Name=cid,Type='integer',Value='1',KeyPath='yes')
  element(feature,'ComponentRef',Id=cid)
 for directory,name in (('DesktopFolder','TM3 Online'),('ProgramMenuFolder','TM3 Online')):
  standard=element(package,'StandardDirectory',Id=directory);cid=identifier('Shortcut',directory);component=element(standard,'Component',Id=cid,Guid=str(uuid.uuid5(uuid.NAMESPACE_URL,cid)).upper())
  element(component,'Shortcut',Id=cid+'Link',Name=name,Target='[INSTALLFOLDER]TM3Lobby.exe',WorkingDirectory='INSTALLFOLDER',Advertise='no')
  element(component,'RegistryValue',Root='HKCU',Key='Software\\NelsonUMG\\TM3Online\\Installer',Name=cid,Type='integer',Value='1',KeyPath='yes');element(feature,'ComponentRef',Id=cid)
 ET.SubElement(package,'{'+UI+'}WixUI',{'Id':'WixUI_InstallDir','InstallDirectory':'INSTALLFOLDER'})
 license_text=(ROOT/'LICENSE').read_text(encoding='utf-8')
 escaped=license_text.replace('\\','\\\\').replace('{','\\{').replace('}','\\}').replace('\n','\\par\n')
 license_file=work/'license.rtf';license_file.write_text('{\\rtf1\\ansi '+escaped+'}',encoding='ascii',errors='replace')
 element(package,'WixVariable',Id='WixUILicenseRtf',Value=str(license_file))
 source=work/'TM3Online.wxs';ET.ElementTree(wix).write(source,encoding='utf-8',xml_declaration=True)
 subprocess.run([str(args.wix.resolve()),'build',str(source),'-arch','x64','-pdb',str(work/'TM3Online.wixpdb'),'-ext','WixToolset.UI.wixext','-culture','es-es','-cc',str(work/'cabcache'),'-o',str(output.resolve())],check=True)
 subprocess.run(['powershell.exe','-NoProfile','-File',str(ROOT/'tools/patch_msi_picker.ps1'),'-Msi',str(output.resolve())],check=True)
 print(output)
if __name__=='__main__':main()
