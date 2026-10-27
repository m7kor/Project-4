"""Lossless field-level pad fixture checks. No interpolation or analog quantization."""
import re
NEUTRAL=(65535,128,128,128,128)
PATTERN=re.compile(r'\[pad trace\] stage=guest\b.*?buttons=(-?\d+) lx=(-?\d+) ly=(-?\d+) rx=(-?\d+) ry=(-?\d+).*?host_ms=(\d+) ee_tick=(\d+)')
def parse_guest_trace(text):
    events=[]
    for line in text.splitlines():
        if '[pad trace] stage=guest' not in line:continue
        match=PATTERN.search(line)
        if not match:raise ValueError('Incomplete native guest input event')
        values=list(map(int,match.groups()))
        events.append({'tick':values[6],'host_ms':values[5],'state':tuple(values[:5])})
    if not events:raise ValueError('No native guest input events')
    return events
def field_replay(events,max_rows=1024):
    if not events:raise ValueError('No input capture')
    if max(event['tick'] for event in events)==0:
        raise ValueError('Unusable guest clock: every ee_tick is zero; interpolation cannot establish an exact field replay')
    if events[0]['state']!=NEUTRAL:raise ValueError('Missing initial neutral input state')
    if events[-1]['state']!=NEUTRAL:raise ValueError('Incomplete final active interval: release was not captured')
    changes=[];previous_host=-1
    for event in events:
        tick=event['tick'];state=tuple(event['state']);host=event['host_ms']
        if type(tick) is not int or not 0<=tick<2**64 or len(state)!=5 or not 0<=state[0]<=65535 or any(not 0<=axis<=255 for axis in state[1:]):raise ValueError('Invalid input range')
        if host<previous_host or (changes and tick<changes[-1]['tick']):raise ValueError('Nonmonotonic input clock')
        previous_host=host
        if changes and state==changes[-1]['state']:continue
        if changes and tick==changes[-1]['tick']:raise ValueError('Distinct input states in one guest field require a finer replay contract')
        changes.append({'tick':tick,'state':state})
    rows=[]
    for before,after in zip(changes,changes[1:]):
        if before['state']==NEUTRAL:continue
        rows.append([before['tick'],after['tick'],*before['state']])
    if not rows:raise ValueError('No active input intervals')
    if len(rows)>max_rows:raise ValueError('Native1024-row limit exceeded; do not quantize or drop events to manufacture a verified replay')
    return rows
