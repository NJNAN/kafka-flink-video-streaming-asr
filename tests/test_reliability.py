import importlib.util
import json
import threading
from pathlib import Path
from unittest.mock import Mock
import pytest
from prometheus_client.parser import text_string_to_metric_families
from tools.slo_report import report

ROOT = Path(__file__).resolve().parents[1]
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

job = load('flink/transcription_job.py', 'job')
store = load('services/api/storage.py', 'store')
gate_module = load('services/asr/runtime_metrics.py', 'gate')

def test_retry_exhaustion_is_failed(monkeypatch):
    post = Mock(side_effect=TimeoutError('unavailable'))
    sleep = Mock()
    monkeypatch.setattr(job.requests, 'post', post)
    monkeypatch.setattr(job.time, 'sleep', sleep)
    result = json.loads(job.transcribe_segment(json.dumps(dict(segment_id='1', stream_id='s', run_id='r'))))
    assert result['status'] == 'error' and result['retry_count'] == 2
    assert result['error'] and job.is_failed_result(json.dumps(result))
    assert post.call_count == 3
    assert [c.args[0] for c in sleep.call_args_list] == [0.8, 1.6]

def test_permanent_http_error_not_retried(monkeypatch):
    response = Mock(status_code=404, text='missing')
    response.raise_for_status.side_effect = ValueError('404')
    post = Mock(return_value=response)
    monkeypatch.setattr(job.requests, 'post', post)
    result, error = job.call_asr_with_retry({})
    assert result['status'] == 'error' and post.call_count == 1 and '404' in error

def test_transient_then_success(monkeypatch):
    response = Mock(status_code=200, text='')
    response.json.return_value = dict(status='ok', text='成功')
    post = Mock(side_effect=[TimeoutError(), response])
    monkeypatch.setattr(job.requests, 'post', post)
    monkeypatch.setattr(job.time, 'sleep', Mock())
    result, error = job.call_asr_with_retry({})
    assert result['retry_count'] == 1 and not error

def test_invalid_success_payload_fails(monkeypatch):
    response = Mock(status_code=200, text='[]')
    response.json.return_value = []
    monkeypatch.setattr(job.requests, 'post', Mock(return_value=response))
    monkeypatch.setattr(job.time, 'sleep', Mock())
    assert job.call_asr_with_retry({})[0]['status'] == 'error'

def test_replay_changed_text_keeps_one_canonical_result(tmp_path):
    db = tmp_path / 'test.db'
    store.init_db(db)
    item = dict(stream_id='s', run_id='r', segment_id='1', text='first', status='ok')
    assert store.receive_raw_result(db, item)[0]
    store.mark_raw_processed(db, item)
    should_process, canonical = store.receive_raw_result(db, {**item, 'text': 'changed'})
    assert not should_process and canonical['text'] == 'first'
    assert store.raw_counts(db) == dict(unique_segments=1, replays=1, pending=0)

def test_crash_before_projection_retries_persisted_payload(tmp_path):
    db = tmp_path / 'test.db'
    store.init_db(db)
    item = dict(stream_id='s', run_id='r', segment_id='1', status='ok', text='durable')
    store.receive_raw_result(db, item)
    process, canonical = store.receive_raw_result(db, {**item, 'text': 'different'})
    assert process and canonical['text'] == 'durable'
    assert store.raw_counts(db)['pending'] == 1

def test_failed_then_success_is_promoted_and_run_id_isolated(tmp_path):
    db = tmp_path / 'test.db'
    store.init_db(db)
    item = dict(stream_id='s', run_id='r', segment_id='1', status='error')
    store.receive_raw_result(db, item)
    store.mark_raw_processed(db, item)
    assert store.receive_raw_result(db, {**item, 'status': 'ok'})[0]
    store.receive_raw_result(db, {**item, 'run_id': 'other'})
    assert store.raw_counts(db)['unique_segments'] == 2

def test_gate_counts_queue_errors_and_releases():
    gate = gate_module.InferenceGate()
    started = threading.Event()
    finished = threading.Event()
    def worker():
        started.set()
        with gate.measure():
            finished.set()
    with gate.measure() as first:
        thread = threading.Thread(target=worker)
        thread.start()
        assert started.wait(1)
        # Thread registers in queue before blocking; wait by condition, bounded by time.
        import time
        deadline = time.monotonic() + 1
        while gate.snapshot()['lock_queue_depth'] != 1 and time.monotonic() < deadline:
            time.sleep(0.001)
        assert gate.snapshot()['lock_queue_depth'] == 1
        assert not finished.is_set()
    thread.join(1)
    assert not thread.is_alive() and first['lock_hold_time_ms'] > 0
    with pytest.raises(ValueError):
        with gate.measure():
            raise ValueError('model failed')
    s = gate.snapshot()
    assert s['inference_count'] == 3 and s['inference_errors'] == 1 and s['lock_active'] == 0
    families = list(text_string_to_metric_families(gate.prometheus()))
    assert len(families) == 7
    assert all(s['wait_buckets'][i] <= s['wait_buckets'][i+1] for i in range(len(s['wait_buckets'])-1))

def test_slo_missing_and_replayed_results_not_hidden():
    item = dict(stream_id='s', run_id='r', segment_id='1', status='ok', end_to_end_time_ms=2)
    r = report([item, item], [('s', 'r', '1'), ('s', 'r', '2')])
    assert r['success']['sli'] == 0.5 and r['missing_inputs'] == 1
    assert r['success']['budget_remaining_fraction'] < 0

def test_slo_empty_and_unknown_latency():
    assert report([])['success']['sli'] is None
    r = report([dict(segment_id='1', status='ok')])
    assert r['unknown_latency_events'] == 1 and r['deadline']['good'] == 0
    assert r['missing_inputs'] is None

@pytest.mark.parametrize('reference,candidate', [('', ''), ('', '幻觉'), ('测试。', '测试！'), ('Kafka hello', 'kafka hello'), ('中文 Flink', '中 Flink'), ('hello world', 'hello')])
def test_edit_distance_matches_jiwer(reference, candidate):
    import jiwer
    from tools.evaluate_subtitles import normalize_text, tokenize_words, edit_distance
    for ref, hyp in ((list(normalize_text(reference)), list(normalize_text(candidate))),
                     (tokenize_words(normalize_text(reference, True)), tokenize_words(normalize_text(candidate, True)))):
        # Feed identical tokenization to jiwer; whitespace separator only after tokenization.
        result = jiwer.process_words(' '.join(ref), ' '.join(hyp))
        assert edit_distance(ref, hyp) == result.substitutions + result.deletions + result.insertions
