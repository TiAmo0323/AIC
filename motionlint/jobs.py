"""Durable serial local jobs; cancellation never publishes partial artifacts."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json
import os
from uuid import uuid4, UUID
from threading import RLock
from motionlint.cli.main import _write_json
from motionlint.resources import cache_root
_STATE_LOCK = RLock()


def data_root():
    return Path(os.environ.get('MOTIONLINT_DATA_DIR', cache_root() / 'tasks')).resolve()


class Cancelled(RuntimeError):
    pass


class Job:
    def __init__(self, root=None, job_id=None, kind='pipeline', *, create=True):
        self.root = Path(root or data_root()).resolve() / 'jobs'
        self.id = job_id or str(uuid4())
        if str(UUID(self.id)) != self.id:
            raise ValueError('Invalid job id')
        self.folder = self.root / self.id
        self.path = self.folder / 'state.json'
        if create:
            self.folder.mkdir(parents=True, exist_ok=False)
            self.state = {'schema_version': 3, 'job_id': self.id, 'kind': kind, 'status': 'queued',
                          'created_at': self.now(), 'owner_pid': os.getpid(), 'events': [], 'attempt': 1}
            self.update('queued')
        else:
            self.state = json.loads(self.path.read_text(encoding='utf-8'))

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat(timespec='seconds')

    def update(self, status=None, **fields):
        with _STATE_LOCK:
            if self.path.exists():
                self.state.update(json.loads(self.path.read_text(encoding='utf-8')))
            if status:
                self.state['status'] = status
            self.state.update(fields, updated_at=self.now())
            self.state['events'].append({'status': self.state['status'], 'stage': fields.get('stage'), 'at': self.now()})
            _write_json(self.path, self.state)

    def checkpoint(self, stage):
        if (self.folder / 'cancel.request').exists():
            self.update('cancelled', stage=stage, reason='Cancelled before publishing the next stage')
            raise Cancelled('Job cancelled')
        self.update('running', stage=stage, owner_pid=os.getpid())

    def cancel(self):
        (self.folder / 'cancel.request').write_text(self.now(), encoding='utf-8')
        self.update(cancel_requested=True)
        if self.state['status'] in {'queued', 'failed', 'interrupted'}:
            self.update('cancelled')

    def recover(self):
        if self.state['status'] == 'running':
            pid = self.state.get('owner_pid')
            try:
                if os.name == 'nt':
                    import ctypes
                    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
                    alive = bool(handle)
                    if handle:
                        ctypes.windll.kernel32.CloseHandle(handle)
                else:
                    os.kill(pid, 0)
                    alive = True
            except (OSError, TypeError):
                alive = False
            if not alive:
                self.update('interrupted', reason='Previous worker process ended before publishing a completed result')
        return self.state


def list_jobs(root=None):
    directory = Path(root or data_root()) / 'jobs'
    states = [Job(root, p.parent.name, create=False).recover() for p in directory.glob('*/state.json')]
    return sorted(states, key=lambda state: (state.get('created_at', ''), state['job_id']))
