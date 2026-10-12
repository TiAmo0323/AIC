"""Record actual workbench operations with the pinned Playwright CLI.

The CLI view contains captured subprocess output, not simulated commands. The
Kenney chapter replays the immutable predeclared actual-export evidence.
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--recording', type=Path, required=True)
    parser.add_argument('--url', default='http://127.0.0.1:8004')
    args = parser.parse_args()
    folder = args.recording.resolve()
    cfg = json.loads((folder / 'recording-inputs.json').read_text(encoding='utf-8'))
    cfg.update(url=args.url, cli_url='http://127.0.0.1:8005/cli.html',output=folder.as_posix(),frame_folder='frames-'+str(time.time_ns()))
    server = ThreadingHTTPServer(('127.0.0.1', 8005), partial(SimpleHTTPRequestHandler, directory=str(folder)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    cache = args.runtime.resolve() / 'review-tools'
    env = {**os.environ, 'npm_config_cache': str(cache / 'npm-cache'),
           'PLAYWRIGHT_BROWSERS_PATH': str(cache / 'playwright-browsers'),
           'PWTEST_DAEMON_SESSION_DIR': str(cache / 'playwright-daemons')}
    prefix = [shutil.which('npx.cmd' if os.name == 'nt' else 'npx'), '--yes', '--package', '@playwright/cli@0.1.22',
              'playwright-cli', '-s=motionlint-capture055']
    def execute(arguments, name):
        result = subprocess.run(prefix + arguments, env=env, cwd=ROOT, text=True, encoding='utf-8',
                                errors='replace', capture_output=True, timeout=480)
        log=folder/(name+'.log')
        if log.exists():log.replace(folder/(name+'.attempt-'+str(time.time_ns())+'.log'))
        log.write_text(result.stdout + result.stderr, encoding='utf-8')
        if result.returncode or '### Error' in result.stdout:
            raise RuntimeError('Recording command failed: ' + name)
        return result.stdout
    helper = '''const cfg=__CFG__;const frames=[],timeline=[];const epoch=Date.now();
      const capture=async()=>{const at=(Date.now()-epoch)/1000;const name=String(frames.length).padStart(5,'0')+'.png';
        await page.screenshot({path:cfg.output+'/'+cfg.frame_folder+'/'+name});frames.push({at,file:cfg.frame_folder+'/'+name});};
      const importFile=async path=>{
        const form=page.getByRole('region',{name:'导入动作数据',exact:true});
        if(!await form.count())await page.getByRole('button',{name:'导入动作',exact:true}).click();
        await form.locator('input[type=file]').setInputFiles(path);
        const r=page.waitForResponse(r=>r.url().endsWith('/v1/motionlint/imports')&&r.request().method()==='POST');
        await form.getByRole('button',{name:'导入并检查',exact:true}).click();
        const result=await r;if(!result.ok())throw new Error(await result.text());
        await page.getByRole('button',{name:'修复全部可修复项',exact:true}).waitFor();
        const data=await result.json();return data.task;
      };
      const hold=async(ms)=>{const stop=Date.now()+ms;while(Date.now()<stop){await capture();await page.waitForTimeout(140);}};
    '''.replace('__CFG__', json.dumps(cfg, ensure_ascii=False))
    chapters = [
        ('导入与实际动作播放', '''await page.goto(cfg.url);
          await importFile(cfg.defect);
          await page.getByRole('button',{name:'设置',exact:true}).first().click();
          const settings=page.getByRole('region',{name:'动作质检设置',exact:true});
          await settings.getByRole('checkbox',{name:'循环播放',exact:true}).check();
          await settings.getByRole('button',{name:'关闭',exact:true}).click();
          const raw=page.getByRole('region',{name:'raw 动作骨架预览',exact:true}).first();
          await raw.scrollIntoViewIfNeeded();await raw.getByRole('button',{name:'播放',exact:true}).click();await hold(18000);
          if(await raw.getByRole('button',{name:'暂停',exact:true}).count())await raw.getByRole('button',{name:'暂停',exact:true}).click();'''),
        ('问题区间、物理数值与阈值', '''const t=page.getByRole('region',{name:'动作问题时间轴',exact:true});
          await t.scrollIntoViewIfNeeded();await t.getByRole('button').first().click();await hold(18000);'''),
        ('有界修复与候选审查', '''await page.getByRole('button',{name:'修复全部可修复项',exact:true}).click();
          await page.getByRole('link',{name:'下载动作与完整报告 ZIP',exact:true}).waitFor({timeout:120000});
          await page.locator('#motionlint-repair-summary').scrollIntoViewIfNeeded();await hold(11000);
          await page.locator('.repair-trials').first().locator('summary').click();await hold(7000);'''),
        ('修复前后同帧联动播放', '''const compare=page.getByRole('region',{name:'修复前后骨架联动比较',exact:true});
          await compare.scrollIntoViewIfNeeded();await compare.getByRole('button',{name:'播放',exact:true}).click();await hold(24000);'''),
        ('下载与实际 BVH 重新导入', '''const download=page.waitForEvent('download');
          await page.getByRole('link',{name:'下载动作与完整报告 ZIP',exact:true}).click();
          await(await download).saveAs(cfg.output+'/recorded-repair-bundle.zip');
          await page.getByRole('button',{name:'将 BVH 重新导入复检',exact:true}).click();
          await page.getByRole('region',{name:'raw 动作骨架预览',exact:true}).first().scrollIntoViewIfNeeded();await hold(18000);'''),
        ('总分提高仍拒绝新增严重问题', '''const baseline=await importFile(cfg.regression_baseline);
          const candidate=await importFile(cfg.regression_candidate);
          await page.getByRole('combobox',{name:'选择基线任务',exact:true}).selectOption('import:'+baseline.task_id);
          await page.getByRole('combobox',{name:'选择候选任务',exact:true}).selectOption('import:'+candidate.task_id);
          const response=page.waitForResponse(r=>r.url().endsWith('/compare')&&r.request().method()==='POST');
          await page.getByRole('button',{name:'比较',exact:true}).click();const result=await(await response).json();
          if(result.status!=='REGRESSION DETECTED')throw new Error('Adverse candidate was not rejected');
          await page.locator('#motionlint-regression').scrollIntoViewIfNeeded();await hold(21000);'''),
        ('固定样本的实际 BVH 阶段复检', '''const jobs=page.getByRole('region',{name:'持久化完整流程任务',exact:true});
          const job=jobs.locator('article').filter({hasText:cfg.character_job_id.slice(0,8)});
          await job.getByRole('button',{name:'打开完成任务',exact:true}).click();
          await page.getByRole('combobox',{name:'检查阶段',exact:true}).selectOption('bvh');
          await page.getByRole('region',{name:'bvh 动作骨架预览',exact:true}).first().waitFor();
          await page.locator('.motionlint-panel').scrollIntoViewIfNeeded();await hold(18000);'''),
        ('实际 Kenney 角色播放与对应报告', '''await page.getByRole('combobox',{name:'检查阶段',exact:true}).selectOption('character');
          const video=page.locator('.result-video');await video.waitFor({timeout:30000});await video.scrollIntoViewIfNeeded();
          await video.evaluate(async el=>{el.muted=true;el.loop=true;await el.play();});await hold(26000);'''),
        ('独立安装包的实际 CLI 输出', '''await page.goto(cfg.cli_url);await hold(10000);
          await page.locator('section').last().scrollIntoViewIfNeeded();await hold(10000);''')]
    execute(['open', args.url], 'open')
    setup = folder / 'viewport.js'
    setup.write_text('async page => {await page.setViewportSize({width:1440,height:1000});}', encoding='utf-8')
    execute(['run-code', '--filename', str(setup)], 'viewport')
    # Sampling actual browser frames avoids the alpha CLI's video overlay and
    # context recording deadlocks. Frame timestamps preserve the real pace.
    frame_dir=folder/cfg['frame_folder']
    frame_dir.mkdir(exist_ok=False)
    try:
        pieces=[]
        for i,(title,code) in enumerate(chapters):
            pieces.append('{const at=(Date.now()-epoch)/1000;await capture();'+code+';timeline.push({start_seconds:at,end_seconds:(Date.now()-epoch)/1000,title:'+json.dumps(title,ensure_ascii=False)+'});}')
        file=folder/'capture-all.js'
        file.write_text('async page=>{'+helper+''.join(pieces)+';return {frames,timeline,recorded_seconds:(Date.now()-epoch)/1000,scope:"Actual browser frame sampling; no fabricated playback or user feedback"};}',encoding='utf-8')
        result=execute(['run-code','--filename',str(file)],'actual-capture')
        payload=json.loads(result.split('### Result\n',1)[1].split('\n### ',1)[0])
        (folder/'capture.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        (folder/'chapters.json').write_text(json.dumps(payload['timeline'],ensure_ascii=False,indent=2),encoding='utf-8')
        print('Actual browser frames recorded:',len(payload['frames']),'duration:',payload['recorded_seconds'],flush=True)
    finally:
        execute(['close'], 'close')
        server.shutdown()
    print('Actual recording saved:',folder/'capture.json',flush=True)


if __name__ == '__main__':main()
