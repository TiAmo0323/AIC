"""Freeze prompts/splits and download six attributed music inputs, not scores."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"reports/first_prize/study"
PROMPTS=[
 ("handshake","Two people face each other, shake their right hands, then release and stand still.","holdout"),
 ("highfive","Two people face each other and give each other a high five.","holdout"),
 ("wave","Two people stand apart and wave their right hands to greet each other.","development"),
 ("walk","Two people walk side by side at a normal pace.","development"),
 ("dance","Two people dance together with small steps and synchronized arm movements.","holdout"),
 ("bow","Two people face each other, bow politely, then straighten up.","development"),
 ("point","One person points to the left while the other person turns to look in that direction.","holdout"),
 ("sidestep","Two people stand side by side and take a small step to their right, then return.","holdout"),
]
MUSIC=[("Carefree","USUAN1400037"),("Life of Riley","USUAN1400054"),("Cipher","USUAN1100844"),
       ("Monkeys Spinning Monkeys","USUAN1400011"),("Sneaky Snitch","USUAN1100772"),("Wallpaper","USUAN1100843")]


def download(url,path):
    if not path.exists():
        with urllib.request.urlopen(url,timeout=90) as response:
            data=response.read()
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/"protocol.json"
    if path.exists():
        protocol=json.loads(path.read_text(encoding="utf-8"))
    else:
        rows=[]
        for group,(name,prompt,split) in enumerate(PROMPTS):
            for repeat in range(3):
                rows.append({"id":f"ig{group:02d}s{repeat}","source":"intergen","group":name,"split":split,
                             "seed":261002100+group*3+repeat,"prompt":prompt,"frames":180,"fps":30})
        for index,(title,isrc) in enumerate(MUSIC):
            rows.append({"id":f"lg{index:02d}","source":"lodge","split":"development" if index<2 else "holdout",
                         "title":title,"isrc":isrc,"fps":30,"clip_seconds":36,
                         "author":"Kevin MacLeod","license":"CC-BY-4.0",
                         "source_url":f"https://incompetech.com/music/royalty-free/index.html?Search=Search&isrc={isrc}",
                         "license_url":"https://incompetech.com/music/royalty-free/licenses/",
                         "changes":"First 36 seconds, converted to mono 22050 Hz WAV for model input",
                         "attribution":f'"{title}" Kevin MacLeod (incompetech.com). Licensed under Creative Commons: By Attribution 4.0, https://creativecommons.org/licenses/by/4.0/ . Cropped/converted for MotionLint evaluation.'})
        protocol={"schema_version":1,"status":"split_frozen_before_inspection","motions":rows,
                  "development_count":11,"holdout_count":19,
                  "export_holdout_ids":["ig00s0","ig01s0","ig04s0","ig06s0","lg02","lg03"],
                  "limitations":["Small sample; all six music recordings from one composer", "LODGE seed not controlled by current API; record upstream settings and do not claim seed reproducibility"],
                  "scoring":"One-to-one event matching at IoU >=0.5 after per-test/actor interval union; no score inspection until adjudicated labels and frozen code"}
        path.write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding="utf-8")
    licenses=OUT/"music/license-page.html"
    download("https://incompetech.com/music/royalty-free/licenses/",licenses)
    text=licenses.read_text(encoding="utf-8")
    if "By Attribution 4.0" not in text:
        raise ValueError("Music license statement changed; verify before using tracks")
    catalog_path=OUT/"music/pieces.json"
    download("https://incompetech.com/music/royalty-free/pieces.json",catalog_path)
    catalog=json.loads(catalog_path.read_text(encoding="utf-8"))
    if isinstance(catalog,dict):
        catalog=catalog.get("pieces",catalog.get("data",[]))
    records=[]
    ffmpeg=ROOT.parent/"HumanAction-runtime/bin/ffmpeg.exe"
    for entry in protocol["motions"]:
        if entry["source"]!="lodge":continue
        item=next(x for x in catalog if x["title"]==entry["title"])
        url="https://incompetech.com/music/royalty-free/mp3-royaltyfree/"+urllib.parse.quote(item["filename"])
        mp3=OUT/"music"/(entry["id"]+".mp3")
        audio=mp3.with_suffix(".wav")
        download(url,mp3)
        if not audio.exists():
            subprocess.run([str(ffmpeg),"-v","error","-y","-i",str(mp3),"-t","36","-ac","1","-ar","22050",str(audio)],check=True)
        records.append({**entry,"input_audio":str(audio),"download_url":url,"sha256":hashlib.sha256(audio.read_bytes()).hexdigest(),
                        "original_sha256":hashlib.sha256(mp3.read_bytes()).hexdigest(),"license_snapshot_sha256":hashlib.sha256(licenses.read_bytes()).hexdigest()})
        print(f"Prepared {entry['id']} {entry['title']}",flush=True)
    (OUT/"music/manifest.json").write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"protocol.sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest(),encoding="ascii")
    print("Frozen 30 entries: 11 development / 19 holdout; no quality inspection")

if __name__=="__main__":main()
