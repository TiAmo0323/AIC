"""Serve the wheel-bundled workbench without Node or generator processes."""
import os
from pathlib import Path


def serve(host='127.0.0.1', port=8003, data_dir=None, runtime=None, repo=None):
    if data_dir:
        os.environ['MOTIONLINT_DATA_DIR'] = str(Path(data_dir).resolve())
    if runtime:
        os.environ['MOTIONLINT_RUNTIME'] = str(Path(runtime).resolve())
    if repo:
        os.environ['MOTIONLINT_REPO'] = str(Path(repo).resolve())
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    from motionlint.api import app
    from motionlint.jobs import list_jobs
    static = Path(__file__).resolve().parent / 'static'
    if not (static / 'index.html').is_file():
        raise ValueError('Packaged workbench is missing. Build project and run scripts/package_workbench.py before building the wheel')
    list_jobs()
    if (static / 'assets').exists():
        app.mount('/assets', StaticFiles(directory=static / 'assets'), name='assets')
    @app.get('/', response_class=HTMLResponse)
    def index():
        content = (static / 'index.html').read_text(encoding='utf-8')
        return content.replace('<head>', '<head><script>window.MOTIONLINT_API_BASE=window.location.origin;window.MOTIONLINT_STANDALONE=true;</script>')
    # The API and injected index have priority over the confined asset fallback.
    app.mount('/', StaticFiles(directory=static), name='workbench-public')
    uvicorn.run(app, host=host, port=port)
