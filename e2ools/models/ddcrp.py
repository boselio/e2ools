import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import pickle
import scipy.optimize as opt

class DDCRPEstimator():
    def __init__(self, decay):
        self.f = decay


    def fit(self, interactions, theta_init=10):
        #Calculate the sums for every denominator
        node_times = []
        scores = []
        max_receiver = 0
        for interaction in interactions:
            for r in interaction[1]:
                #Calculate distances from all nodes
                dists = self.f(interaction[0] - np.array(node_times))
                scores.append(sum(dists))

                if r > max_receiver:
                    max_receiver += 1

                node_times.append(interaction[0])

        self.theta = opt.fsolve(self._f_theta, theta_init, args=(scores, max_receiver))


    def _f_theta(self, theta, scores, max_receiver):
        val = np.sum(-2 / (np.array(scores) + theta))
        val += max_receiver / theta
        return val



def exp_decay(d, sigma=0.01):

    d = np.array(d)
    flags = d >= 0
    answer = np.zeros_like(d)
    answer[flags] = np.exp(-sigma * d[flags])

    return answer


def evaluate_probabilities(f, theta, data, times, debug=False):
    node_times = np.array([interaction[0] for interaction in data])
    node_labels = np.array([i for interaction in data for i in interaction[1]])
    node_set = set(node_labels)

    p_list = []
    for t in times:
        # Add jitter, because we only want the probabilities right BEFORE the interaction.
        distances = t - 1e-8 - node_times
        discounts = f(distances)
        degrees = np.bincount(node_labels, weights=discounts)

        if debug:
            # Check that all the previous degrees are > 0
            nonzero_degrees = degrees.nonzero()[0]
            assert set(nonzero_degrees) == set(
                np.arange(len(nonzero_degrees))), "Degrees are zero where they shouldn't."

        degrees = degrees[degrees > 0]

        probs = np.concatenate([degrees, [theta]])
        p_list.append(probs / probs.sum())

    return p_list

