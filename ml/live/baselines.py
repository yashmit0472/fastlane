"""Freeze simple race-coherent comparators at prediction time, never after results."""
import numpy as np
from ml.live.outcomes import constrained_marginals
from ml.features.build import historical_prior
from ml.training.evaluate import race_distribution

VERSION='prospective-baselines-v1'


def attach(forecast,raw,history,cutoff):
    drivers=forecast['drivers']; strengths=[]
    for d in drivers:
        average=(d.get('observations') or {}).get('recent_average_finish')
        strengths.append(float(np.exp(-(average if average is not None else 10.5)/5)))
    candidates=[('recent_form','Recent form',np.array(strengths),'exp(-earlier five-start average finish / 5); missing form uses 10.5')]
    if forecast['stage']=='Q' and all(d.get('grid') is not None for d in drivers):
        scores=np.array([historical_prior(history,raw['Circuit']['circuitId'],int(d['grid']),cutoff)[0] for d in drivers])
        candidates.append(('qualifying_only','Qualifying position',scores,'Smoothed earlier circuit/grid win rate using qualifying position; later penalties excluded'))
    output=[]
    for name,label,scores,method in candidates:
        win=race_distribution(scores); podium=constrained_marginals(win,win,3); top10=constrained_marginals(win,podium,10)
        output.append({'name':name,'label':label,'version':VERSION,'method':method,'available_at':cutoff.isoformat(),
            'drivers':[{'driver_id':d['driver_id'],'name':d['name'],'probability':float(win[i]),'podium_probability':float(podium[i]),'top10_probability':float(top10[i])} for i,d in enumerate(drivers)]})
    forecast['baselines']=output
    return forecast
