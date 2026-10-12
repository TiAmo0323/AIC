"""Forward kinematics retaining animated local positions on every joint."""
import numpy as np


def forward_positions(rotations, local_positions, parents):
    world=np.empty_like(rotations)
    positions=np.empty_like(local_positions)
    for joint,parent in enumerate(parents):
        if parent<0:
            world[...,joint,:,:]=rotations[...,joint,:,:]
            positions[...,joint,:]=local_positions[...,joint,:]
        else:
            world[...,joint,:,:]=world[...,parent,:,:] @ rotations[...,joint,:,:]
            positions[...,joint,:]=positions[...,parent,:]+np.einsum('...ij,...j->...i',world[...,parent,:,:],local_positions[...,joint,:])
    return positions,world
