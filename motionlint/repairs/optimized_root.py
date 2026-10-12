"""Bounded convex foot/root subproblem with explicit numerical diagnostics."""
from __future__ import annotations
import importlib.util
import numpy as np
from motionlint.core.foot_support import estimate_support
from motionlint.repairs.foot_lock import repair_foot_sliding


def available():
    return importlib.util.find_spec('cvxpy') is not None and importlib.util.find_spec('clarabel') is not None


def budget_diagnostic(motion, settings, budget):
    support=estimate_support(motion,settings)
    axes=[a for a in range(3) if a!=motion.metadata.get('up_axis',1)]
    witnesses=[]
    for actor in range(motion.actor_count):
        for local,joint in enumerate(support.feet):
            mask=support.intervals[:,actor,local]
            ids=np.flatnonzero(mask)
            for segment in np.split(ids,np.flatnonzero(np.diff(ids)>1)+1):
                if not len(segment):continue
                frames=np.arange(segment[0],segment[-1]+2)
                # A positive witness remains a valid proof when sampled. Avoid
                # quadratic allocations for long imported support intervals.
                if len(frames) > 512:
                    frames = frames[np.unique(np.linspace(0, len(frames)-1, 512).astype(int))]
                p=motion.positions[frames,actor,joint][:,axes]
                distances=np.linalg.norm(p[:,None,:]-p[None,:,:],axis=-1)
                dt=np.abs(frames[:,None]-frames[None,:])/motion.fps
                margin=distances-2*budget-settings['horizontal_speed_m_s']*dt
                i,j=np.unravel_index(np.argmax(margin),margin.shape)
                if margin[i,j]>1e-6:
                    witnesses.append({'actor_id':actor,'joint_id':joint,'start_frame':int(min(frames[i],frames[j])),
                        'end_frame':int(max(frames[i],frames[j])),'chord_distance_m':float(distances[i,j]),
                        'minimum_required_budget_m':float((distances[i,j]-settings['horizontal_speed_m_s']*dt[i,j])/2),
                        'configured_budget_m':budget,'positive_infeasibility_margin_m':float(margin[i,j])})
    return {'status':'proven_budget_insufficient_for_strict_fixed_support_speed' if witnesses else 'no_budget_impossibility_proven',
            'scope':'Triangle-inequality necessity for original support, fixed FPS and per-point displacement balls; not proof about every possible repair',
            'witnesses':witnesses}


def repair_optimized(motion, issues, *, support_settings, max_correction_m=.15, optimizer_mode='coupled', raw=None, **unused):
    if not available():raise ValueError('Optimization extension unavailable; install motionlint[optimize]')
    import cvxpy as cp
    support=estimate_support(motion,support_settings)
    axes=[a for a in range(3) if a!=motion.metadata.get('up_axis',1)]
    lookup={name:i for i,name in enumerate(motion.joint_names)}
    affected={i.actor_id for i in issues}
    t=motion.frame_count
    correction=np.zeros((t,motion.actor_count,2,2));roots=np.zeros((t,motion.actor_count,3))
    records=[]
    for actor in range(motion.actor_count):
        if actor not in affected:continue
        root=cp.Variable((t,2))
        feet=[cp.Variable((t,2)) for _ in range(2)]
        constraints=[cp.norm(root,axis=1)<=max_correction_m]
        loss=0.;slacks=[]
        for side,(prefix,delta) in enumerate(zip(('Left','Right'),feet)):
            constraints.append(cp.norm(delta,axis=1)<=max_correction_m)
            if optimizer_mode=='shared':constraints.append(delta==root)
            hip,knee,ankle,toe=[lookup[prefix+s] for s in ('UpLeg','Leg','Foot','Toe')]
            if optimizer_mode!='shared':
                length=np.linalg.norm(motion.positions[:,actor,knee]-motion.positions[:,actor,hip],axis=-1)+np.linalg.norm(motion.positions[:,actor,ankle]-motion.positions[:,actor,knee],axis=-1)
                distance=motion.positions[:,actor,ankle]-motion.positions[:,actor,hip]
                columns=[distance[:,axis]+delta[:,axes.index(axis)]-root[:,axes.index(axis)] if axis in axes else distance[:,axis] for axis in range(3)]
                constraints.append(cp.norm(cp.vstack(columns).T,axis=1)<=length)
            for joint in (ankle,toe):
                local=support.feet.index(joint)
                indices=np.flatnonzero(support.intervals[:,actor,local])
                if not len(indices):continue
                original_delta=np.diff(motion.positions[:,actor,joint][:,axes],axis=0)[indices]
                changed=original_delta+delta[indices+1]-delta[indices]
                path=cp.norm(changed,axis=1)
                slack=cp.Variable(len(indices),nonneg=True)
                constraints.append(path<=support_settings['horizontal_speed_m_s']/motion.fps*.99999+slack)
                slacks.append(slack)
                # A foot already stationary must remain stationary on those intervals.
                clean=np.flatnonzero(np.linalg.norm(original_delta,axis=1)<1e-9)
                if len(clean):constraints.append(changed[clean]==0)
                loss+=cp.sum(path)*20+cp.sum(slack)*2000
            loss+=cp.sum_squares(delta-root)*(.2 if optimizer_mode=='coupled' else 2.)
            loss+=cp.sum_squares(delta)*.01
            if t>=4:loss+=cp.sum_squares(delta[3:]-3*delta[2:-1]+3*delta[1:-2]-delta[:-3])*10
        loss+=cp.sum_squares(root)*.001
        if t>=4:loss+=cp.sum_squares(root[3:]-3*root[2:-1]+3*root[1:-2]-root[:-3])*100
        problem=cp.Problem(cp.Minimize(loss),constraints)
        try:
            problem.solve(solver='CLARABEL',max_iter=150,tol_gap_abs=1e-8,tol_feas=1e-8,tol_gap_rel=1e-8)
        except cp.error.SolverError as exc:
            raise ValueError(f'Convex subproblem solver failed; no mathematical impossibility established: {exc}') from exc
        if problem.status not in ('optimal','optimal_inaccurate') or root.value is None:
            raise ValueError(f'Convex subproblem status {problem.status}; this does not prove the full repair has no solution')
        roots[:,actor][:,axes]=root.value
        for side in range(2):correction[:,actor,side]=feet[side].value
        records.append({'actor_id':actor,'solver':'Clarabel','cvxpy_version':cp.__version__,'status':problem.status,
                        'objective':float(problem.value),'iterations':problem.solver_stats.num_iters,
                        'solve_seconds':problem.solver_stats.solve_time,'max_speed_slack_m_per_frame':max((float(s.value.max()) for s in slacks),default=0.)})
    candidate,candidate_raw,detail=repair_foot_sliding(motion,issues,raw=raw,support_settings=support_settings,
                max_correction_m=max_correction_m,anchor_method='interval',center_method='bounds',root_method='support',
                root_follow=True,contact_correction=correction,root_correction=roots)
    detail.update(method='Bounded convex foot/root trajectories followed by two-bone IK',optimizer_mode=optimizer_mode,
                  solver_status=records,constraint_diagnostic=budget_diagnostic(motion,support_settings,max_correction_m))
    return candidate,candidate_raw,detail
