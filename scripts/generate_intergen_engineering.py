"""Serial official InterGen inference, no renderer, dataset or platform API.

The checkpoint already contains the CLIP text weights. Construct its text
architecture from those shapes, avoiding an unnecessary vision-model download.
No inference network or sampling algorithm is replaced.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time

parser=argparse.ArgumentParser()
parser.add_argument('--source',type=Path,required=True)
parser.add_argument('--checkpoint',type=Path,required=True)
parser.add_argument('--selection',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--split',choices=('all','development','holdout'),default='all')
args=parser.parse_args()
source=args.source.resolve();checkpoint=args.checkpoint.resolve();selection=args.selection.resolve();output=args.output.resolve()
output.mkdir(parents=True,exist_ok=True)
os.chdir(source);sys.path.insert(0,str(source))
os.environ.setdefault('MPLBACKEND','Agg')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','2')
os.environ.setdefault('MKL_NUM_THREADS','2')
import numpy as np
import torch
import clip
from torch import nn
from clip.model import Transformer,LayerNorm

print("Libraries imported",flush=True)
torch.set_num_threads(8)
if not torch.cuda.is_available():raise RuntimeError('CUDA generation resource unavailable')
try:loaded=torch.load(checkpoint,map_location='cpu',weights_only=False,mmap=True)
except RuntimeError:loaded=torch.load(checkpoint,map_location='cpu',weights_only=False)
print("Checkpoint mapped",flush=True)
state={key.removeprefix('model.'):value for key,value in loaded['state_dict'].items()}
del loaded
embedding=state['token_embedding.weight']
vocab,width=embedding.shape
layers=max(int(key.split('.')[2]) for key in state if key.startswith('clip_transformer.resblocks.'))+1
context=state['positional_embedding'].shape[0]

print("CLIP text dimensions",vocab,width,layers,context,flush=True)

def text_only_clip(*unused,**options):
    module=nn.Module()
    mask=torch.empty(context,context,device="cpu");mask.fill_(float('-inf'));mask.triu_(1)
    module.token_embedding=nn.Embedding(vocab,width)
    module.transformer=Transformer(width,layers,width//64,attn_mask=mask)
    module.positional_embedding=nn.Parameter(torch.empty(context,width))
    module.ln_final=LayerNorm(width)
    module.dtype=torch.float32
    return module,None

clip.load=text_only_clip
from configs import get_config
from models import InterGen
from utils.utils import MotionNormalizer
cfg=get_config('configs/model.yaml')
print("Initializing official InterGen",flush=True)
with torch.device("meta"):
    model=InterGen(cfg)
print("Model initialized",sum(p.numel() for p in model.parameters()),flush=True)
incompatible=model.load_state_dict(state,strict=False,assign=True)
missing=set(incompatible.missing_keys)&set(dict(model.named_parameters()))
if missing:raise RuntimeError('Missing inference parameters: '+','.join(sorted(missing)))
del state,embedding
print("Checkpoint weights copied",flush=True)
model=model.to('cuda').eval()
print("CUDA model ready",flush=True)
normalizer=MotionNormalizer()
rows=json.loads(selection.read_text(encoding='utf-8'))['motions']
rows=[r for r in rows if r['source']=='intergen' and (args.split=='all' or r['split']==args.split)]
checkpoint_hash=hashlib.file_digest(checkpoint.open('rb'),'sha256').hexdigest()
receipts=[]
for row in rows:
    folder=output/'intergen'/row['id'];folder.mkdir(parents=True,exist_ok=True)
    record=folder/'generation.json'
    if record.exists():
        previous=json.loads(record.read_text(encoding='utf-8'))
        if previous.get('status')=='ready' and previous.get('checkpoint_sha256')==checkpoint_hash and previous.get('seed')==row['seed'] and all((folder/name).is_file() and hashlib.sha256((folder/name).read_bytes()).hexdigest()==sha for name,sha in previous['files'].items()):
            receipts.append(previous);print(row['id'],'verified existing',flush=True);continue
    started=time.perf_counter()
    receipt={**row,'checkpoint_sha256':checkpoint_hash,'upstream_commit':'b1750df4a859443b8a69329f759ce3a7503ae179',
             'clip_commit':'d05afc436d78f1c48dc0dbf8e5980a9d471f35f6','sampler':cfg.STRATEGY,'batch_size':1,
             'postprocessing':'None: raw denormalized positions, no Gaussian filtering',
             'evidence_type':'real_generator_no_human_labels'}
    try:
        random.seed(row['seed']);np.random.seed(row['seed']);torch.manual_seed(row['seed']);torch.cuda.manual_seed_all(row['seed'])
        torch.cuda.reset_peak_memory_stats()
        batch={'motion_lens':torch.full((1,1),row['frames'],dtype=torch.long,device='cuda'),'text':[row['prompt']]}
        with torch.inference_mode():generated=model.forward_test(batch)['output'][0]
        raw=normalizer.backward(generated.reshape(row['frames'],2,-1).cpu().numpy())
        positions=raw[...,:66].reshape(row['frames'],2,22,3)
        if not np.isfinite(positions).all():raise ValueError('Generator produced non-finite positions')
        for actor in range(2):np.save(folder/f'actor{actor+1}.npy',positions[:,actor],allow_pickle=False)
        np.save(folder/'raw_features.npy',raw,allow_pickle=False)
        receipt.update(status='ready',seconds=time.perf_counter()-started,peak_gpu_bytes=torch.cuda.max_memory_allocated(),
                       files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob('*.npy')})
        del batch,generated,raw,positions
    except Exception as exc:
        receipt.update(status='failed',error=f'{type(exc).__name__}: {exc}',seconds=time.perf_counter()-started)
        import traceback
        traceback.print_exc()
        torch.cuda.empty_cache()
    if record.exists():
        with (folder/"attempt-history.jsonl").open("a",encoding="utf-8") as history:
            history.write(record.read_text(encoding="utf-8").replace("\n", "")+"\n")
    record.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    receipts.append(receipt)
    (output/'generation-recovery.json').write_text(json.dumps({'records':receipts},indent=2),encoding='utf-8')
    print(row['id'],receipt['status'],round(receipt['seconds'],2),receipt.get('error',''),flush=True)
