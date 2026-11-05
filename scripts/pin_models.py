"""Pin the currently selected, locally evaluated qualifying artifact without retraining."""
import json
from ml.live.refresh import choose_model,ROOT
from ml.live.outcomes import checksum

def main():
    path,report=choose_model()
    if not report or report['status']!='backtested': raise ValueError('No evaluated qualifying model')
    files={p.name:checksum(p) for p in path.parent.iterdir() if p.suffix in {'.cbm','.pkl'}}
    manifest={'schema':'qualifying-bundle-v1','report':path.relative_to(ROOT).as_posix(),'sha256':checksum(path),'artifacts':files,'model_version':report['model_version']}
    target=ROOT/'ml/artifacts/qualifying-active.json'; tmp=target.with_suffix('.tmp'); tmp.write_text(json.dumps(manifest,indent=2)); tmp.replace(target)
    print('Pinned',report['model_version'])

if __name__=='__main__': main()
