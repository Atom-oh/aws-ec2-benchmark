"""Contract tests for adding traffic to existing servers without restarting them."""
import copy
import importlib
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
import springboot_traffic48 as runner
try:
    boost = importlib.import_module('springboot_traffic48_boost')
except ModuleNotFoundError:
    boost = None


def metadata():
    return dict(run_id='test1', start_epoch=2000000000, warmup_seconds=300,
                server_digest='sha256:'+'a'*64, client_digest='sha256:'+'b'*64,
                calibrated=dict(peak_rps=66000), instances=list(runner.TYPES),
                phases=runner.build_phases(20000, 60000))


class BoostRunnerTests(unittest.TestCase):
    def plan(self):
        self.assertIsNotNone(boost, 'Additional traffic runner is required')
        value=metadata()
        return value, boost.build_boost_plan(value, value['start_epoch']+2700, 90000)

    def test_future_idle_activation_preserves_end_and_history(self):
        value=metadata();before=copy.deepcopy(value)
        self.assertIsNotNone(boost)
        plan=boost.build_boost_plan(value, value['start_epoch']+2700, 90000)
        self.assertEqual(value, before)
        self.assertEqual(plan['peak_rps'], 90000)
        self.assertEqual(plan['measurement_offset_seconds'], 2700)
        self.assertEqual(plan['start_epoch']+sum(p['duration_seconds'] for p in plan['phases']),
                         value['start_epoch']+172800)
        self.assertEqual(plan['phases'][0]['name'], value['phases'][1]['name'])
        self.assertEqual(plan['phases'][0]['rate_rps'], 0)

    def test_added_peak_and_ramps_preserve_original_steady_low_and_mid_rates(self):
        value,plan=self.plan()
        originals={p['name']:p for p in value['phases']}
        def rate(p,t):
            ramp=p['ramp_seconds']
            return p['from_rate_rps']+(p['rate_rps']-p['from_rate_rps'])*t/ramp if ramp and t<ramp else p['rate_rps']
        for p in plan['phases']:
            base=originals[p['name']]
            if '-l100-' in p['name']:
                self.assertEqual(base['rate_rps']+p['rate_rps'], 90000)
                if p['ramp_seconds']:
                    self.assertAlmostEqual(rate(base,30)+rate(p,30), (base['from_rate_rps']+90000)/2)
            else:
                self.assertEqual(p['rate_rps'], 0)
                self.assertEqual(rate(base,61)+rate(p,61), base['rate_rps'])
            if p['name'].startswith('d2-'):
                self.assertEqual(p['ramp_seconds'], 0)
        down=next(p for p in plan['phases'] if p['name']=='d1-c1-l80-s5')
        self.assertEqual(down['from_rate_rps'], 24000)
        self.assertEqual(down['ramp_seconds'], 60)
        self.assertEqual(runner.analysis.expected_offered(down), 720000)

    def test_activation_rejects_wrong_boundary_peak_and_nonfinite_target(self):
        self.assertIsNotNone(boost)
        m=metadata()
        for offset,target in [(2701,90000),(6300,90000),(171900,90000),(172800,90000),(2700,66000),
                              (2700,float('nan')),(2700,float('inf'))]:
            with self.subTest(offset=offset,target=target), self.assertRaises(ValueError):
                boost.build_boost_plan(m,m['start_epoch']+offset,target)

    def test_activation_choice_is_future_idle_phase_with_full_provisioning_lead(self):
        self.assertIsNotNone(boost)
        m=metadata()
        chosen=boost.choose_activation(m,m['start_epoch']+2000,lead_seconds=900)
        self.assertEqual(chosen,m['start_epoch']+4500)
        with self.assertRaises(ValueError):
            boost.choose_activation(m,m['start_epoch']+172000,lead_seconds=900)

    def test_manifests_add_only_six_unprivileged_isolated_finite_clients(self):
        value,plan=self.plan()
        objects=boost.render_boost(value,plan,'sha256:'+'c'*64)
        self.assertEqual({p['kind'] for p in objects},{'PersistentVolumeClaim','ConfigMap','Job'})
        jobs=[p for p in objects if p['kind']=='Job'];self.assertEqual(len(jobs),6)
        for job in jobs:
            self.assertTrue(job['metadata']['name'].endswith('-boost'))
            self.assertEqual(job['metadata']['namespace'],runner.NAMESPACE)
            self.assertLessEqual(job['spec']['activeDeadlineSeconds'],180000)
            spec=job['spec']['template']['spec']
            self.assertFalse(spec['automountServiceAccountToken'])
            self.assertNotIn('serviceAccountName',spec)
            self.assertEqual(spec['nodeSelector']['node.kubernetes.io/instance-type'],'c6in.2xlarge')
            self.assertEqual(spec['nodeSelector']['topology.kubernetes.io/zone'],runner.ZONE)
            self.assertTrue(spec['affinity']['podAntiAffinity']['requiredDuringSchedulingIgnoredDuringExecution'])
            self.assertNotIn('limits',spec['containers'][0]['resources'])
            self.assertEqual(spec['restartPolicy'],'Never')
        for cm in [p for p in objects if p['kind']=='ConfigMap']:
            c=json.loads(cm['data']['config.json'])
            self.assertTrue(c['allow_idle']);self.assertIsNone(c['cleanup'])
            self.assertEqual(c['start_epoch'],plan['start_epoch'])
            self.assertIn('-server:8080/',c['target'])
            self.assertNotIn('-boost-server',c['target'])

    def test_failed_extra_capture_is_independent_of_original_and_gc_capture(self):
        calls=[]
        def capture(pvc,directory,image,server_node=False):
            calls.append(pvc)
            if pvc.endswith('m7i-xlarge-boost-results'):
                raise OSError('extra source unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'test1';out.mkdir()
            (out/'metadata.json').write_text(json.dumps(dict(boost={'status':'launched'})))
            with patch.object(runner,'kubectl',return_value=SimpleNamespace(stdout='{"items":[]}')), \
                 patch.object(runner,'copy_pvc',side_effect=capture):
                runner.collect(out,'sha256:'+'a'*64)
            self.assertEqual(len(calls),18)
            errors=json.loads((out/'collection-latest.json').read_text())['errors']
            self.assertEqual(len(errors),1)
            self.assertEqual(errors[0]['instance'],'m7i.xlarge')
            self.assertEqual(errors[0]['source'],'boost')

    def test_launch_rechecks_activation_after_dry_run_before_any_mutation(self):
        self.assertIsNotNone(boost)
        self.assertTrue(callable(getattr(boost,'launch_boost',None)))
        import hashlib
        now=[1000.0];calls=[]
        m=dict(boost=dict(status='prepared',start_epoch=1301.0))
        def remote(*args,**kwargs):
            calls.append(args)
            self.assertIn('--dry-run=server',args)
            self.assertLessEqual(kwargs['timeout'],120)
            now[0]=1306.0
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);manifest=output/'boost-clients.yaml';manifest.write_text('reviewed manifest\n')
            m['boost']['manifest_sha256']=hashlib.sha256(manifest.read_bytes()).hexdigest()
            with patch.object(runner,'review_gate'),patch.object(runner,'kubectl',side_effect=remote):
                with self.assertRaises(ValueError):
                    boost.launch_boost(output,m,'test1',clock=lambda:now[0])
            self.assertEqual(len(calls),1)
            self.assertEqual(m['boost']['status'],'prepared')
            self.assertFalse((output/'metadata.json').exists())


if __name__=='__main__':
    unittest.main()
