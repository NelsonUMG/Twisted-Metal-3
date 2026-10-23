import csv,io,subprocess,tempfile,unittest
from pathlib import Path
from analyze_tm3_link_boundary import analyze
ROOT=Path(__file__).resolve().parents[1]

class BoundaryTests(unittest.TestCase):
    def test_observer(self):
        with tempfile.TemporaryDirectory(prefix='tm3_boundary_') as tmp:
            exe=Path(tmp)/'test.exe'
            subprocess.run([str(ROOT/'third_party/toolchains/winlibs-x86_64/mingw64/bin/gcc.exe'),
                str(ROOT/'diagnostics/link_boundary_v1/test_observer.c'),'-Wall','-Wextra','-o',str(exe)],check=True)
            for mode in ('normal','changed','disabled','existing','cap'):
                with self.subTest(mode=mode):
                    out=Path(tmp)/(mode+'.csv');subprocess.run([str(exe),mode,str(out)],check=True)
                    if mode=='disabled':self.assertFalse(out.exists());continue
                    if mode=='existing':self.assertEqual(out.read_text(),'KEEP');continue
                    rows=list(csv.DictReader(io.StringIO(out.read_text())));self.assertEqual(len(rows),1)
                    self.assertEqual(rows[0]['valid'],'0' if mode=='changed' else '1')
                    self.assertEqual(rows[0]['tick'],'1200' if mode=='cap' else '1')

    def test_matching_brackets(self):
        header='tick,sequence,time_start,time_end,pop_start,pop_end,map_start,map_end,valid,v0,qpc_hz,publish_before,publish_after,ready_guest,resume_guest\n'
        guest=header+'1,100,42,42,8,8,4,4,1,1,1000000,100,120,300,310\n'
        host='LINK_DETECT seq=100 qpc=150 hz=1000000\nLINK_PUBLISH seq=100 before=250 after=270\n'
        r=analyze(guest,host);self.assertEqual(r['matched'],1)
        self.assertAlmostEqual(r['intervals'][0]['detect_delay_low_ms'],.03)
        self.assertAlmostEqual(r['intervals'][0]['resume_delay_high_ms'],.06)
        self.assertEqual(analyze(guest,host+host)['matched'],0)
        with self.assertRaises(ValueError):analyze(guest,host.replace('hz=1000000','hz=3'))

    def test_actual_publish_word(self):
        import struct
        blob=(ROOT/'diagnostics/sqrt_merge_v4/SCUS_942.49.sqrt_merge_v4').read_bytes()
        self.assertEqual(struct.unpack_from('<I',blob,0x800+0x80047AF0-0x80010000)[0],0xA50F0006)

if __name__=='__main__':unittest.main()
