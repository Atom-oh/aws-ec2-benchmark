import copy
from pathlib import Path
import sys
import unittest
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from traffic48_report import qualify,pool,compare,COUNTS,BASE
from traffic48_archive import pack, verify

class Statistics(unittest.TestCase):
    def row(self,hist=None):
        return dict(**{k:0 for k in COUNTS},seconds=60,histogram=hist or {},valid=True,qualification={'qualified':True},memory_gc={})
    def idle(self):
        boost=dict(**{k:0 for k in COUNTS},histogram={},expected_offered=0)
        row={'validation_errors':['boost: incomplete boost sample coverage'],'sources':{'boost':boost,'base':{'accounting_valid':True}}}
        schedule={'duration_seconds':60,'rate_rps':0,'from_rate_rps':0,'ramp_seconds':0}
        quality={'sources':{s:{'outcome':'COMPLETE','accounting_errors':[],'validation_errors':[]} for s in ['base','boost']}}
        return row,schedule,quality
    def test_only_true_idle_coverage_is_waived(self):
        row,schedule,quality=self.idle();before=copy.deepcopy(row)
        self.assertTrue(qualify(row,schedule,quality)['qualified']);self.assertEqual(row,before)
        row['validation_errors'].insert(0,'dispatch lag >25ms')
        self.assertEqual(qualify(row,schedule,quality)['remaining_errors'],['dispatch lag >25ms'])
    def test_exit_ramp_is_not_idle(self):
        row,schedule,quality=self.idle();schedule.update(from_rate_rps=100,ramp_seconds=60)
        self.assertFalse(qualify(row,schedule,quality)['qualified'])
    def test_incomplete_or_nonzero_source_not_waived(self):
        for field in COUNTS:
            row,schedule,quality=self.idle();row['sources']['boost'][field]=1
            self.assertFalse(qualify(row,schedule,quality)['qualified'])
        row,schedule,quality=self.idle();quality['sources']['boost']['accounting_errors']=['missing']
        self.assertFalse(qualify(row,schedule,quality)['qualified'])
    def test_pooled_p99_weights_requests_not_phases(self):
        a=self.row({'1':999});b=self.row({'1000':1})
        for r in [a,b]:r.update(offered=sum(r['histogram'].values()),success=sum(r['histogram'].values()),completed=sum(r['histogram'].values()))
        result=pool([a,b]);self.assertEqual(result['p99_ms'],.001);self.assertEqual(result['success_rps'],1000/120)
    def test_matched_intersection_not_separate_subsets(self):
        a=self.row({'1':100});a.update(offered=100,success=100,completed=100)
        bad=copy.deepcopy(a);bad['valid']=False;bad['qualification']['qualified']=False
        p=[{'name':'first','instances':{BASE:a,'other':bad}},{'name':'second','instances':{BASE:bad,'other':a}}]
        self.assertIsNone(compare(p,'other','strict')['target'])
        self.assertEqual(compare(p,'other','observed')['target']['phases'],2)

class Archive(unittest.TestCase):
    def test_restore_and_reject_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.mkdir()
            raw=b'complete raw data\x00\xff\n'*500
            (source/'raw.bin').write_bytes(raw)
            archive=root/'archive';destination=root/'restored'
            pack(root,archive,['source'])
            verify(archive,destination)
            self.assertEqual((destination/'source/raw.bin').read_bytes(),raw)
            with self.assertRaisesRegex(ValueError,'empty'):verify(archive,destination)
            part=next(archive.glob('raw.tar.zst.part-*'))
            data=bytearray(part.read_bytes());data[-1]^=1;part.write_bytes(data)
            with self.assertRaisesRegex(ValueError,'checksum'):verify(archive)

if __name__=='__main__':unittest.main()
