"""Real ASR capacity and isolated Docker fault experiments; outputs immutable raw JSON.

Fault operations only affect containers carrying the streamsense-lab Compose label.
No volume/data deletion. Existing user deployment is never selected.
"""
import argparse
import asyncio
import concurrent.futures
import hashlib
import json
import math
import subprocess
import threading
import time
import uuid
import logging
logging.getLogger('aiokafka').setLevel(logging.CRITICAL)
from pathlib import Path
import requests
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition

ROOT = Path(__file__).resolve().parents[1]
ASR = 'http://127.0.0.1:18001'
API = 'http://127.0.0.1:18000'
FLINK = 'http://127.0.0.1:18081'
BROKER = 'localhost:39092'
SOURCES = ['services/asr/asr_service.py', 'services/asr/runtime_metrics.py',
           'services/api/app.py', 'services/api/storage.py', 'flink/transcription_job.py',
           'tools/reliability_lab.py', 'experiments/compose.lab.yaml']

def now_ms():
    return int(time.time()*1000)

def get(url):
    r = requests.get(url, timeout=3)
    r.raise_for_status()
    return r.json()

def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered)-1)*q
    lo, hi = math.floor(rank), math.ceil(rank)
    return ordered[lo]+(ordered[hi]-ordered[lo])*(rank-lo)

def docker(*args):
    r = subprocess.run(['docker', *args], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=45)
    if r.returncode:
        raise RuntimeError(r.stderr[-1500:])
    return r.stdout.strip()

def container(service):
    ids = docker('ps', '-aq', '--filter', 'label=com.docker.compose.project=streamsense-lab',
                 '--filter', 'label=com.docker.compose.service='+service).splitlines()
    if len(ids) != 1:
        raise RuntimeError('expected exactly one isolated lab container: '+service)
    labels = json.loads(docker('inspect', ids[0]))[0]['Config']['Labels']
    if labels.get('com.docker.compose.project') != 'streamsense-lab':
        raise RuntimeError('refusing fault outside lab')
    return ids[0]

def metadata():
    fixtures = json.loads((ROOT/'experiments/fixtures.json').read_text(encoding='utf-8'))
    for item in fixtures:
        path = ROOT/'data/reliability_lab/fixtures'/f"{item['id']}.wav"
        item['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    r = subprocess.run(['nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader,nounits'], capture_output=True, text=True)
    return dict(timestamp_ms=now_ms(), gpu=r.stdout.strip(), model=get(ASR+'/health'),
                fixture_voice='Microsoft Huihui Desktop', fixtures=fixtures,
                source_sha256={p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES},
                images={s: json.loads(docker('inspect', container(s)))[0]['Image'] for s in ('asr','api','kafka','flink-taskmanager')},
                beam_size=5, compute_type='float16', checkpoint_interval_ms=5000,
                note='small model synthetic 4-phrase workload; no production availability or video-ingest capacity claim')

def body(index, run_id, stream='capacity'):
    return dict(segment_id=str(index), stream_id=stream, run_id=run_id,
                file_path='/data/fixtures/'+f'{index%4+1:02d}.wav', start_time_ms=index*5000, end_time_ms=(index+1)*5000)

def capacity(count):
    # Warm GPU and VAD before all comparable trials.
    warm = requests.post(ASR+'/transcribe', json=body(0, 'warmup'), timeout=120)
    warm.raise_for_status()
    result = dict(kind='direct_asr_capacity', metadata=metadata(), warmup=warm.json(), trials=[])
    for concurrency in (1,2,3,4,6):
        run_id = 'capacity-'+uuid.uuid4().hex[:10]
        runtime_samples = []
        stop = threading.Event()
        def sampler():
            while not stop.is_set():
                try:
                    runtime_samples.append(dict(at_ms=now_ms(), **get(ASR+'/runtime')))
                except Exception as exc:
                    runtime_samples.append(dict(at_ms=now_ms(), error=str(exc)))
                stop.wait(0.1)
        monitor = threading.Thread(target=sampler, daemon=True)
        monitor.start()
        def call(index):
            request = body(index, run_id)
            started = time.perf_counter()
            r = requests.post(ASR+'/transcribe', json=request, timeout=120)
            r.raise_for_status()
            return dict(request=request, response=r.json(), http_elapsed_ms=(time.perf_counter()-started)*1000)
        started = time.perf_counter()
        try:
            with concurrent.futures.ThreadPoolExecutor(concurrency) as pool:
                rows = list(pool.map(call, range(count)))
        finally:
            stop.set()
            monitor.join(4)
        trial = dict(concurrency=concurrency, count=count, elapsed_seconds=time.perf_counter()-started,
                     rows=rows, runtime_samples=runtime_samples)
        result['trials'].append(trial)
        print('capacity', concurrency, 'completed', count, 'requests', flush=True)
    return result

async def pipeline_fault(service, count, interval):
    target = container(service)
    run_id = 'fault-'+service+'-'+uuid.uuid4().hex[:8]
    samples, sent, events, producer_errors = [], [], [], []
    producer = AIOKafkaProducer(bootstrap_servers=BROKER, request_timeout_ms=10000, retry_backoff_ms=200, enable_idempotence=True)
    probe = AIOKafkaConsumer(bootstrap_servers=BROKER, group_id='flink-asr-transcription', enable_auto_commit=False)
    await producer.start()
    await probe.start()
    finished = asyncio.Event()
    jobs = await asyncio.to_thread(get, FLINK+'/jobs')
    jid = next(j['id'] for j in jobs['jobs'] if j['status'] == 'RUNNING')
    # Prove a completed checkpoint exists before restarting a worker.
    checkpoint = await asyncio.to_thread(get, FLINK+'/jobs/'+jid+'/checkpoints')
    if checkpoint.get('counts', {}).get('completed', 0) == 0:
        raise RuntimeError('wait for a completed checkpoint before faults')
    async def sample():
        while not finished.is_set():
            item = dict(at_ms=now_ms())
            for name, url in [('asr',ASR+'/runtime'), ('checkpoints',FLINK+'/jobs/'+jid+'/checkpoints')]:
                try:
                    payload = await asyncio.to_thread(get, url)
                    item[name] = {k:payload[k] for k in ('counts','latest') if k in payload} if name == 'checkpoints' else payload
                except Exception as exc:
                    item[name] = dict(error=str(exc))
            try:
                parts = [TopicPartition('audio-segment', i) for i in (0,1,2)]
                ends = await asyncio.wait_for(probe.end_offsets(parts), 2)
                commits = [await asyncio.wait_for(probe.committed(p), 2) for p in parts]
                item['offsets'] = [dict(partition=p.partition, end=ends[p], committed=c) for p,c in zip(parts,commits)]
                # An empty partition has zero records to consume; an uncommitted nonempty partition is unknown.
                item['lag'] = sum(max(ends[p]-(c or 0),0) for p,c in zip(parts,commits)) if all(c is not None or ends[p] == 0 for p,c in zip(parts,commits)) else None
            except Exception as exc:
                item['lag'] = None
                item['lag_error'] = str(exc)
            if len(samples) % 5 == 0:
                try:
                    gpu = await asyncio.to_thread(subprocess.run, ['nvidia-smi','--query-gpu=memory.used,memory.total,utilization.gpu','--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=2)
                    item['gpu_csv'] = gpu.stdout.strip() if gpu.returncode == 0 else None
                    job = await asyncio.to_thread(get, FLINK+'/jobs/'+jid)
                    vertex = next(v for v in job['vertices'] if 'Map' in v['name'])
                    item['backpressure'] = await asyncio.to_thread(get, FLINK+'/jobs/'+jid+'/vertices/'+vertex['id']+'/backpressure')
                except Exception as exc:
                    item['resource_error'] = str(exc)
            samples.append(item)
            try:
                await asyncio.wait_for(finished.wait(), 1)
            except asyncio.TimeoutError:
                pass
    async def fault():
        await asyncio.sleep(interval * 12)
        events.append(dict(action='stop_started', at_ms=now_ms()))
        try:
            await asyncio.to_thread(docker, 'stop', '--time', '1', target)
            events.append(dict(action='stopped', at_ms=now_ms()))
            await asyncio.sleep(3)
        finally:
            events.append(dict(action='start_started', at_ms=now_ms()))
            await asyncio.to_thread(docker, 'start', target)
            events.append(dict(action='started', at_ms=now_ms()))
    sample_task = asyncio.create_task(sample())
    fault_task = asyncio.create_task(fault())
    try:
        started = now_ms()
        for index in range(count):
            item = body(index, run_id, 'lab-'+service)
            item.update(created_at_ms=now_ms(), kafka_sent_at=now_ms())
            send_deadline = time.monotonic()+90
            while True:
                try:
                    record = await asyncio.wait_for(producer.send_and_wait('audio-segment', json.dumps(item, ensure_ascii=False).encode(), key=item['stream_id'].encode()), max(0.1,send_deadline-time.monotonic()))
                    break
                except Exception as exc:
                    producer_errors.append(dict(at_ms=now_ms(), segment_id=item['segment_id'], error=str(exc)))
                    if time.monotonic() >= send_deadline:
                        raise
                    # Fatal sequence/epoch errors poison this producer. Reconnect with
                    # a new producer identity; application IDs still deduplicate replay.
                    if type(exc).__name__ in ('OutOfOrderSequenceNumber', 'InvalidProducerEpoch', 'ProducerFenced'):
                        await asyncio.wait_for(producer.stop(), 5)
                        producer = AIOKafkaProducer(bootstrap_servers=BROKER, request_timeout_ms=10000, retry_backoff_ms=200, enable_idempotence=True)
                        await asyncio.wait_for(producer.start(), 15)
                    await asyncio.sleep(0.5)
            sent.append(dict(payload=item, partition=record.partition, offset=record.offset, acknowledged_at_ms=now_ms()))
            await asyncio.sleep(interval)
        await fault_task
        deadline = time.monotonic()+120
        rows = []
        while time.monotonic() < deadline:
            rows = await asyncio.to_thread(get, API+'/api/reliability/segments?run_id='+run_id+'&limit=10000')
            if len(rows) >= count and all(r['processed'] for r in rows):
                break
            await asyncio.sleep(1)
        events.append(dict(action='result_check_finished', at_ms=now_ms()))
        # Lag includes checkpoint commit delay; allow two intervals after all results arrive.
        await asyncio.sleep(12)
        return dict(kind='pipeline_fault', service=service, run_id=run_id, metadata=metadata(),
                    started_at_ms=started, finished_at_ms=now_ms(), interval_seconds=interval,
                    baseline_checkpoint=checkpoint, input_manifest=sent, results=rows, events=events, samples=samples, producer_errors=producer_errors)
    finally:
        if not fault_task.done():
            fault_task.cancel()
        await asyncio.to_thread(docker, 'start', target)
        finished.set()
        await sample_task
        await producer.stop()
        await probe.stop()

def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['capacity','asr','flink-taskmanager','kafka'])
    p.add_argument('--count', type=int, default=24)
    p.add_argument('--interval', type=float, default=1.3)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    if a.count < 16 or a.interval <= 0:
        p.error('at least 16 requests and positive interval required')
    out = ROOT/a.output
    out.parent.mkdir(parents=True, exist_ok=True)
    result = capacity(a.count) if a.mode == 'capacity' else asyncio.run(pipeline_fault(a.mode,a.count,a.interval))
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('saved', out, flush=True)

if __name__ == '__main__':
    main()
