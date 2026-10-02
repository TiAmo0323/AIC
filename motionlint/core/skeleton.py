"""Legacy platform skeleton convention; provenance pending publication review.

Numeric proxy offsets preserve the frozen v3 geometry. They are not SMPL-X
model files or proof of redistribution permission.
"""
import numpy as np

SMPL_TO_BVH22 = [0, 1, 4, 7, 10, 2, 5, 8, 11, 3, 6, 9, 12, 15, 13, 16, 18, 20, 14, 17, 19, 21]
BVH_NAMES = [
    "Hips", "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToe",
    "RightUpLeg", "RightLeg", "RightFoot", "RightToe",
    "Spine", "Spine1", "Spine2", "Neck", "Head",
    "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand",
    "RightShoulder", "RightArm", "RightForeArm", "RightHand",
]
BVH_PARENTS = np.array(
    [-1, 0, 1, 2, 3, 0, 5, 6, 7, 0, 9, 10, 11, 12, 11, 14, 15, 16, 11, 18, 19, 20],
    dtype=np.int64,
)
BVH_OFFSETS = np.array(
    [
        [-0.001795, -0.223333, 0.028219], [0.069520, -0.091406, -0.006815],
        [0.034277, -0.375199, -0.004496], [-0.013596, -0.397961, -0.043693],
        [0.026358, -0.055791, 0.119288], [-0.067670, -0.090522, -0.004320],
        [-0.038290, -0.382569, -0.008850], [0.015774, -0.398415, -0.042312],
        [-0.025372, -0.048144, 0.123348], [-0.002533, 0.108963, -0.026696],
        [0.005487, 0.135180, 0.001092], [0.001457, 0.052922, 0.025425],
        [-0.002778, 0.213870, -0.042857], [0.005152, 0.064970, 0.051349],
        [0.070682, 0.113999, -0.034942], [0.131151, 0.020969, -0.017528],
        [0.253106, 0.006564, -0.026820], [0.234605, 0.008539, -0.006011],
        [-0.068819, 0.113488, -0.034688], [-0.134624, 0.021356, -0.020510],
        [-0.254539, 0.007921, -0.026620], [-0.237194, 0.009012, -0.006273],
    ],
    dtype=np.float64,
)
