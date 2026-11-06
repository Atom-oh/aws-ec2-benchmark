#!/usr/bin/env python3
"""Add a finite independent traffic source to existing comparison servers."""
import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import re
import time

import springboot_traffic48 as runner


def additional_phases(metadata, peak_rps):
    base_peak = metadata['calibrated']['peak_rps']
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
               for v in (base_peak, peak_rps)) or not 0 < base_peak < peak_rps:
        raise ValueError('Additional peak must be finite and greater than original peak')
    delta = peak_rps-base_peak
    result, previous = [], 0.0
    for phase in metadata['phases']:
        rate = delta if '-l100-' in phase['name'] else 0.0
        if rate and phase['rate_rps'] != base_peak:
            raise ValueError('Original peak rate does not match calibration')
        ramp = phase.get('ramp_seconds', 0) if rate != previous else 0
        result.append(dict(name=phase['name'], duration_seconds=phase['duration_seconds'],
                           rate_rps=rate, from_rate_rps=previous, ramp_seconds=ramp))
        previous = rate
    return result


def build_boost_plan(metadata, activation_epoch, peak_rps):
    phases = additional_phases(metadata, peak_rps)
    offset = 0
    for index, phase in enumerate(phases):
        if metadata['start_epoch']+offset == activation_epoch:
            if phase['rate_rps'] or (phase['ramp_seconds'] and phase['from_rate_rps']):
                raise ValueError('Activation must be an idle additional-traffic phase')
            if not any(p['rate_rps'] for p in phases[index:]):
                raise ValueError('No future peak remains to increase')
            return dict(version=1, peak_rps=peak_rps,
                        base_peak_rps=metadata['calibrated']['peak_rps'],
                        start_epoch=activation_epoch, measurement_offset_seconds=offset,
                        phases=phases[index:])
        offset += phase['duration_seconds']
    raise ValueError('Activation must match a remaining original phase boundary')


def choose_activation(metadata, now, lead_seconds=900):
    if not math.isfinite(now) or not math.isfinite(lead_seconds) or lead_seconds < 900:
        raise ValueError('Need finite time and at least 900 seconds provisioning lead')
    at = metadata['start_epoch']
    phases=additional_phases(metadata, metadata['calibrated']['peak_rps']+1)
    for index, phase in enumerate(phases):
        if at >= now+lead_seconds and not phase['rate_rps'] and not (
                phase['ramp_seconds'] and phase['from_rate_rps']) and any(p['rate_rps'] for p in phases[index:]):
            return at
        at += phase['duration_seconds']
    raise ValueError('No future idle phase with sufficient provisioning lead')


def render_boost(metadata, plan, client_digest):
    _, objects = runner.render(metadata['run_id'], metadata['server_digest'], client_digest,
                               plan['phases'], plan['start_epoch'])
    result = [copy.deepcopy(o) for o in objects if o['kind'] in ('PersistentVolumeClaim','ConfigMap','Job')]
    renames = {}
    for obj in result:
        name = obj['metadata']['name']
        if name.endswith('-load-results'):
            renamed = name[:-len('-load-results')]+'-boost-results'
        else:
            renamed = name[:-len('-load')]+'-boost'
        renames[name] = renamed
        obj['metadata']['name'] = renamed
        obj['metadata']['labels']['traffic-stage'] = 'boost'
    for obj in result:
        if obj['kind'] == 'ConfigMap':
            config = json.loads(obj['data']['config.json'])
            config.update(allow_idle=True, cleanup=None)
            obj['data']['config.json'] = json.dumps(config, indent=2)
        elif obj['kind'] == 'Job':
            template = obj['spec']['template']
            template['metadata']['labels']['traffic-stage'] = 'boost'
            spec = template['spec']
            spec['automountServiceAccountToken'] = False
            spec.pop('serviceAccountName', None)
            for volume in spec['volumes']:
                if 'configMap' in volume:
                    volume['configMap']['name'] = renames[volume['configMap']['name']]
                if 'persistentVolumeClaim' in volume:
                    key = volume['persistentVolumeClaim']['claimName']
                    volume['persistentVolumeClaim']['claimName'] = renames[key]
            remaining = sum(p['duration_seconds'] for p in plan['phases'])
            obj['spec']['activeDeadlineSeconds'] = min(180000, remaining+7200)
    return result


def launch_boost(output, metadata, run_id, clock=None):
    clock=clock or time.time
    runner.review_gate(output)
    plan=metadata['boost']
    manifest=output/'boost-clients.yaml'
    if plan['status'] != 'prepared':
        raise ValueError('Additional traffic already launched or launch attempted')
    def check_lead():
        if clock() > plan['start_epoch']-300:
            raise ValueError('Less than five minutes remain before activation; do not launch late')
    check_lead()
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != plan['manifest_sha256']:
        raise ValueError('Prepared manifest changed')
    runner.kubectl('--request-timeout=60s','apply','--dry-run=server','-f',str(manifest),timeout=120)
    # API latency must not silently turn a reviewed future schedule into a late start.
    check_lead()
    plan['status']='launching'
    runner.write_json(output/'metadata.json',metadata)
    runner.kubectl('--request-timeout=60s','apply','-f',str(manifest),timeout=120)
    ready_timeout=min(900,math.floor(plan['start_epoch']-clock()-30))
    if ready_timeout <= 0:
        raise ValueError('Activation too close to verify client readiness')
    runner.kubectl('--request-timeout=60s','wait','--for=condition=ready','pod','-l',
                   f'experiment=springboot-traffic48,benchmark-run={run_id},traffic-stage=boost',
                   f'--timeout={ready_timeout}s',timeout=ready_timeout+20)
    if clock() >= plan['start_epoch']:
        raise ValueError('Client readiness was not verified before activation')
    plan['status']='launched'
    plan['launched_at']=dt.datetime.now(dt.timezone.utc).isoformat()
    runner.write_json(output/'metadata.json',metadata)
    runner.write_json(output/'boost-plan.json',plan)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare','launch','status'))
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--client-digest')
    parser.add_argument('--peak-rps', type=float, default=90000)
    args = parser.parse_args()
    if not re.fullmatch(runner.RUN_ID_PATTERN, args.run_id):
        parser.error('Invalid run id')
    output = runner.ROOT/'results/springboot-traffic48'/args.run_id
    metadata = json.loads((output/'metadata.json').read_text())
    manifest = output/'boost-clients.yaml'
    if args.action == 'prepare':
        if not args.client_digest:
            parser.error('prepare requires --client-digest')
        if metadata.get('boost') or manifest.exists():
            raise ValueError('Additional traffic already prepared; never overwrite/relaunch')
        activation = choose_activation(metadata, time.time())
        plan = build_boost_plan(metadata, activation, args.peak_rps)
        objects = render_boost(metadata, plan, args.client_digest)
        runner.save_yaml(manifest, objects)
        plan.update(client_digest=args.client_digest, status='prepared',
                    manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                    prepared_at=dt.datetime.now(dt.timezone.utc).isoformat())
        metadata['boost'] = plan
        runner.write_json(output/'metadata.json', metadata)
        runner.write_json(output/'boost-plan.json', plan)
        print(json.dumps(plan, indent=2))
    elif args.action == 'launch':
        plan = launch_boost(output,metadata,args.run_id)
        print('Additional source activation UTC:',dt.datetime.fromtimestamp(plan['start_epoch'],dt.timezone.utc).isoformat())
    else:
        runner.kubectl('get','jobs,pods,pvc','-l',
                       f'experiment=springboot-traffic48,benchmark-run={args.run_id},traffic-stage=boost','-o','wide')


if __name__ == '__main__':
    main()
