"""Signed SO(3) increments, including reversals and near-pi angles."""
import numpy as np


def increments_degrees(matrices):
    relative=matrices[1:] @ np.swapaxes(matrices[:-1],-1,-2)
    cosine=np.clip((np.trace(relative,axis1=-2,axis2=-1)-1)/2,-1.,1.)
    theta=np.arccos(cosine)
    skew=np.stack((relative[...,2,1]-relative[...,1,2],relative[...,0,2]-relative[...,2,0],relative[...,1,0]-relative[...,0,1]),axis=-1)
    factor=np.divide(theta,2*np.sin(theta),out=np.full_like(theta,.5),where=np.abs(np.sin(theta))>1e-7)
    result=skew*factor[...,None]
    for index in zip(*np.where(theta>np.pi-1e-5)):
        values,vectors=np.linalg.eig(relative[index])
        axis=np.real(vectors[:,np.argmin(np.abs(values-1.))]);axis/=np.linalg.norm(axis)
        if np.dot(axis,skew[index])<0:axis=-axis
        result[index]=axis*theta[index]
    return np.degrees(result)
