"""Race-balanced proper scores, calibration and race-cluster uncertainty."""
import numpy as np


def assess(race_ids,labels,probabilities,places):
    ids=np.asarray(race_ids); y=np.asarray(labels,dtype=float); p=np.asarray(probabilities,dtype=float)
    if not len(p) or p.shape!=y.shape or len(ids)!=len(p) or not np.isin(y,[0,1]).all() or not np.isfinite(p).all() or ((p<0)|(p>1)).any(): raise ValueError('Invalid evaluation arrays')
    races=np.unique(ids); ll=[]; bs=[]; hits=[]; weights=np.zeros(len(p))
    q=np.clip(p,1e-12,1-1e-12)
    for rid in races:
        mask=ids==rid; target=y[mask]; values=p[mask]
        if int(target.sum())!=places: raise ValueError('Incomplete outcome labels')
        weights[mask]=1/(len(races)*mask.sum())
        ll.append(float(np.mean(-target*np.log(q[mask])-(1-target)*np.log(1-q[mask]))))
        bs.append(float(np.mean((values-target)**2)))
        threshold=np.sort(values)[-places]; tied=np.isclose(values,threshold,atol=1e-12,rtol=0); above=(values>threshold)&~tied
        hits.append(float((target[above].sum()+target[tied].sum()*(places-above.sum())/tied.sum())/places))
    bins=[]; ece=0.
    for i in range(10):
        selected=(p>=i/10)&((p<(i+1)/10) if i<9 else p<=1)
        mass=float(weights[selected].sum())
        mean=float(np.average(p[selected],weights=weights[selected])) if mass else None
        observed=float(np.average(y[selected],weights=weights[selected])) if mass else None
        if mass: ece+=mass*abs(mean-observed)
        bins.append({'lower':i/10,'upper':(i+1)/10,'n':int(selected.sum()),'mean_probability':mean,'observed_rate':observed})
    rng=np.random.default_rng(42); draw=rng.integers(0,len(races),(300,len(races)))
    return {'races':len(races),'driver_predictions':len(p),'binary_log_loss':float(np.mean(ll)),
        'brier':float(np.mean(bs)),'top_k_recall':float(np.mean(hits)),'ece':float(ece),'reliability':bins,
        'brier_interval_95':np.quantile(np.asarray(bs)[draw].mean(axis=1),[.025,.975]).tolist(),
        'log_loss_interval_95':np.quantile(np.asarray(ll)[draw].mean(axis=1),[.025,.975]).tolist()}
