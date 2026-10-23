"""Offline host-observer fixtures; never launches a game or edits guest state."""
import csv
import subprocess
import tempfile
import unittest
from pathlib import Path
from analyze_tm3_cycle_detail import parse, summarize, hist
ROOT=Path(__file__).resolve().parents[1]

def ledger(text):
    return [list(map(int,item.split(':'))) for item in text.split(';') if item]

class CycleDetailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='tm3_cycle_detail_');cls.root=Path(cls.tmp.name)
        cls.exe=cls.root/'fixtures.exe'
        subprocess.run([str(ROOT/'third_party/toolchains/winlibs-x86_64/mingw64/bin/gcc.exe'),
            str(ROOT/'diagnostics/cycle_detail_v1/test_observer.c'),'-Wall','-Wextra','-o',str(cls.exe)],check=True)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_modes(self):
        for mode in ('normal','changed','cap','disabled','existing'):
            with self.subTest(mode=mode):
                detail=self.root/(mode+'.csv');pace=self.root/(mode+'.pace.csv')
                subprocess.run([str(self.exe),mode,str(pace),str(detail)],check=True)
                if mode=='disabled':self.assertFalse(detail.exists());continue
                if mode=='existing':self.assertEqual(detail.read_text(),'KEEP');continue
                with detail.open() as stream:rows=list(csv.DictReader(stream))
                self.assertEqual(len(rows),1)
                r=rows[0];self.assertEqual(int(r['span_cycles']),105)
                self.assertEqual(r['valid'],'0' if mode=='changed' else '1')
                sums=[]
                for key in ('functions','classes','phases'):
                    entries=ledger(r[key]);sums.append([sum(e[i] for e in entries) for i in range(1,5)])
                self.assertEqual(sums,[[14,9,29,7]]*3)
                self.assertEqual(r['fast_calls'],'1');self.assertEqual(r['fallback_calls'],'1')
                self.assertEqual(r['rtpt_dispatches'],'1')
                self.assertEqual(r['tick'],'1200' if mode=='cap' else '1')
                if mode=='normal':
                    parsed=parse(detail.read_bytes())
                    report=summarize(parsed,[str(i) for i in range(1133)])
                    self.assertEqual(report['accounted_fetch_plus_execution'],38)
                    self.assertEqual(report['event_or_unaccounted_cycles'],67)
                    self.assertEqual(report['gte_wait_cycles_subset'],7)
                    self.assertEqual(report['callbacks_top_inclusive'][0]['calls'],1)
                    bad=dict(r);bad['render_pcs']='99999:1:0:0:0;'
                    import io
                    stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=bad)
                    writer.writeheader();writer.writerow(bad)
                    with self.assertRaisesRegex(ValueError,'out of range'):parse(stream.getvalue().encode())

    def test_reject_invalid_histograms(self):
        for value in ('1:2:3:4:5','1:2:3:4:0;1:2:3:4:0','-1:2:3:4:0'):
            with self.subTest(value=value),self.assertRaises(ValueError):hist(value)

if __name__=='__main__':unittest.main()
