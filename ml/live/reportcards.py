"""Score only real forecasts saved before a race, with no retrospective substitutes."""
from collections import defaultdict
import numpy as np
from ml.features.practice import parse_time
from ml.validation.metrics import assess

TARGETS={'winner':('probability',1),'podium':('podium_probability',3),'top10':('top10_probability',10)}
STAGES=['FP1','FP2','FP3','Q']


def latest_stages(predictions):
    latest={}
    for p in sorted(predictions,key=lambda p:parse_time(p['cutoff'])):
        if p.get('is_demo') is not False or parse_time(p['cutoff'])>=parse_time(p['race_start']): continue
        latest[p.get('stage','Q')]=p
    return latest


def score_snapshot(prediction,results):
    rows=prediction['drivers']; positions={r['driver_id']:int(r['position']) for r in results}
    if len(set(positions.values()))!=len(results) or sorted(positions.values())!=list(range(1,len(results)+1)):
        return {'status':'incomplete classification','targets':{}}
    if len(positions)!=len(results) or len({r['driver_id'] for r in rows})!=len(rows) or set(positions)!={r['driver_id'] for r in rows}:
        return {'status':'field mismatch','targets':{}}
    targets={}
    for target,(field,k) in TARGETS.items():
        if not all(d.get(field) is not None for d in rows): continue
        if sum(p<=k for p in positions.values())!=k: continue
        probability=[d[field] for d in rows]; labels=[int(positions[d['driver_id']]<=k) for d in rows]
        metric=assess([prediction['race_id']]*len(rows),labels,probability,k)
        picks=sorted(rows,key=lambda d:(-d[field],d['driver_id']))[:k]
        targets[target]={'metrics':metric,'picks':[{'driver_id':d['driver_id'],'name':d['name'],'probability':d[field],
            'position':positions[d['driver_id']],'correct':positions[d['driver_id']]<=k} for d in picks],
            'actual':[r for r in sorted(results,key=lambda r:int(r['position'])) if int(r['position'])<=k],
            'driver_scores':[{'driver_id':d['driver_id'],'name':d['name'],'probability':d[field],'actual':labels[i],
                'position':positions[d['driver_id']]} for i,d in enumerate(rows)]}
    return {'status':'scored' if targets else 'unsupported targets','targets':targets}


def race_card(race,predictions,evaluation):
    results=(evaluation or {}).get('results',[])
    latest=latest_stages(predictions)
    stages=[]
    for stage in STAGES:
        if stage not in latest: continue
        p=latest[stage]
        score=score_snapshot(p,results) if results else {'status':'awaiting classification','targets':{}}
        baselines=[]
        if results:
            for b in p.get('baselines') or []:
                scored=score_snapshot({**p,'drivers':b['drivers']},results)
                if scored['status']=='scored': baselines.append({'name':b['name'],'label':b['label'],'version':b['version'],'targets':scored['targets']})
        stages.append({'stage':stage,'cutoff':p['cutoff'],'model_version':p['model_version'],'outcomes_model_version':p.get('outcomes_model_version'),'baselines':baselines,**score})
    return {'race_id':race['race_id'],'race_name':race['name'],'scheduled_at':race['scheduled_at'],
        'status':'scored' if any(s['status']=='scored' for s in stages) else 'awaiting classification' if latest and not results else 'no recorded forecast',
        'stages':stages,'snapshot_count':len(predictions),'results':results,
        'policy':'Latest real pre-race snapshot per stage. Earlier revisions remain in forecast history. Full-field matches only. Classified top 3 / top 10, including classified non-finishers.'}


def overall(cards):
    grouped=defaultdict(list); paired=defaultdict(list); trend=[]
    for card in sorted(cards,key=lambda c:c['scheduled_at']):
        for stage in card['stages']:
            for target,details in stage['targets'].items():
                version=stage['model_version']
                if target!='winner': version+=' / '+(stage.get('outcomes_model_version') or 'unversioned outcome snapshot')
                grouped[(stage['stage'],version,target)].append((card['race_id'],details['driver_scores']))
                for baseline in stage.get('baselines',[]):
                    if target in baseline['targets']:
                        paired[(stage['stage'],version,target,baseline['name'],baseline['version'])].append((card['race_id'],details['driver_scores'],baseline['targets'][target]['driver_scores']))
                trend.append({'race_id':card['race_id'],'race_name':card['race_name'],'date':card['scheduled_at'],
                    'stage':stage['stage'],'model_version':version,'target':target,
                    'brier':details['metrics']['brier'],'binary_log_loss':details['metrics']['binary_log_loss']})
    groups=[]
    for (stage,version,target),races in grouped.items():
        ids=[]; y=[]; p=[]
        for rid,drivers in races:
            ids.extend([rid]*len(drivers)); y.extend(d['actual'] for d in drivers); p.extend(d['probability'] for d in drivers)
        groups.append({'stage':stage,'model_version':version,'target':target,'metrics':assess(ids,y,p,TARGETS[target][1])})
    baseline_groups=[]
    for (stage,version,target,name,baseline_version),races in paired.items():
        ids=[]; y=[]; model=[]; baseline=[]
        for rid,model_rows,base_rows in races:
            by_id={d['driver_id']:d for d in base_rows}
            ids.extend([rid]*len(model_rows)); y.extend(d['actual'] for d in model_rows)
            model.extend(d['probability'] for d in model_rows); baseline.extend(by_id[d['driver_id']]['probability'] for d in model_rows)
        k=TARGETS[target][1]
        baseline_groups.append({'stage':stage,'model_version':version,'target':target,'baseline':name,'baseline_version':baseline_version,
            'model_metrics':assess(ids,y,model,k),'baseline_metrics':assess(ids,y,baseline,k),'race_ids':[rid for rid,_,_ in races]})
    return {'groups':groups,'baseline_groups':baseline_groups,'trend':trend,'races_with_scored_forecasts':sum(c['status']=='scored' for c in cards),
        'completed_races':len(cards),'cards':[{k:v for k,v in c.items() if k not in {'results','stages'}}|{'stages':[{'stage':s['stage'],'status':s['status']} for s in c['stages']]} for c in cards],
        'notice':'Prospective saved forecasts only. No predictions are invented for races before recording began. Metrics are separated by stage and model version. Latest pre-race revision per stage; race-balanced binary scores with race-cluster intervals. Sparse samples do not establish calibration.'}
