#!/usr/bin/env python3
"""Prepare/calibrate/launch/collect a six-instance, independent 48 h traffic test."""
import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import yaml
import traffic48_analysis as analysis

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = 'mall-apne2-mgmt'
NAMESPACE = 'benchmark'
ZONE = 'ap-northeast-2c'
TYPES = ('m7i.xlarge', 'm7i-flex.xlarge', 'm8i.xlarge', 'm8i-flex.xlarge', 'm7g.xlarge', 'm8g.xlarge')
ECR = '180294183052.dkr.ecr.ap-northeast-2.amazonaws.com/benchmark'
WARMUP_SECONDS = 300
RUN_ID_PATTERN = r'[a-z0-9](?:[a-z0-9-]{0,14}[a-z0-9])?'
READER_IMAGE = f'{ECR}/wrk@sha256:8390b04216601702c9d24172bb95dcb1729f03347b4140f1f3516cc5e29eb969'


def kubectl(*args, **kwargs):
    return subprocess.run(['kubectl', '--context', CONTEXT, '-n', NAMESPACE, *args], check=True, **kwargs)


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    temp.replace(path)


def analyze_isolated(output):
    """Wait for one report child; its exit returns the analyzer's heap to the OS."""
    output = Path(output).resolve()
    if (output.parent != (ROOT/'results/springboot-traffic48').resolve()
            or not re.fullmatch(RUN_ID_PATTERN, output.name)):
        raise ValueError('Analysis output must be a valid traffic48 run directory')
    subprocess.run([sys.executable, str(ROOT/'scripts/springboot_traffic48.py'),
                    'analyze', '--run-id', output.name], cwd=ROOT, check=True)


def build_phases(low_rps, capacity_rps):
    if not all(math.isfinite(x) and x > 0 for x in (low_rps, capacity_rps)) or low_rps >= capacity_rps:
        raise ValueError('Need finite 0 < low_rps < capacity_rps')
    peak = capacity_rps*1.1
    rates = {level:low_rps+(level-40)/60*(peak-low_rps) for level in (40,60,80,100)}
    ramp = [(40,45),(60,30),(80,30),(100,30),(80,30),(60,30),(40,45)]
    burst = [(40,45),(100,1),(40,39),(100,5),(40,30),(100,15),(40,30),(100,60),(40,15)]
    phases, previous = [], low_rps
    for day, pattern in [(1,ramp),(2,burst)]:
        for cycle in range(1,7):
            for step,(level,minutes) in enumerate(pattern,1):
                phases.append({'name':f'd{day}-c{cycle}-l{level}-s{step}', 'duration_seconds':minutes*60,
                               'rate_rps':rates[level], 'from_rate_rps':previous,
                               'ramp_seconds':60 if day==1 and previous!=rates[level] else 0})
                previous=rates[level]
    return phases


def calibration_phases():
    # 5k spacing near expected capacity avoids stepping directly from healthy
    # sub-saturation to severe overload without a valid >=90% CPU observation.
    rates = (5000,10000,15000,20000,25000,30000,35000,40000,45000,50000,
             55000,60000,65000,70000,75000,80000,90000,100000,120000,150000)
    return [{'name':'warmup', 'duration_seconds':300, 'rate_rps':20000, 'ramp_seconds':0, 'from_rate_rps':20000}] + [
        {'name':f'cal-{rate}', 'duration_seconds':120, 'rate_rps':rate, 'ramp_seconds':0, 'from_rate_rps':rate}
        for rate in rates]


def render(run_id, server_digest, client_digest, phases, start_epoch, calibration=False):
    if not re.fullmatch(RUN_ID_PATTERN,run_id):
        raise ValueError('Run id: 1..16 lowercase letters/digits/hyphens')
    for digest in (server_digest,client_digest):
        if not isinstance(digest,str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',digest):
            raise ValueError('Images must be pinned sha256 digests')
    base = f'sb-traffic48-{run_id}'
    common = {'benchmark-run':run_id,'experiment':'springboot-traffic48'}
    source = next(yaml.safe_load_all((ROOT/'benchmarks/springboot/springboot-server.yaml').read_text()))
    servers,clients=[],[]
    for instance in TYPES:
        name=base+'-'+instance.replace('.','-')
        labels=dict(common,**{'instance-type':instance})
        server_name=name+'-server'
        template=copy.deepcopy(source['spec']['template'])
        template['metadata']={'labels':dict(labels,benchmark='springboot-traffic48-server',app=server_name),
                              'annotations':{'karpenter.sh/do-not-disrupt':'true'}}
        spec=template['spec']
        spec.update(restartPolicy='Never',automountServiceAccountToken=False)
        spec['nodeSelector']={'node.kubernetes.io/instance-type':instance,'karpenter.sh/nodepool':'benchmark-server',
                              'topology.kubernetes.io/zone':ZONE,'karpenter.sh/capacity-type':'on-demand'}
        server=spec['containers'][0]
        server['image']=f'{ECR}/springboot-simple@{server_digest}'
        server['resources']={'requests':{'cpu':'3000m','memory':'12Gi'}}
        env=[e for e in server['env'] if e['name']!='INSTANCE_TYPE']
        for e in env:
            if e['name']=='JAVA_OPTS':
                e['value']+=' -Xlog:gc*,safepoint:file=/gc/gc.log:time,uptime,level,tags:filecount=8,filesize=20M'
        server['env']=env+[{'name':'INSTANCE_TYPE','value':instance},
                          {'name':'MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_INCLUDE','value':'health,metrics'}]
        # Restarting a JVM during a peak invalidates GC/CPU history. Readiness does
        # not restart it; disable template liveness and rely on Job deadline/errors.
        server.pop('livenessProbe',None)
        server['volumeMounts']=[{'name':'gc','mountPath':'/gc'}]
        spec['volumes']=[{'name':'gc','persistentVolumeClaim':{'claimName':name+'-gc'}}]
        def pvc(suffix):
            return {'apiVersion':'v1','kind':'PersistentVolumeClaim','metadata':{'name':name+suffix,'labels':labels},
                    'spec':{'accessModes':['ReadWriteOnce'],'storageClassName':'gp3','resources':{'requests':{'storage':'1Gi'}}}}
        servers.extend([pvc('-gc'),{'apiVersion':'batch/v1','kind':'Job','metadata':{'name':server_name,'labels':labels},
                  'spec':{'backoffLimit':0,'activeDeadlineSeconds':194400,'ttlSecondsAfterFinished':604800,'template':template}},
                  {'apiVersion':'v1','kind':'Service','metadata':{'name':server_name,'labels':labels},
                   'spec':{'type':'ClusterIP','selector':{'app':server_name},'ports':[{'port':8080,'targetPort':8080}]}}])
        if calibration and instance!='m7i.xlarge':
            continue
        suffix='-cal' if calibration else '-load'
        account=name+'-cleanup'
        config_name=name+suffix
        config={'target':f'http://{server_name}:8080/','instance':instance,'run_id':run_id,
                'start_epoch':start_epoch,'timeout_seconds':2,'max_inflight':2048,'phases':phases,
                'cleanup':None if calibration else {'server_job':server_name,'server_service':server_name,'namespace':NAMESPACE}}
        clients.extend([pvc(suffix+'-results'),{'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':config_name,'labels':labels},
                                               'data':{'config.json':json.dumps(config,indent=2)}}])
        if not calibration:
            clients.extend([{'apiVersion':'v1','kind':'ServiceAccount','metadata':{'name':account,'labels':labels}},
                            {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'Role','metadata':{'name':account,'labels':labels},
                             'rules':[{'apiGroups':['batch'],'resources':['jobs'],'resourceNames':[server_name],'verbs':['delete']},
                                      {'apiGroups':[''],'resources':['services'],'resourceNames':[server_name],'verbs':['delete']}]},
                            {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'RoleBinding','metadata':{'name':account,'labels':labels},
                             'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'Role','name':account},
                             'subjects':[{'kind':'ServiceAccount','name':account,'namespace':NAMESPACE}]}])
        client_spec={'restartPolicy':'Never','automountServiceAccountToken':not calibration,
                     'nodeSelector':{'node-type':'benchmark-client','karpenter.sh/nodepool':'benchmark-client',
                                     'node.kubernetes.io/instance-type':'c6in.2xlarge',
                                     'karpenter.sh/capacity-type':'on-demand','topology.kubernetes.io/zone':ZONE},
                     'tolerations':[{'key':'benchmark-client','operator':'Equal','value':'true','effect':'NoSchedule'}],
                     'affinity':copy.deepcopy(spec['affinity']),
                     'volumes':[{'name':'config','configMap':{'name':config_name}},
                                {'name':'results','persistentVolumeClaim':{'claimName':name+suffix+'-results'}}],
                     'containers':[{'name':'load','image':f'{ECR}/traffic-client@{client_digest}',
                         'command':['/usr/local/bin/traffic-client','-config','/config/config.json','-results','/results'],
                         'resources':{'requests':{'cpu':'6000m','memory':'4Gi'}},
                         'volumeMounts':[{'name':'config','mountPath':'/config','readOnly':True},{'name':'results','mountPath':'/results'}]}]}
        if not calibration:
            client_spec['serviceAccountName']=account
        clients.append({'apiVersion':'batch/v1','kind':'Job','metadata':{'name':name+suffix,'labels':labels},
                        'spec':{'backoffLimit':0,'activeDeadlineSeconds':3600 if calibration else 180000,
                                'ttlSecondsAfterFinished':604800,'template':{'metadata':{'labels':dict(labels,benchmark='springboot-traffic48-client',
                                  **{'traffic-stage':'calibration' if calibration else 'measurement'}),
                                  'annotations':{'karpenter.sh/do-not-disrupt':'true'}},'spec':client_spec}}})
    for obj in servers+clients:
        obj['metadata']['namespace']=NAMESPACE
    return servers,clients


def save_yaml(path,objects):
    Path(path).write_text(yaml.safe_dump_all(objects,sort_keys=False))


def artifact_hash():
    paths=[ROOT/'scripts/springboot_traffic48.py',ROOT/'scripts/traffic48_analysis.py',
           ROOT/'scripts/springboot_traffic48_boost.py',
           ROOT/'docs/springboot-traffic48.md',ROOT/'benchmarks/springboot/springboot-server.yaml',
           ROOT/'scripts/run-springboot-traffic48.sh']
    paths+=sorted((ROOT/'docker/traffic-client').glob('*.go'))
    paths += [ROOT/'docker/traffic-client/Dockerfile', ROOT/'docker/traffic-client/go.mod']
    h=hashlib.sha256()
    for path in paths:
        h.update(str(path.relative_to(ROOT)).encode());h.update(path.read_bytes())
    return h.hexdigest()


def review_gate(output):
    review=json.loads((output/'review.json').read_text())
    if (review.get('verdict')!='PASS' or review.get('score',0)<85
            or review.get('artifact_sha256')!=artifact_hash()):
        raise ValueError('Current independent content review PASS >=85 required')


def collect(output,client_digest,calibration=False):
    jobs=json.loads(kubectl('get','pods','-l',f'experiment=springboot-traffic48,benchmark-run={output.name}',
                             '-o','json',capture_output=True,text=True).stdout)
    write_json(output/'pods-status.json',jobs)
    suffix='-cal' if calibration else '-load'
    reader_image=READER_IMAGE  # Multiarch: GC PVC can be bound to a Graviton node.
    metadata_path=output/'metadata.json'
    metadata=json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    with_boost=not calibration and bool(metadata.get('boost'))
    errors=[]
    for instance in ('m7i.xlarge',) if calibration else TYPES:
        directory=output/('calibration' if calibration else instance)
        directory.mkdir(exist_ok=True)
        name='sb-traffic48-'+output.name+'-'+instance.replace('.','-')+suffix
        pod=next((p for p in jobs['items'] if any(o.get('name')==name for o in p['metadata'].get('ownerReferences',[]))),None)
        try:
            if pod and pod.get('status',{}).get('phase')=='Running':
                kubectl('cp','-c','load',pod['metadata']['name']+':/results/.',str(directory))
            else:
                copy_pvc(name+'-results', directory, reader_image)
        except (subprocess.SubprocessError,OSError) as error:
            errors.append({'instance':instance,'source':'load','error':str(error)})
        if with_boost:
            additional=directory/'boost';additional.mkdir(exist_ok=True)
            boost_name=name[:-len(suffix)]+'-boost'
            boost_pod=next((p for p in jobs['items'] if any(o.get('name')==boost_name
                           for o in p['metadata'].get('ownerReferences',[]))),None)
            try:
                if boost_pod and boost_pod.get('status',{}).get('phase')=='Running':
                    kubectl('cp','-c','load',boost_pod['metadata']['name']+':/results/.',str(additional))
                elif metadata['boost'].get('status') in ('launching','launched'):
                    copy_pvc(boost_name+'-results',additional,reader_image)
                else:
                    raise ValueError('Additional source is prepared but not launched')
            except (subprocess.SubprocessError,OSError,ValueError) as error:
                errors.append({'instance':instance,'source':'boost','error':str(error)})
        if not calibration:
            # Separate persistent GC volume; source server can already be cleaned up.
            server_name=name[:-len(suffix)]+'-server'
            server=next((p for p in jobs['items'] if any(o.get('name')==server_name for o in p['metadata'].get('ownerReferences',[]))),None)
            gc=directory/'gc';gc.mkdir(exist_ok=True)
            collected_at=time.time()
            try:
                # A fresh copy excludes stale rotation slots left by older captures.
                with tempfile.TemporaryDirectory(prefix='capture-',dir=gc) as tmp:
                    capture=Path(tmp)
                    if server and server.get('status',{}).get('phase')=='Running':
                        copy_running_gc(server['metadata']['name'], capture)
                    else:
                        copy_pvc(name[:-len(suffix)]+'-gc',capture,reader_image,server_node=True)
                    for old in gc.glob('gc.log*'):
                        old.unlink()
                    for raw in capture.glob('gc.log*'):
                        raw.replace(gc/raw.name)
                archive_gc(gc,collected_at=collected_at)
            except (subprocess.SubprocessError,OSError,ValueError) as error:
                errors.append({'instance':instance,'source':'gc','error':str(error)})
    write_json(output/('calibration-collection.json' if calibration else 'collection-latest.json'),
               {'timestamp':time.time(),'errors':errors})
    if calibration and errors:
        raise RuntimeError(f'Calibration collection failed: {errors}')


def copy_running_gc(pod, directory):
    """Read raw GC files without requiring tar in the Java server image.

    Capture remains non-atomic during rotation; archive coverage is an estimate.
    A failed read leaves the previous snapshot intact in collect().
    """
    listing = kubectl('exec', pod, '-c', 'springboot', '--', 'sh', '-c',
        'for file in /gc/gc.log*; do [ -f "$file" ] && printf "%s\\n" "$file"; done',
        capture_output=True, text=True).stdout.splitlines()
    if not listing or any(not re.fullmatch(r'/gc/gc\.log(?:\.\d+)?', name) for name in listing):
        raise ValueError('Missing GC logs or unexpected GC file path')
    for name in listing:
        with (Path(directory)/Path(name).name).open('wb') as destination:
            kubectl('exec', pod, '-c', 'springboot', '--', 'cat', name, stdout=destination)


def archive_gc(directory,collected_at=None):
    """Append only unseen bytes, retaining raw GC/safepoint lines across rotation."""
    directory=Path(directory)
    index_path=directory/'archive-index.json'
    offsets=json.loads(index_path.read_text()) if index_path.exists() else {}
    captured=time.time() if collected_at is None else collected_at
    coverage_path=directory/'coverage.json'
    coverage=json.loads(coverage_path.read_text()) if coverage_path.exists() else {'intervals':[],'gaps':[]}
    earliest=None
    with (directory/'all.log').open('ab') as archive:
        for path in sorted(directory.glob('gc.log*')):
            data=path.read_bytes()
            for stamp in re.findall(rb'^\[([^\]]+)\]',data,flags=re.MULTILINE):
                try:
                    epoch=analysis.epoch(stamp.decode())
                except (ValueError,UnicodeDecodeError):
                    continue
                earliest=epoch if earliest is None else min(earliest,epoch)
                break
            # Files smaller than 4 KiB may acquire a new identity when growing;
            # duplicate events are deduplicated by timestamp/gc-id in analysis.
            key=hashlib.sha256(data[:4096]).hexdigest()
            old=offsets.get(key,0)
            if len(data)<old:
                old=0
            # Never archive a torn final line. It will arrive on the next copy.
            end=data.rfind(b'\n')+1
            if end>old:
                archive.write(data[old:end])
                offsets[key]=end
    write_json(index_path,offsets)
    previous=coverage.get('last_collection_epoch')
    if earliest is not None and earliest<=captured:
        coverage['intervals'].append([earliest,captured])
        if previous is not None and earliest>previous:
            coverage['gaps'].append([previous,earliest])
    elif previous is not None and captured>previous:
        coverage['gaps'].append([previous,captured])
    coverage.update(last_collection_epoch=captured,
                    inference='retained raw timestamps to copy start; non-atomic capture')
    write_json(coverage_path,coverage)


def copy_pvc(pvc,directory,image,server_node=False):
    # Use the already bound volume's node affinity; unlike benchmark Pods this
    # reader intentionally may share the node and carries no benchmark label.
    name=pvc[:55]+'-reader'
    reader={'apiVersion':'v1','kind':'Pod','metadata':{'name':name,'namespace':NAMESPACE,
             'labels':{'experiment':'springboot-traffic48-reader'}},
            'spec':{'restartPolicy':'Never','automountServiceAccountToken':False,'activeDeadlineSeconds':300,
                    'tolerations':[{'key':'benchmark' if server_node else 'benchmark-client','operator':'Equal','value':'true','effect':'NoSchedule'}],
                    'containers':[{'name':'reader','image':image,'command':['/bin/sh','-c','sleep 300'],
                                   'resources':{'requests':{'cpu':'10m','memory':'16Mi'}},
                                   'volumeMounts':[{'name':'results','mountPath':'/results','readOnly':True}]}],
                    'volumes':[{'name':'results','persistentVolumeClaim':{'claimName':pvc,'readOnly':True}}]}}
    kubectl('create','-f','-',input=yaml.safe_dump(reader),text=True)
    try:
        kubectl('wait','--for=condition=ready','pod/'+name,'--timeout=180s')
        kubectl('cp','-c','reader',name+':/results/.',str(directory))
    finally:
        kubectl('delete','pod',name,'--ignore-not-found','--wait=false')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','calibrate','launch','status','collect','analyze','watch'))
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--server-digest')
    parser.add_argument('--client-digest')
    args=parser.parse_args()
    if not re.fullmatch(RUN_ID_PATTERN,args.run_id):
        parser.error('Invalid run id')
    output=ROOT/'results/springboot-traffic48'/args.run_id
    if args.action=='prepare':
        if not args.server_digest or not args.client_digest:
            parser.error('prepare requires --server-digest and --client-digest')
        if output.exists():
            raise ValueError('Run directory already exists; never overwrite an experiment')
        servers,cal=render(args.run_id,args.server_digest,args.client_digest,calibration_phases(),math.ceil(time.time())+3600,calibration=True)
        output.mkdir(parents=True)
        save_yaml(output/'servers.yaml',servers)
        save_yaml(output/'calibration.yaml',cal)
        write_json(output/'metadata.json',{'run_id':args.run_id,'context':CONTEXT,'zone':ZONE,'instances':TYPES,
                                          'server_digest':args.server_digest,'client_digest':args.client_digest,
                                          'prepared_at':dt.datetime.now(dt.timezone.utc).isoformat(),'duration_seconds':172800})
        print(output)
        return
    metadata=json.loads((output/'metadata.json').read_text())
    if args.action=='status':
        kubectl('get','jobs,pods,pvc','-l',f'experiment=springboot-traffic48,benchmark-run={args.run_id}','-o','wide')
    elif args.action=='calibrate':
        review_gate(output)
        kubectl('apply','--dry-run=server','-f',str(output/'servers.yaml'))
        kubectl('apply','--dry-run=server','-f',str(output/'calibration.yaml'))
        kubectl('apply','-f',str(output/'servers.yaml'))
        kubectl('wait','--for=condition=ready','pod','-l',f'experiment=springboot-traffic48,benchmark-run={args.run_id},benchmark=springboot-traffic48-server', '--timeout=900s')
        _, cal = render(args.run_id,metadata['server_digest'],metadata['client_digest'],
                        calibration_phases(),math.ceil(time.time())+180,calibration=True)
        save_yaml(output/'calibration.yaml',cal)
        kubectl('apply','-f',str(output/'calibration.yaml'))
        job='sb-traffic48-'+args.run_id+'-m7i-xlarge-cal'
        # Bound each API call; a failed Job ends the wait without waiting an hour.
        deadline=time.monotonic()+3700
        while time.monotonic()<deadline:
            obj=json.loads(kubectl('get','job',job,'-o','json',capture_output=True,text=True).stdout)
            if obj.get('status',{}).get('failed'):
                raise RuntimeError('Calibration Job failed; inspect logs; no 48h load launched')
            if obj.get('status',{}).get('succeeded'):
                break
            time.sleep(20)
        else:
            raise TimeoutError('Calibration not complete within 3700 s')
        collect(output,metadata['client_digest'],calibration=True)
        status=json.loads((output/'calibration/status.json').read_text())
        if status.get('outcome')!='COMPLETE' or status.get('start_lateness_ms',float('inf'))>1000:
            raise ValueError('Calibration incomplete or started >1 s late; no 48h load launched')
        samples=analysis.read_jsonl(output/'calibration/samples.ndjson')
        metrics=analysis.read_jsonl(output/'calibration/metrics.ndjson')
        if not samples:
            raise ValueError('No calibration samples')
        start=statistics_median_start(samples)
        calibrated=analysis.calibrate(samples,metrics,calibration_phases(),start,status=status)
        write_json(output/'calibrated.json',calibrated)
        print(json.dumps(calibrated,indent=2))
    elif args.action=='launch':
        review_gate(output)
        if metadata.get('start_epoch'):
            raise ValueError('Already launched; never restart')
        calibrated=json.loads((output/'calibrated.json').read_text())
        phases=build_phases(calibrated['low_rps'],calibrated['capacity_rps'])
        # Existing calibration server remains alive. Each client performs equal
        # 5 min low-load warmup before the shared 48-hour measurement epoch.
        start=math.ceil(time.time())+900
        prewarm={'name':'warmup','duration_seconds':WARMUP_SECONDS,'rate_rps':calibrated['low_rps'],
                 'ramp_seconds':0,'from_rate_rps':calibrated['low_rps']}
        _,clients=render(args.run_id,metadata['server_digest'],metadata['client_digest'],[prewarm]+phases,start)
        save_yaml(output/'clients.yaml',clients)
        kubectl('apply','--dry-run=server','-f',str(output/'clients.yaml'))
        metadata.update(start_epoch=start+WARMUP_SECONDS,load_start_epoch=start,
                        warmup_seconds=WARMUP_SECONDS,phases=phases,calibrated=calibrated)
        # Record intent before external mutation so accidental re-launch is blocked.
        write_json(output/'metadata.json',metadata)
        kubectl('apply','-f',str(output/'clients.yaml'))
        kubectl('wait','--for=condition=ready','pod','-l',f'experiment=springboot-traffic48,benchmark-run={args.run_id},traffic-stage=measurement','--timeout=600s')
        print('Measurement start UTC:',dt.datetime.fromtimestamp(metadata['start_epoch'],dt.timezone.utc).isoformat())
    elif args.action=='collect':
        collect(output,metadata['client_digest'])
        analyze_isolated(output)
    elif args.action=='analyze':
        write_json(output/'progress-latest.json',analysis.report(output))
        print(output/'progress-latest.json')
    elif args.action=='watch':
        until=time.monotonic()+51*3600
        last_collect=0
        while time.monotonic()<until:
            try:
                jobs=json.loads(kubectl('get','jobs','-l',f'experiment=springboot-traffic48,benchmark-run={args.run_id}','-o','json',capture_output=True,text=True).stdout)
            except subprocess.SubprocessError as error:
                print(f'Observer API error: {error}; retry in 60s',flush=True)
                time.sleep(60)
                continue
            write_json(output/'jobs-status.json',jobs)
            loads=[j for j in jobs['items'] if j['metadata']['name'].endswith('-load')]
            done=len(loads)==6 and all(j.get('status',{}).get('succeeded') or j.get('status',{}).get('failed') for j in loads)
            if metadata.get('boost'):
                boosts=[j for j in jobs['items'] if j['metadata']['name'].endswith('-boost')]
                done=done and len(boosts)==6 and all(j.get('status',{}).get('succeeded') or j.get('status',{}).get('failed') for j in boosts)
            if time.monotonic()-last_collect>=1800 or done:
                try:
                    collect(output,metadata['client_digest'])
                    analyze_isolated(output)
                    last_collect=time.monotonic()
                except (subprocess.SubprocessError, ValueError, OSError) as error:
                    print(f'Collection error: {error}',flush=True)
                    if done:
                        raise
            if done:
                return
            time.sleep(60)
        raise TimeoutError('Observer ended after 51h; PVC retains data')


def statistics_median_start(samples):
    import statistics
    return statistics.median(analysis.epoch(s['timestamp'])-s['elapsed_sec'] for s in samples)


if __name__=='__main__':
    main()
