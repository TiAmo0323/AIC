"""Grouped dynamic fixtures with analytic contact labels and reference solutions.

This generator never calls a detector, a repair, or support estimation. All
derivatives used to verify labels are computed in the independent truth kernel.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
from motionlint.benchmark.fixtures import standing, TESTS
from motionlint.adapters.intergen_adapter import JOINT_NAMES, PARENTS

FAMILIES = ('turn', 'straight_walk', 'direction_change', 'jump_landing', 'dance_step', 'two_actor_contact')


def _ease(x):
    return x**3 * (10 - 15*x + 6*x*x)


def _knee(hip, ankle, upper, lower):
    delta = ankle - hip
    distance = np.linalg.norm(delta)
    if distance > upper + lower - 1e-8:
        raise ValueError('Procedural reference leg is outside its analytic reach')
    direction = delta / distance
    along = (upper*upper - lower*lower + distance*distance) / (2*distance)
    bend = np.array([0., 0., 1.])
    bend -= direction * np.dot(bend, direction)
    bend /= np.linalg.norm(bend)
    return hip + direction*along + bend*np.sqrt(max(0., upper*upper-along*along))


def trajectory(family, seed, frames=240, fps=30.):
    rng = np.random.default_rng(630000 + seed)
    scale = rng.uniform(.96, 1.04)
    rest = standing(1)[0] * scale
    positions = standing(frames) * scale
    contacts = np.ones((frames, 4), dtype=float)
    t = np.arange(frames) / fps
    active = np.clip((t - 1.5) / 4., 0, 1)
    phase = _ease(active)
    root = rest[0] + np.stack([np.zeros(frames), -.045*scale + np.zeros(frames), np.zeros(frames)], axis=1)
    yaw = .75 * phase if family == 'turn' else .3*np.sin(np.pi*phase) if family == 'direction_change' else np.zeros(frames)
    if family in ('straight_walk', 'direction_change', 'dance_step'):
        root[:, 2] += .18*scale*phase
        root[:, 0] += (.07 if family == 'direction_change' else .025)*scale*np.sin(np.pi*phase)
    jump = .20*scale*np.sin(np.pi*phase)**4 if family == 'jump_landing' else np.zeros(frames)
    root[:, 1] += jump
    for f in range(frames):
        c, s = np.cos(yaw[f]), np.sin(yaw[f])
        rotate = np.array([[c,0,s],[0,1,0],[-s,0,c]])
        positions[f] = (rest-rest[0]) @ rotate.T + root[f]
        # A slowly moving wrist chain preserves lengths and avoids face contact.
        angle = .10*np.sin(2*np.pi*phase[f])
        ca, sa = np.cos(angle), np.sin(angle)
        arm_rot = np.array([[ca,-sa,0],[sa,ca,0],[0,0,1]])
        for arm, elbow, wrist in ((16,18,20),(17,19,21)):
            pivot = positions[f,arm].copy()
            positions[f,[elbow,wrist]] = (positions[f,[elbow,wrist]]-pivot) @ arm_rot.T+pivot
        for side,(hip,knee,ankle,toe,local) in enumerate(((1,4,7,10,0),(2,5,8,11,1))):
            ankle_target = rest[ankle].copy()
            foot_lift = 0.
            if family in ('straight_walk','direction_change','dance_step'):
                # Two slow swing intervals, prescribed independently of speeds.
                left, right = ((.12,.42) if side == 0 else (.56,.86))
                u = np.clip((phase[f]-left)/(right-left),0.,1.)
                ankle_target[2] += .18*scale*_ease(u)
                if left < phase[f] < right:
                    foot_lift = .09*scale*np.sin(np.pi*u)**4
                    contacts[f,local] = contacts[f,local+2] = 0.
            ankle_target[1] += jump[f] + foot_lift
            if jump[f] > .001:
                contacts[f,local] = contacts[f,local+2] = 0.
            upper = np.linalg.norm(rest[knee]-rest[hip])
            lower = np.linalg.norm(rest[ankle]-rest[knee])
            positions[f,knee] = _knee(positions[f,hip], ankle_target, upper, lower)
            positions[f,ankle] = ankle_target
            positions[f,toe] = ankle_target + (rest[toe]-rest[ankle])
    if family == 'two_actor_contact':
        partner = positions.copy()
        partner[..., 0] += 1.65*scale
        positions = np.stack([positions, partner], axis=1)
        contacts = np.stack([contacts, contacts.copy()], axis=1)
    else:
        positions, contacts = positions[:,None], contacts[:,None]
    return positions, contacts, {'scale':float(scale), 'family':family, 'seed':seed, 'floor_height_m':0.,
                                'contact_origin':'Analytic stance/swing/flight schedule; no detector calls'}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(output):
    output = Path(output)
    if (output/'manifest.json').exists():
        raise ValueError('Dataset version already exists; use a new directory')
    output.mkdir(parents=True,exist_ok=True)
    rows = []
    for family in FAMILIES:
        for seed in range(5):
            group = f'{family}_{seed}'
            base, contacts, context = trajectory(family, seed)
            directory = output/group
            directory.mkdir()
            np.save(directory/'reference.npy', base, allow_pickle=False)
            np.save(directory/'contacts.npy', contacts, allow_pickle=False)
            for kind in (*TESTS, 'clean'):
                for strength in range(2 if kind=='clean' else 3):
                    p = base.copy()
                    actor = seed % p.shape[1]
                    start, end = 72+seed*3, 90+seed*3
                    if kind in ('foot_sliding', 'ground_contact'):
                        # Prescribed contacts select a stance episode during the
                        # trajectory. Neither detector nor support estimator is
                        # consulted. Jump samples use their landing episode.
                        planted = np.all(contacts[:,actor,[2,3]] > .5,axis=1)
                        starts = [f for f in range(1,len(p)-20) if planted[f-1:f+19].all()]
                        start = min(starts, key=lambda f:abs(f-125-seed*3))
                        end = start+18
                    joints, quantity = [], 0.
                    repairable, reference = False, base
                    if kind=='temporal_continuity':
                        quantity = (.24,.32,.40)[strength]
                        p[start:,actor,:,0] += quantity
                        end, joints = start, [0]
                    elif kind=='skeleton_integrity':
                        quantity = (.18,.30,.45)[strength]
                        bone = p[start:end+1,actor,20]-p[start:end+1,actor,18]
                        p[start:end+1,actor,20] += quantity*bone
                        joints = [18,20]
                    elif kind=='foot_sliding':
                        quantity = (.20,.28,.36)[strength]
                        drift = np.clip(np.arange(len(p))-(start-1),0,end-start+1)*quantity/30.
                        p[:,actor,:,0] += drift[:,None]
                        reference = base.copy()
                        reference[:,actor,:,0] += drift[-1]/2
                        repairable = float(drift[-1]/2) <= .15
                        joints = [10,11]
                    elif kind=='ground_contact':
                        quantity = (.06,.09,.12)[strength]
                        p[start:end+1,actor,:,1] -= quantity
                        joints = [7,8,10,11]
                    elif kind=='collision':
                        quantity = (.10,.06,.02)[strength]
                        p[start:end+1,actor,20] = p[start:end+1,actor,15]+[quantity,0,0]
                        joints = [20,15]
                    elif kind=='motion_jerk':
                        quantity = (.010,.016,.025)[strength]
                        p[start:end+1,actor,20,2] += quantity*np.where(np.arange(end-start+1)%2,1.,-1.)
                        end += 3
                        joints = [20]
                    elif strength:
                        p[...,0] += .12
                        reference = p.copy()
                    identifier = f'{group}_{kind}_{strength}'
                    path = directory/f'{kind}_{strength}.npy'
                    np.save(path,p,allow_pickle=False)
                    reference_path = directory/f'{kind}_{strength}.reference.npy'
                    if repairable:
                        np.save(reference_path, reference, allow_pickle=False)
                    events = [] if kind=='clean' else [{'test_name':kind,'actor_id':actor,'joint_ids':joints,
                                                       'start_frame':start,'end_frame':end,'uncertain':False}]
                    rows.append({'id':identifier,'group_id':group,'input':path.relative_to(output).as_posix(),
                                 'reference':(reference_path if repairable else directory/'reference.npy').relative_to(output).as_posix(),
                                 'contacts':(directory/'contacts.npy').relative_to(output).as_posix(),
                                 'split':'development' if seed<2 else 'holdout','fps':30.,'sha256':_sha(path),
                                 'reference_sha256':_sha(reference_path if repairable else directory/'reference.npy'),
                                 'context':context,'events':events,'evaluated_tests':list(TESTS) if kind=='clean' else [kind],
                                 'injection':{'type':kind,'strength':strength,'quantity':quantity},
                                 'repairable_by_known_reference':repairable,
                                 'reference_max_shift_m':float(np.linalg.norm(p-reference,axis=-1).max()),
                                 'evidence_type':'analytic_injection_not_human_truth'})
    manifest = {'schema_version':3,'dataset_version':output.name,'motions':rows,
                'selection':'Seed 0/1 development; seed 2/3/4 holdout, grouped by original trajectory',
                'counts':{'total':600,'development':240,'holdout':360,'normal_controls':60},
                'scope':'Non-target collateral defects on injected samples are unlabelled, not true negatives.'}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return manifest
