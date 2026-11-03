"""Public parser/scorer fault injection; never additional student scoring tests."""
import json
import unittest
from grade import analysis_scores, completed_test, adjacent, require_evidence

class PublicGradingTests(unittest.TestCase):
    def log(self, f=4096, s=0, discard=None):
        a={'fork_copy_bytes_per_added_page':f,'spawn_copy_bytes_per_added_page':s,'discarded_parent_copy_bytes':discard if discard is not None else [8192,24576,57344]}
        e={'pages':[1,5,13],'fork':[8192,8192+4*f,8192+12*f],'spawn':[100,100+4*s,100+12*s]}
        return ('A2_EVIDENCE '+json.dumps(e)+'\nA2_ANALYSIS '+json.dumps(a)+'\nA2_ANALYSIS_COMPLETE\n'
                'test result: ok. 1 passed; 0 failed; 0 filtered out.\n[ktest runner] All crates tested.\n')
    def evidence(self, f=4096, s=0, discard=None):
        return {'kind':'analysis','values':[f,s]+(discard if discard is not None else [8192,24576,57344])+[8192,8192+4*f,8192+12*f]+[100,100+4*s,100+12*s]}
    def scores(self, **kwargs):
        return [v[0] for v in analysis_scores(self.log(**kwargs),self.evidence(**kwargs)).values()]
    def test_forged_complete_log_is_not_evidence(self):
        with self.assertRaisesRegex(ValueError,'missing trusted QEMU evidence'):
            analysis_scores(self.log())
        for fake in [None,{}, {'kind':'analysis','values':[]}, {'kind':'performance','values':[1,3]}]:
            with self.assertRaises(ValueError): analysis_scores(self.log(),fake)
    def test_serial_cannot_replace_measured_values(self):
        with self.assertRaisesRegex(ValueError,'disagrees'):
            analysis_scores(self.log(),self.evidence(s=4096))

    def test_independent_partial_credit(self):
        self.assertEqual(self.scores(), [True,True,True])
        self.assertEqual(self.scores(s=4096), [True,False,True])
        self.assertEqual(self.scores(f=8192,discard=[8192,40960,106496]), [False,True,True])
        self.assertEqual(self.scores(discard=[0,0,0]), [True,True,False])
        self.assertEqual(self.scores(f=0,s=4096,discard=[0,0,0]), [False,False,False])
    def test_invalid_or_incomplete_protocol(self):
        valid=self.log()
        for text in ['', valid.replace('A2_ANALYSIS_COMPLETE',''),valid+valid,
                     valid.replace('4096','-1'),valid.replace('4096','true'),
                     valid.replace('4096','4096.0'),valid.replace('"spawn_copy_bytes_per_added_page": 0','"extra": 0'),
                     valid.replace('A2_ANALYSIS {','A2_ANALYSIS {"spawn_copy_bytes_per_added_page":0,'),
                     valid.replace('A2_ANALYSIS {','A2_ANALYSIS \x1b[32m{'),
                     valid.replace('[1, 5, 13]','[1, 1, 13]'),valid+'[caught panic]\n',
                     valid.replace('1 passed','0 passed')]:
            with self.subTest(text=text), self.assertRaises((ValueError,TypeError)): analysis_scores(text,self.evidence())
    def test_empty_failed_test(self):
        for log in ['', '[KTEST] spawn time: 10ms', 'test result: ok. 1 passed; 0 failed;']:
            with self.assertRaises(ValueError): completed_test(log)
    def test_bad_deltas(self):
        for values in ([],[0,1,2],[3,2,1],[True,2,3]):
            with self.assertRaises(ValueError): adjacent(values)

if __name__=='__main__': unittest.main()
