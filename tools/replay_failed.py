"""Plan/execute failed-segment replay against the isolated lab, preserving identities."""
import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path
from aiokafka import AIOKafkaProducer
from tools.reliability_lab import BROKER, API, ROOT, container, get, now_ms

async def replay(source, output):
    raw = json.loads(source.read_text(encoding='utf-8'))
    failed = {str(e['segment_id']) for e in raw['results'] if e.get('status') != 'ok'}
    plan = [r['payload'] for r in raw['input_manifest'] if str(r['payload']['segment_id']) in failed]
    container('kafka')  # Verify that this broker belongs to the isolated project.
    producer = AIOKafkaProducer(bootstrap_servers=BROKER)
    await producer.start()
    acknowledgements = []
    try:
        for item in plan:
            r = await producer.send_and_wait('audio-segment', json.dumps(item,ensure_ascii=False).encode(), key=item['stream_id'].encode())
            acknowledgements.append(dict(segment_id=item['segment_id'], partition=r.partition, offset=r.offset, at_ms=now_ms()))
    finally:
        await producer.stop()
    deadline = time.monotonic()+90
    final = []
    while time.monotonic() < deadline:
        final = await asyncio.to_thread(get, API+'/api/reliability/segments?run_id='+raw['run_id']+'&limit=10000')
        if all(e.get('status') == 'ok' and e['processed'] for e in final) and len(final)==len(raw['input_manifest']):
            break
        await asyncio.sleep(1)
    result = dict(kind='failed_replay', parent_file=source.name, parent_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  started_at_ms=now_ms(), original_results=raw['results'], replay_plan=plan, acknowledgements=acknowledgements,
                  final_results=final, final_success_count=sum(e.get('status')=='ok' for e in final),
                  logical_result_count=len(final), replay_source='original input manifest; original IDs and timestamps preserved')
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('replayed',len(plan),'failed segments; final success',result['final_success_count'],'/',len(final))

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', required=True)
    p.add_argument('--apply', action='store_true', help='otherwise only print the replay plan')
    p.add_argument('--output', default='benchmarks/reliability/20261001/replay-asr.json')
    a = p.parse_args()
    source = ROOT/a.input
    raw = json.loads(source.read_text(encoding='utf-8'))
    if not a.apply:
        print(json.dumps([e['segment_id'] for e in raw['results'] if e.get('status')!='ok']))
    else:
        asyncio.run(replay(source,ROOT/a.output))

if __name__ == '__main__':
    main()
