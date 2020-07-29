from scipy.special import logit, logsumexp, expit, beta
import numpy as np
from collections import defaultdict, Counter
import bisect
from scipy.stats import multivariate_normal as mvn
import matplotlib.pyplot as plt
import seaborn as sns
import scipy.stats as st
import pickle
from copy import deepcopy
from bisect import bisect_right, bisect_left


class TemporalProbabilities():
    def __init__(self, sticks, receivers, created_times, created_sticks, change_times):
        self.stick_dict = defaultdict(list)
        self.arrival_times_dict = defaultdict(list)
        self.created_times = np.array(created_times)
        for r, (ct, s) in enumerate(zip(created_times, created_sticks)):
            self.arrival_times_dict[r].append(ct)
            self.stick_dict[r].append(s)

        for s, r, ct in zip(sticks, receivers, change_times):
            if r == -1:
                continue
            self.arrival_times_dict[r].append(ct)
            self.stick_dict[r].append(s)

    def get_receiver_stick_trace(self, r, upper_limit):
        x = np.repeat(self.arrival_times_dict[r], 2)[1:]
        x = np.concatenate([x, [upper_limit]])
        y = np.repeat(self.stick_dict[r], 2)

        return x, y

    def get_receiver_probability_trace(self, r, upper_limit):
        # Times to test
        x = []
        for i in range(r + 1):
            x.extend(self.arrival_times_dict[i])
        x.sort()
        y = np.array([self.get_probability(r, t) for t in x])


        x = np.repeat(x, 2)[1:]
        x = np.concatenate([x, [upper_limit]])
        y = np.repeat(y, 2)

        return x, y

    def get_stick(self, r, t, return_index=False):
        if t <= self.created_times[r]:
            index = -1
            s = 1
        else:
            index = bisect.bisect_left(self.arrival_times_dict[r], t) - 1
            s = self.stick_dict[r][index]

        if return_index:
            return s, index
        else:
            return s

    def insert_change(self, r, t, s):
        insert_index = bisect_right(self.arrival_times_dict[r], t)
        self.arrival_times_dict[r].insert(insert_index, t)
        self.stick_dict[r].insert(insert_index, s)
        return

    def delete_change(self, r, t):
        delete_index = self.arrival_times_dict[r].index(t)
        del self.arrival_times_dict[r][delete_index]
        del self.stick_dict[r][delete_index]

    def get_last_switch(self, r, t, return_index=False):
        index = bisect_left(self.arrival_times_dict[r], t) - 1
        if return_index:
            return self.arrival_times_dict[r][index], index
        else:
            return self.arrival_times_dict[r][index]

    def get_next_switch(self, r, t, return_index=False):
        index = bisect_right(self.arrival_times_dict[r], t)
        if index == len(self.arrival_times_dict[r]):
            index == -1
            switch_time = -1
        else:
            switch_time = self.arrival_times_dict[r][index]
        if return_index:
            return switch_time, index
        else:
            return switch_time


def update_sticks_v2(tp_initial, change_times, recs_initial, interactions, alpha, theta):
    num_recs = len(set([r for t, recs in interactions for r in recs]))

    rec_choice = np.zeros_like(change_times)
    stick_choice = np.zeros_like(change_times)
    interaction_times = np.array([interaction[0] for interaction in interactions])
    max_time = interactions[-1][0]
    #created_set = set()

    permuted_inds = np.random.permutation(len(change_times))
    for ind in permuted_inds:
        ct = change_times[ind]
        #created_recs = np.where(tp_initial.created_times < ct)[0]

        #update_set = set(created_recs).difference(created_set)
        #created_set.update(update_set)
        #for r in list(update_set):
            #draw beta
        #    end_time = tp_initial.get_next_switch(r, tp_initial.created_times[r])
        #    if end_time == -1:
        #        end_time = max_time

        #    begin_ind = bisect_left(interaction_times, tp_initial.created_times[r])
        #    end_ind = bisect_right(interaction_times, end_time)
        #    recs, degrees = np.unique([r for interaction in interactions[begin_ind:end_ind] for r in interaction[1]],
        #                              return_counts=True)
        #    degree_dict = dict(zip(recs, degrees))
        #    a = 1 - alpha + degree_dict[r] - 1
        #    b = theta + (r + 1) * alpha + np.sum([v for (k,v) in degree_dict.items() if k > r])
        #    tp_initial.stick_dict[r][0] = np.random.beta(a, b)

        num_created_recs = len(tp_initial.created_times[tp_initial.created_times < ct])
        probs = np.array([tp_initial.get_stick(r, ct) for r in range(num_created_recs)] + [1])
        probs[1:] = probs[1:] * np.cumprod(1 - probs[:-1])
        new_choice = np.random.choice(num_created_recs+1, p=probs)

        rec_choice[ind] = new_choice

        if new_choice == recs_initial[ind]:
            #Draw the beta
            end_time = tp_initial.get_next_switch(new_choice, ct)
            if end_time == -1:
                end_time = max_time
            begin_ind = bisect_left(interaction_times, ct)
            end_ind = bisect_right(interaction_times, end_time)
            recs, degrees = np.unique([r for interaction in interactions[begin_ind:end_ind] for r in interaction[1]],
                                      return_counts=True)
            degree_dict = dict(zip(recs, degrees))
            if new_choice not in degree_dict:
                degree_dict[new_choice] = 0
            a = 1 - alpha + degree_dict[new_choice]
            b = theta + (new_choice + 1) * alpha + np.sum([v for (k, v) in degree_dict.items() if k > new_choice])
            change_index = tp_initial.arrival_times_dict[new_choice].index(ct)
            tp_initial.stick_dict[new_choice][change_index] = np.random.beta(a, b)

        if recs_initial[ind] != -1:
            # Delete the current change
            r_delete = int(recs_initial[ind])
            tp_initial.delete_change(r_delete, ct)
            # redraw the beta that we had deleted.

            begin_time, change_ind = tp_initial.get_last_switch(r_delete, ct, return_index=True)
            end_time = tp_initial.get_next_switch(r_delete, ct)
            if end_time == -1:
                end_time = max_time

            begin_ind = bisect_left(interaction_times, begin_time)
            end_ind = bisect_right(interaction_times, end_time)
            recs, degrees = np.unique([r for interaction in interactions[begin_ind:end_ind] for r in interaction[1]],
                                      return_counts=True)
            degree_dict = dict(zip(recs, degrees))
            if r_delete not in degree_dict:
                degree_dict[r_delete] = 0
            if begin_time == tp_initial.created_times[r_delete]:
                degree_dict[r_delete] -= 1
            a = 1 - alpha + degree_dict[r_delete]
            b = theta + (r_delete + 1) * alpha + np.sum([v for (k, v) in degree_dict.items() if k > r_delete])
            tp_initial.stick_dict[r_delete][change_ind] = np.random.beta(a, b)

        if new_choice == num_created_recs:
            rec_choice[ind] = -1
            stick_choice[ind] = -1
        else:
            # Draw the beta backward
            begin_time, change_ind = tp_initial.get_last_switch(new_choice, ct, return_index=True)
            begin_ind = bisect_left(interaction_times, begin_time)
            end_ind = bisect_right(interaction_times, ct)
            recs, degrees = np.unique([r for interaction in interactions[begin_ind:end_ind] for r in interaction[1]],
                                      return_counts=True)
            degree_dict = dict(zip(recs, degrees))
            if new_choice not in degree_dict:
                degree_dict[new_choice] = 0
            if begin_time == tp_initial.created_times[new_choice]:
                degree_dict[new_choice] -= 1
            a = 1 - alpha + degree_dict[new_choice]
            b = theta + (new_choice + 1) * alpha + np.sum([v for (k, v) in degree_dict.items() if k > new_choice])
            tp_initial.stick_dict[new_choice][change_ind] = np.random.beta(a, b)


            #Draw the beta forward
            end_time = tp_initial.get_next_switch(new_choice, ct)
            if end_time == -1:
                end_time = max_time
            begin_ind = bisect_left(interaction_times, ct)
            end_ind = bisect_right(interaction_times, end_time)
            recs, degrees = np.unique([r for interaction in interactions[begin_ind:end_ind] for r in interaction[1]],
                                      return_counts=True)
            degree_dict = dict(zip(recs, degrees))
            if new_choice not in degree_dict:
                degree_dict[new_choice] = 0
            a = 1 - alpha + degree_dict[new_choice]
            b = theta + (new_choice + 1) * alpha + np.sum([v for (k, v) in degree_dict.items() if k > new_choice])
            tp_initial.insert_change(new_choice, ct, np.random.beta(a, b))

    # Reupdate all the initial sticks, in case they did not get updated.
    for r in range(num_recs):
            #draw beta
        end_time = tp_initial.get_next_switch(r, tp_initial.created_times[r])
        if end_time == -1:
            end_time = max_time

        begin_ind = bisect_left(interaction_times, tp_initial.created_times[r])
        end_ind = bisect_right(interaction_times, end_time)
        recs, degrees = np.unique([r for interaction in interactions[begin_ind:end_ind] for r in interaction[1]],
                                     return_counts=True)
        degree_dict = dict(zip(recs, degrees))
        a = 1 - alpha + degree_dict[r] - 1
        b = theta + (r + 1) * alpha + np.sum([v for (k,v) in degree_dict.items() if k > r])
        tp_initial.stick_dict[r][0] = np.random.beta(a, b)

    return tp_initial, rec_choice, stick_choice


def get_created_sticks(interactions, theta, alpha):
    nodes, degrees = np.unique([i for interaction in interactions for i in interaction[1]], return_counts=True)
    degree_dict = dict(zip(nodes, degrees))

    num_recs = len(nodes)
    created_sticks = np.zeros(num_recs)

    for r in nodes:
        a = 1 - alpha + degree_dict[r]
        b = theta + (r + 1) * alpha + np.sum([v for (k, v) in degree_dict.items() if k > r])
        created_sticks[r] = np.random.beta(a, b)

    return created_sticks


def get_created_times(interactions):
    created_times = []
    counter = 0
    for interaction in interactions:
        for i in interaction[1]:
            if i == len(created_times):
                created_times.append(interaction[0])

    return np.array(created_times)


def run_chain(save_dir, num_times, created_times, created_sticks, change_times, interactions, alpha,
              theta, seed=None):
    np.random.seed(seed)

    tp_initial = TemporalProbabilities(-1 * np.ones_like(change_times), -1 * np.ones_like(change_times),
                                         created_times, created_sticks, change_times)
    rec_choice = np.ones_like(change_times) * -1

    for t in range(num_times):
        if t % 100 == 0:
            print(t)
        tp_initial, rec_choice, stick_choice = update_sticks_v2(tp_initial, change_times, rec_choice,
                                                                    interactions, alpha, theta)
        if t >= num_times / 2:
            file_dir = save_dir / '{}.pkl'.format(t - int(num_times / 2))
            with file_dir.open('wb') as outfile:
                pickle.dump(tp_initial, outfile)
    return

