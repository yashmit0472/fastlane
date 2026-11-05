"""Parameter-only logistic inference. Does not import or execute sklearn code.

Supports the exact median-impute / standardize / one-hot pipelines trained here.
Unknown model layouts fail closed. Existing artifact checksums remain authoritative.
"""
import pickle
from pathlib import Path
from types import SimpleNamespace
import numpy as np

ROOT=Path(__file__).resolve().parents[2]


class ParameterRecord:
    def __new__(cls,*args,**kwargs): return super().__new__(cls)
    def __setstate__(self,state):
        if isinstance(state,dict): self.__dict__.update(state)
        elif isinstance(state,tuple):
            for part in state:
                if isinstance(part,dict): self.__dict__.update(part)
        else: raise ValueError('Unsupported parameter state')


class ParameterReader(pickle.Unpickler):
    def find_class(self,module,name):
        if module.startswith('sklearn.') and name in {'Pipeline','ColumnTransformer','SimpleImputer','MissingIndicator','StandardScaler','OneHotEncoder','LogisticRegression'}: return ParameterRecord
        if (module,name)==('builtins','slice'): return slice
        allowed={('numpy','dtype'),('numpy','ndarray'),('numpy','float64'),('numpy','int64'),('numpy._core.multiarray','_reconstruct'),('numpy._core.multiarray','scalar'),('numpy._core.numeric','_frombuffer'),('numpy.core.multiarray','_reconstruct'),('numpy.core.multiarray','scalar')}
        if (module,name) in allowed: return super().find_class(module,name)
        raise ValueError(f'Unsupported model parameter type: {module}.{name}')


class Preprocessor:
    def __init__(self,blocks): self.blocks=blocks
    def transform(self,frame):
        arrays=[]
        for b in self.blocks:
            if b['kind']=='numeric':
                x=frame[b['columns']].to_numpy(dtype=float,na_value=np.nan).copy(); missing=np.isnan(x)
                statistics=np.asarray(b['statistics'],dtype=float)
                x=np.where(missing,statistics,x)
                indicators=np.asarray(b['indicators'],dtype=int)
                if len(indicators): x=np.column_stack((x,missing[:,indicators].astype(float)))
                x=(x-np.asarray(b['mean'],dtype=float))/np.asarray(b['scale'],dtype=float)
                if not np.isfinite(x).all(): raise ValueError('Non-finite portable numeric features')
                arrays.append(x)
            else:
                for column,categories in zip(b['columns'],b['categories']):
                    values=frame[column].to_numpy(dtype=object)
                    arrays.append(np.column_stack([values==category for category in categories]).astype(float))
        return np.concatenate(arrays,axis=1)
    def get_feature_names_out(self):
        names=[]
        for b in self.blocks:
            if b['kind']=='numeric': names += [b['name']+'__'+c for c in b['columns']]+[b['name']+'__missingindicator_'+b['columns'][i] for i in b['indicators']]
            else: names += [b['name']+'__'+c+'_'+str(v) for c,values in zip(b['columns'],b['categories']) for v in values]
        return np.asarray(names,dtype=object)


class LinearModel:
    def __init__(self,blocks,coefficients,intercept):
        transform=Preprocessor(blocks); coef=np.asarray(coefficients,dtype=float).reshape(1,-1)
        if len(transform.get_feature_names_out())!=coef.shape[1] or not np.isfinite(coef).all() or not np.isfinite(intercept): raise ValueError('Unsupported linear dimensions/parameters')
        self.named_steps={'features':transform,'model':SimpleNamespace(coef_=coef,intercept_=np.array([float(intercept)]))}
    def decision_function(self,frame):
        return self.named_steps['features'].transform(frame)@self.named_steps['model'].coef_[0]+self.named_steps['model'].intercept_[0]
    def predict_proba(self,frame):
        score=self.decision_function(frame); probability=1/(1+np.exp(-np.clip(score,-709,709)))
        return np.column_stack((1-probability,probability))


def load_linear(path):
    path=Path(path).resolve()
    if not path.is_relative_to(ROOT/'ml/artifacts'): raise ValueError('Linear parameters must be a local model artifact')
    with path.open('rb') as stream: pipeline=ParameterReader(stream).load()
    steps=dict(pipeline.steps); transform=steps['features']; model=steps['model']; blocks=[]
    if transform.transformer_weights is not None or transform.remainder!='drop': raise ValueError('Unsupported column weighting/remainder')
    if not np.array_equal(model.classes_,[0,1]) or model.coef_.shape[0]!=1: raise ValueError('Expected binary logistic coefficients')
    for name,t,columns in transform.transformers_:
        if isinstance(t,str):
            if t!='drop': raise ValueError('Unsupported passthrough transformer')
            continue
        if hasattr(t,'steps'):
            parts=dict(t.steps)
            if set(parts)!={'imputer','scale'}: raise ValueError('Unsupported numeric pipeline')
            imp=parts['imputer']; scale=parts['scale']; stats=np.asarray(imp.statistics_,dtype=float)
            if imp.strategy!='median' or len(stats)!=len(columns) or not np.isfinite(stats).all(): raise ValueError('Unsupported imputation layout')
            indicators=imp.indicator_.features_.tolist() if imp.indicator_ is not None else []
            n=len(columns)+len(indicators)
            blocks.append({'kind':'numeric','name':name,'columns':list(columns),'statistics':stats.tolist(),'indicators':indicators,
                'mean':scale.mean_.tolist() if scale.with_mean else [0.]*n,'scale':scale.scale_.tolist() if scale.with_std else [1.]*n})
        else:
            if not hasattr(t,'categories_') or t.drop_idx_ is not None or t._infrequent_enabled or t.handle_unknown!='ignore': raise ValueError('Unsupported one-hot layout')
            blocks.append({'kind':'categorical','name':name,'columns':list(columns),'categories':[a.tolist() for a in t.categories_]})
    return LinearModel(blocks,model.coef_,model.intercept_[0])
