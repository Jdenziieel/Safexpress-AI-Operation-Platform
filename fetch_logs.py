import sys, io, boto3
from datetime import datetime, timezone
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

LOG_GROUPS = [
    '/aws/lambda/safexpressops-dynamic-mapping-wrapper',
    '/aws/lambda/safexpressops-dynamic-mapping-agent',
]
logs = boto3.client('logs', region_name='ap-southeast-1')

def fmt(ms): return datetime.fromtimestamp(ms/1000, tz=timezone.utc).isoformat()

def list_streams(lg, n=5):
    r = logs.describe_log_streams(logGroupName=lg, orderBy='LastEventTime', descending=True, limit=n)
    return r['logStreams']

def get_events(lg, ls):
    events, tok = [], None
    while True:
        kw = dict(logGroupName=lg, logStreamName=ls, startFromHead=True, limit=10000)
        if tok: kw['nextToken'] = tok
        r = logs.get_log_events(**kw)
        events.extend(r['events'])
        nt = r.get('nextForwardToken')
        if nt == tok or not r['events']: break
        tok = nt
    return events

if len(sys.argv) > 2:
    lg, ls = sys.argv[1], sys.argv[2]
    print('=== ' + lg + ' / ' + ls + ' ===')
    for e in get_events(lg, ls):
        print(fmt(e['timestamp']) + ' | ' + e['message'].rstrip())
else:
    for lg in LOG_GROUPS:
        print('\n=== ' + lg + ' ===')
        for s in list_streams(lg):
            print('  stream=' + s['logStreamName'] + ' last=' + fmt(s['lastEventTimestamp']) + ' bytes=' + str(s.get('storedBytes', 0)))