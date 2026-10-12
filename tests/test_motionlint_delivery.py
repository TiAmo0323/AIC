"""Real import boundaries and recoverable downloads never become quality failures."""
import asyncio
import hashlib
import io
import json
from pathlib import Path
import numpy as np
import pytest
from fastapi import HTTPException, UploadFile
import motionlint.api as api
from motionlint.resources import fetch
from motionlint.jobs import Job


@pytest.mark.parametrize('kind', ['bytes','frames'])
def test_actual_import_limits_without_lowering_limits(tmp_path,monkeypatch,kind):
    monkeypatch.setitem(api.TASK_ROOTS,'import',tmp_path/'imports')
    if kind=='bytes': payload=io.BytesIO(b'\0'*(32*1024**2+1))
    else:
        payload=io.BytesIO();np.save(payload,np.zeros((12001,22,3),dtype=np.float32));payload.seek(0)
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.import_motion(files=[UploadFile(filename='large.npy',file=payload)],
            fps=30,unit_scale=1,up_axis=1,joint_mapping='{}'))
    assert error.value.status_code in {413,422}
    assert not list((tmp_path/'imports').glob('*/import.json'))


class Response(io.BytesIO):
    def __init__(self,body,status=200,headers=None):
        super().__init__(body);self.status=status;self.headers=headers or {}


def test_resume_checks_byte_range_and_complete_sha(tmp_path):
    content=b'abcdefgh';partial=tmp_path/'model.bin.part';partial.write_bytes(content[:3])
    spec={'path':'model.bin','url':'https://example.invalid/model.bin','sha256':hashlib.sha256(content).hexdigest()}
    def opener(request,**kwargs):
        assert request.get_header('Range')=='bytes=3-'
        return Response(content[3:],206,{'Content-Length':'5','Content-Range':'bytes 3-7/8'})
    result=fetch(spec,tmp_path,opener=opener,reserve_bytes=0)
    assert result['status']=='downloaded' and (tmp_path/'model.bin').read_bytes()==content
    assert not partial.exists()


@pytest.mark.parametrize('kind',['range','truncated','hash','network'])
def test_failed_resource_is_preserved_and_not_published(tmp_path,kind):
    partial=tmp_path/'model.bin.part';partial.write_bytes(b'abc')
    spec={'path':'model.bin','url':'https://example.invalid/model.bin','sha256':hashlib.sha256(b'abcdef').hexdigest()}
    def opener(request,**kwargs):
        if kind=='network':raise OSError('Offline')
        headers={'Content-Length':'3','Content-Range':'bytes 3-5/6'}
        if kind=='range':headers['Content-Range']='bytes 0-2/6'
        return Response(b'x' if kind=='truncated' else b'xxx' if kind=='hash' else b'def',206,headers)
    with pytest.raises((ValueError,OSError)):fetch(spec,tmp_path,opener=opener,reserve_bytes=0)
    assert partial.exists() and not (tmp_path/'model.bin').exists()


def test_pipeline_preflight_error_cannot_remain_queued(tmp_path,monkeypatch):
    from uuid import uuid4
    task_id=str(uuid4());folder=tmp_path/'imports'/task_id;folder.mkdir(parents=True)
    monkeypatch.setitem(api.TASK_ROOTS,'import',folder.parent)
    job=Job(tmp_path/'data')
    api._pipeline_worker(job,api.PipelineRequest(source='import',task_id=task_id))
    state=json.loads(job.path.read_text(encoding='utf-8'))
    assert state['status']=='failed' and state['error']
