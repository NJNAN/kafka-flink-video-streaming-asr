"""Plot only recorded samples; missing lag remains a gap."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
folder = ROOT/'benchmarks/reliability/20261001'
data = json.loads((folder/'summary.json').read_text(encoding='utf-8'))
out = ROOT/'docs/assets/reliability'
out.mkdir(parents=True,exist_ok=True)
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
capacity = next(e for e in data['experiments'] if e['kind']=='direct_asr_capacity')['trials']
x = [t['concurrency'] for t in capacity]
fig, axes = plt.subplots(1,2,figsize=(11,3.6),layout='constrained')
axes[0].plot(x,[t['throughput'] for t in capacity],'o-',color='#0d9488')
axes[0].set(xlabel='Concurrent HTTP workers',ylabel='Segments / second',title='Throughput plateaus',ylim=(0,4.5),xticks=x)
axes[1].plot(x,[t['p95_ms'] for t in capacity],'o-',label='HTTP P95',color='#2563eb')
axes[1].plot(x,[t['wait_p95_ms'] for t in capacity],'s--',label='Lock wait P95',color='#d97706')
axes[1].set(xlabel='Concurrent HTTP workers',ylabel='Milliseconds',title='Queueing grows',xticks=x)
axes[1].legend(frameon=False)
for ax in axes: ax.grid(alpha=.18)
fig.savefig(out/'capacity.png',dpi=180)
plt.close(fig)
fig, axes = plt.subplots(3,1,figsize=(10,7),layout='constrained')
for ax, service in zip(axes,['asr','flink-taskmanager','kafka']):
    raw = json.loads((folder/('fault-'+service+'.json')).read_text(encoding='utf-8'))
    origin = raw['started_at_ms']
    x = [(s['at_ms']-origin)/1000 for s in raw['samples']]
    y = [s['lag'] if s.get('lag') is not None else float('nan') for s in raw['samples']]
    ax.plot(x,y,'o-',markersize=3,color='#2563eb',label='Committed lag')
    stop = next(e['at_ms'] for e in raw['events'] if e['action']=='stop_started')
    start = next(e['at_ms'] for e in raw['events'] if e['action']=='start_started')
    ax.axvspan((stop-origin)/1000,(start-origin)/1000,color='#dc2626',alpha=.15,label='Stop / offline')
    last_ack = max(r['acknowledged_at_ms'] for r in raw['input_manifest'])
    ax.axvline((last_ack-origin)/1000,color='#0d9488',linestyle='--',label='Last input ACK')
    ax.set(title=service,ylabel='Lag (records)',xlabel='Seconds since trial start')
    ax.grid(alpha=.18)
    ax.legend(frameon=False,loc='upper right',fontsize=8)
fig.savefig(out/'fault-lag.png',dpi=180)
print('Saved',out)
