from scipy.special import logit, logsumexp, expit, beta, betaln, gamma, digamma
import numpy as np
from collections import defaultdict, Counter
import bisect
from scipy.stats import multivariate_normal as mvn, expon
import matplotlib.pyplot as plt
import matplotlib.backends.backend_pdf
import seaborn as sns
import scipy.stats as st
import pickle
from copy import deepcopy
from bisect import bisect_right, bisect_left
import os
from functools import partial
import pathlib
import time
from concurrent.futures import ProcessPoolExecutor
import math
from ..utils import plot_event_times

class TemporalProbabilities():
    def __init__(self, sticks, receivers, created_times, created_sticks, change_times):
        self.stick_dict = defaultdict(list)
        self.arrival_times_dict = defaultdict(list)
        self.created_times = np.array(created_times)
        for r, (ct, s) in enumerate(zip(created_times, created_sticks)):
            self.arrival_times_dict[r].append(ct)
            self.stick_dict[r].append(s)

        for s, r, ct in zip(sticks, receivers, change_times):
            self.arrival_times_dict[r].append(ct)
            self.stick_dict[r].append(s)

    def get_receiver_stick_trace(self, r, upper_limit):
        x = np.array(self.arrival_times_dict[r])
        y = np.array(self.stick_dict[r])
        y = y[x <= upper_limit]
        x = x[x <= upper_limit]
        x = np.repeat(x, 2)[1:]
        y = np.repeat(y, 2)
        x = np.concatenate([x, [upper_limit]])

        return x, y

    def get_receiver_probability_trace(self, r, upper_limit):
        print("This is probably broken. Don't Use!")
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

    def get_probability_traces(self):
        times = [t for v in self.arrival_times_dict.values() for t in v]
        times = np.array(times)
        times.sort()

        num_times = len(times)
        num_recs = len(self.created_times)
        true_stick_array = np.zeros((num_times, num_recs))

        for r in range(num_recs):
            stick_list = []
            sticks_ind = np.digitize(times, self.arrival_times_dict[r], right=False) - 1
            sticks = np.array(self.stick_dict[r])[sticks_ind]
            sticks[times < self.created_times[r]] = 0
            true_stick_array[:, r] = sticks

        true_prob_array = true_stick_array.copy()
        true_prob_array[:, 1:] = true_prob_array[:, 1:] * np.cumprod(1 - true_prob_array[:, :-1], axis=1)

        return times, true_prob_array


    def get_stick(self, r, t, return_index=False):
        if t < self.created_times[r]:
            index = -1
            s = 1
        else:
            index = bisect.bisect_left(self.arrival_times_dict[r], t) - 1
            s = self.stick_dict[r][index]

        if return_index:
            return s, index
        else:
            return s

    def get_probability(self, r, t):
        if r != -1:
            prob = self.get_stick(r, t)
            for j in range(r):
                prob = prob * (1 - self.get_stick(j, t))
        else:
            num_recs = (self.created_times <= t).sum() 
            prob = np.prod([1 - self.get_stick(j, t) for j in range(num_recs)])
            
        return prob

    def insert_change(self, r, t, s):
        insert_index = bisect_right(self.arrival_times_dict[r], t)
        self.arrival_times_dict[r].insert(insert_index, t)
        self.stick_dict[r].insert(insert_index, s)
        return

    def delete_change(self, r, t):
        delete_index = self.arrival_times_dict[r].index(t)
        del self.arrival_times_dict[r][delete_index]
        del self.stick_dict[r][delete_index]

    def move_change(self, r, t, t_new):
        change_index = self.arrival_times_dict[r].index(t)
        self.arrival_times_dict[r][change_index] = t_new

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

    def get_arrival_times(self):
        num_recs = len(self.created_times)

        nodes, arrival_times = zip(*[(k, t) for (k, v) in self.arrival_times_dict.items()
                                for t in v[1:]])
        nodes = list(nodes)
        arrival_times = list(arrival_times)

        if len(self.arrival_times_dict[-1]) > 0:
            arrival_times.append(self.arrival_times_dict[-1][0])
            nodes.append(-1)

        arrival_times = np.array(arrival_times)
        sorted_inds = arrival_times.argsort()
        arrival_times = arrival_times[sorted_inds]
        nodes = np.array(nodes)[sorted_inds]

        return arrival_times, nodes

    def generate_trace_pdf(self, save_dir, interactions=None, r_list='all'):
        if interactions is not None:
            max_time = interactions[-1][0]
            unique_nodes, degrees = np.unique([i for interaction in 
                                               interactions for i in interaction[1]],
                                              return_counts=True)
        
        if r_list == 'all':
            r_list = np.arange(len(self.created_times))
        elif r_list[:3] == 'top':
            number_of_plots = int(r_list[3:])
            r_list = unique_nodes[np.argsort(degrees)[::-1][:number_of_plots]]

        num_pages = math.ceil(len(r_list) / 10)

        r_counter = 0

        data_color = 'C2'

        times, probabilities = self.get_probability_traces()
        with matplotlib.backends.backend_pdf.PdfPages(save_dir) as pdf:
            for p in range(num_pages):
                fig, axs = plt.subplots(5,2, figsize=(8.5, 11))
                for k in range(10):
                    r = r_list[r_counter]
                    i, j = np.unravel_index(k, [5, 2])
                    if i == 0 and j == 1:
                        #use these for the legend
                        true_label = 'Probabilities'
                        data_label = 'Data'
                    else:
                        true_label = None
                        confidence_label = None
                        mean_label = None

                    axs[i, j].plot(times, probabilities[:, r], color='k', 
                        linewidth=2, label=true_label)
                    
                    if interactions is not None:
                        plot_event_times(interactions, r, axs[i, j], color=data_color)

                    if i == 0 and j == 1:
                        axs[i, j].legend()
                    
                    axs[i, j].set_title('Receiver {}'.format(r))
                    r_counter += 1
                    if r_counter == len(r_list):
                        break

                fig.tight_layout()
                pdf.savefig(fig)
                plt.close(fig)
        return


class FastInteractions():
    #Purpose of class is to wrap interactions so that they can be accessed via slicing 
    #and unique receiver counting very quickly.
    def __init__(self, interactions):
        self.interaction_times = np.array([interaction[0] for interaction in interactions])

        index_list = []
        flattened_interactions = []
        repeated_index_list = []
        counter = 0
        for i, interaction in enumerate(interactions):
            index_list.append(counter)
            flattened_interactions.extend(interaction[1])
            repeated_index_list.extend([counter] * len(interaction[1]))
            counter += len(interaction[1])

        #Add one more to index list, in the case that a time is greater than 
        #any of the interaction times (see get_degrees).
        index_list.append(counter)

        self.index_array = np.array(index_list)
        self.flattened_interactions = np.array(flattened_interactions)

        self.created_times = {}
        for r in np.unique(self.flattened_interactions):
            self.created_times[r] = repeated_index_list[np.argmax(flattened_interactions == r)]


    def get_degrees(self, begin_time, end_time):
        #Get degrees much quicker than a list comprehension could.
        begin_i = np.searchsorted(self.interaction_times, begin_time, side='left')
        end_i = np.searchsorted(self.interaction_times, end_time, side='right')

        begin_ind = self.index_array[begin_i]
        end_ind = self.index_array[end_i]
        recs, degrees = np.unique(self.flattened_interactions[begin_ind:end_ind],
                                    return_counts=True)
        return recs, degrees


def draw_beta(interactions, tp, begin_time, alpha, theta, r):
    recs, degrees = np.unique([r for interaction in interactions for r in interaction[1]],
                              return_counts=True)
    degree_dict = dict(zip(recs, degrees))

    if r not in degree_dict:
        degree_dict[r] = 0
    if begin_time == tp.created_times[r]:
        degree_dict[r] -= 1


    a = 1 - alpha + degree_dict[r]
    b = theta + (r + 1) * alpha + np.sum([v for (k, v) in degree_dict.items() if k > r])

    return np.random.beta(a, b)


def draw_beta_speedy(interactions, begin_time, end_time, alpha, theta, r):
    recs, degrees = interactions.get_degrees(begin_time, end_time)

    degree_dict = dict(zip(recs, degrees))

    if r not in recs:
        r_degrees = degrees[recs == r]
    else:
        r_degrees = 0 

    if begin_time == interactions.created_times[r]:
        r_degrees -= 1

    a = 1 - alpha + r_degrees
    sum_ind = np.argmax(recs > r)
    b = theta + (r + 1) * alpha + np.sum(degrees[sum_ind:])

    return np.random.beta(a, b)


def update_sticks_v2(tp_initial, interactions, alpha, theta):

    num_recs = len(set([r for t, recs in interactions for r in recs]))
    recs_initial, change_times = zip(*[(r, t) for (r, v) in tp_initial.arrival_times_dict.items() 
                                        for t in v[1:]])
    change_times = list(change_times)
    recs_initial = list(recs_initial)


    if len(tp_initial.arrival_times_dict[-1]) > 0:
        change_times.append(tp_initial.arrival_times_dict[-1][0])
        recs_initial.append(-1)

    change_times = np.array(change_times)
    sorted_inds = change_times.argsort()
    change_times = change_times[sorted_inds]
    recs_initial = np.array(recs_initial)[sorted_inds]

    rec_choice = np.zeros_like(change_times)
    stick_choice = np.zeros_like(change_times)
    interaction_times = np.array([interaction[0] for interaction in interactions])
    max_time = interactions[-1][0]
    #created_set = set()

    permuted_inds = np.random.permutation(len(change_times))

    for ind in permuted_inds:

        ct = change_times[ind]

        num_created_recs = len(tp_initial.created_times[tp_initial.created_times < ct])
        probs = np.array([tp_initial.get_stick(r, ct) for r in range(num_created_recs)] + [1])
        probs[1:] = probs[1:] * np.cumprod(1 - probs[:-1])

        new_choice = np.random.choice(num_created_recs+1, p=probs)

        if new_choice == recs_initial[ind]:
            if new_choice == num_created_recs:
                #Do nothing
                continue
            #Draw the beta
            end_time = tp_initial.get_next_switch(new_choice, ct)
            if end_time == -1:
                end_time = max_time
            begin_ind = bisect_left(interaction_times, ct)
            end_ind = bisect_right(interaction_times, end_time)

            new_stick = draw_beta(interactions[begin_ind:end_ind], tp_initial, ct, alpha, theta, new_choice)

            change_index = tp_initial.arrival_times_dict[new_choice].index(ct)
            tp_initial.stick_dict[new_choice][change_index] = new_stick

        else:
            r_delete = int(recs_initial[ind])
            tp_initial.delete_change(r_delete, ct)
        
            if r_delete != -1:
                # redraw the beta that we had deleted.
                begin_time, change_ind = tp_initial.get_last_switch(r_delete, ct, return_index=True)
                end_time = tp_initial.get_next_switch(r_delete, ct)
                if end_time == -1:
                    end_time = max_time

                begin_ind = bisect_left(interaction_times, begin_time)
                end_ind = bisect_right(interaction_times, end_time)

                new_stick = draw_beta(interactions[begin_ind:end_ind], tp_initial, begin_time, alpha, theta, r_delete)

                tp_initial.stick_dict[r_delete][change_ind] = new_stick

            if new_choice == num_created_recs:
                rec_choice[ind] = -1
                stick_choice[ind] = -1
                tp_initial.insert_change(-1, ct, -1.0)

            else:
                # Draw the beta backward
                begin_time, change_ind = tp_initial.get_last_switch(new_choice, ct, return_index=True)
                begin_ind = bisect_left(interaction_times, begin_time)
                end_ind = bisect_right(interaction_times, ct)
                
                new_stick = draw_beta(interactions[begin_ind:end_ind], tp_initial, begin_time, alpha, theta, new_choice)

                tp_initial.stick_dict[new_choice][change_ind] = new_stick

                #Draw the beta forward
                end_time = tp_initial.get_next_switch(new_choice, ct)
                if end_time == -1:
                    end_time = max_time
                begin_ind = bisect_left(interaction_times, ct)
                end_ind = bisect_right(interaction_times, end_time)

                new_stick = draw_beta(interactions[begin_ind:end_ind], tp_initial, ct, alpha, theta, new_choice)

                tp_initial.insert_change(new_choice, ct, new_stick)

    # Reupdate all the initial sticks, in case they did not get updated.
    for r in range(num_recs):
            #draw beta
        end_time = tp_initial.get_next_switch(r, tp_initial.created_times[r])
        if end_time == -1:
            end_time = max_time

        begin_ind = bisect_left(interaction_times, tp_initial.created_times[r])
        end_ind = bisect_right(interaction_times, end_time)

        new_stick = draw_beta(interactions[begin_ind:end_ind], tp_initial, tp_initial.created_times[r], alpha, theta, r)

        tp_initial.stick_dict[r][0] = new_stick

    return tp_initial, rec_choice, stick_choice


def update_sticks_new_jump_update(tp_initial, interactions, alpha, theta):

    num_recs = len(set([r for t, recs in interactions for r in recs]))
    recs_initial, change_times = zip(*[(r, t) for (r, v) in tp_initial.arrival_times_dict.items() 
                                        for t in v[1:]])
    change_times = list(change_times)
    recs_initial = list(recs_initial)


    if len(tp_initial.arrival_times_dict[-1]) > 0:
        change_times.append(tp_initial.arrival_times_dict[-1][0])
        recs_initial.append(-1)

    change_times = np.array(change_times)
    sorted_inds = change_times.argsort()
    change_times = change_times[sorted_inds]
    recs_initial = np.array(recs_initial)[sorted_inds]

    rec_choice = np.zeros_like(change_times)
    stick_choice = np.zeros_like(change_times)
    interaction_times = np.array([interaction[0] for interaction in interactions])
    max_time = interactions[-1][0]
    #created_set = set()

    permuted_inds = np.random.permutation(len(change_times))
    
    # calculate all degrees between change times for all receivers
    degree_mat = np.zeros((num_recs, len(change_times) + 1))
    beta_mat = np.zeros((num_recs, len(change_times) + 1))

    for i, (begin_time, end_time) in enumerate(zip(np.concatenate([[0], change_times]), np.concatenate([change_times, [interaction_times[-1] + 1]]))):

        begin_ind = bisect_left(interaction_times, begin_time)
        end_ind = bisect_right(interaction_times, end_time)
        if begin_ind == end_ind:
            continue
            
        recs, degrees = np.unique([r for interaction in interactions[begin_ind:end_ind] for r in interaction[1]],
                              return_counts=True)

        for r in recs:
            if begin_time >= tp_initial.created_times[r] and end_time <= tp_initial.created_times[r]:
                degrees[recs == r] -= 1

        try:
            degree_mat[recs, i] = degrees
        except IndexError:
            import pdb
            pdb.set_trace()

        for r in range(num_recs):
            beta_mat[r, i] = tp_initial.get_stick(r, end_time)

    s_mat = np.vstack([np.flipud(np.cumsum(np.flipud(degree_mat), axis=0))[1:, :], 
           np.zeros((1, len(change_times)+1))])

    for ind in permuted_inds:
    #Need to calculate, the likelihood of each stick if that receiver
    #was not chosen.

        ct = change_times[ind]
        try:
            end_time = change_times[ind+1]
        except: end_time = interaction_times[-1] + 1

        for r in range(num_recs):
            beta_mat[r, ind+1] = tp_initial.get_stick(r, end_time)

        num_created_recs = len(tp_initial.created_times[tp_initial.created_times < ct])
        probs = np.array([tp_initial.get_stick(r, ct) for r in range(num_created_recs)] + [1])
        probs[1:] = probs[1:] * np.cumprod(1 - probs[:-1])

        log_probs = np.log(probs)
        #Calculate likelihood of each jump
        #First step, add integrated new beta
        log_probs[:-1] += betaln(1 - alpha + degree_mat[:num_created_recs, ind+1], 
                            theta + np.arange(1, num_created_recs+1) * alpha + s_mat[:num_created_recs, ind+1])
        
        #I think this next line is wrong.
        #log_probs[-1] += betaln(1 - alpha, 
        #                    theta + num_created_recs+1 * alpha)

        #Now, need to add all other likelihood components, i.e. all degrees for
        #which the receiver did not jump.
        likelihood_components = degree_mat[:num_created_recs, ind+1] * np.log(beta_mat[:num_created_recs, ind+1])
        likelihood_components += s_mat[:num_created_recs, ind+1] * np.log(1 - beta_mat[:num_created_recs, ind+1])

        log_probs[:-1] += np.sum(likelihood_components) - likelihood_components
        log_probs[-1] += np.sum(likelihood_components)

        probs = np.exp(log_probs - logsumexp(log_probs))

        new_choice = np.random.choice(num_created_recs+1, p=probs)
        rec_choice[ind] = new_choice
        if new_choice == recs_initial[ind]:
            if new_choice == num_created_recs:
                #Do nothing, it stayed in the tail
                continue
            else:
                #Draw the beta
                end_time = tp_initial.get_next_switch(new_choice, ct)
                if end_time == -1:
                    end_time = max_time
                begin_ind = bisect_left(interaction_times, ct)
                end_ind = bisect_right(interaction_times, end_time)

                new_stick = draw_beta(interactions[begin_ind:end_ind], tp_initial, ct, alpha, theta, new_choice)

                change_index = tp_initial.arrival_times_dict[new_choice].index(ct)
                tp_initial.stick_dict[new_choice][change_index] = new_stick

        else:
            r_delete = int(recs_initial[ind])
            tp_initial.delete_change(r_delete, ct)
        
            if r_delete != -1:
                # redraw the beta that we had deleted.
                begin_time, change_ind = tp_initial.get_last_switch(r_delete, ct, return_index=True)
                end_time = tp_initial.get_next_switch(r_delete, ct)
                if end_time == -1:
                    end_time = max_time

                begin_ind = bisect_left(interaction_times, begin_time)
                end_ind = bisect_right(interaction_times, end_time)

                new_stick = draw_beta(interactions[begin_ind:end_ind], tp_initial, begin_time, alpha, theta, r_delete)

                tp_initial.stick_dict[r_delete][change_ind] = new_stick

            if new_choice == num_created_recs:
                rec_choice[ind] = -1
                stick_choice[ind] = -1
                tp_initial.insert_change(-1, ct, -1.0)

            else:
                # Draw the beta backward
                begin_time, change_ind = tp_initial.get_last_switch(new_choice, ct, return_index=True)
                begin_ind = bisect_left(interaction_times, begin_time)
                end_ind = bisect_right(interaction_times, ct)
                
                new_stick = draw_beta(interactions[begin_ind:end_ind], tp_initial, begin_time, alpha, theta, new_choice)

                tp_initial.stick_dict[new_choice][change_ind] = new_stick

                #Draw the beta forward
                end_time = tp_initial.get_next_switch(new_choice, ct)
                if end_time == -1:
                    end_time = max_time
                begin_ind = bisect_left(interaction_times, ct)
                end_ind = bisect_right(interaction_times, end_time)

                new_stick = draw_beta(interactions[begin_ind:end_ind], tp_initial, ct, alpha, theta, new_choice)

                tp_initial.insert_change(new_choice, ct, new_stick)

    # Reupdate all the initial sticks, in case they did not get updated.
    for r in range(num_recs):
            #draw beta
        end_time = tp_initial.get_next_switch(r, tp_initial.created_times[r])
        if end_time == -1:
            end_time = max_time

        begin_ind = bisect_left(interaction_times, tp_initial.created_times[r])
        end_ind = bisect_right(interaction_times, end_time)

        new_stick = draw_beta(interactions[begin_ind:end_ind], tp_initial, tp_initial.created_times[r], alpha, theta, r)

        tp_initial.stick_dict[r][0] = new_stick

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


def sample_alpha(alpha, theta, V_array, r_array, sigma=0.1, debug=False):

    #Transform alpha by logit
    t_alpha = logit(alpha)
    t_alpha_prime = t_alpha + np.random.randn() * sigma
    alpha_prime = expit(t_alpha_prime)
    
    #Calculate the log likelihood ratio
    ll_ratio = ((alpha - alpha_prime) * np.log(V_array) + (r_array + 1) * 
                (alpha_prime - alpha) * np.log(1 - V_array)).sum()
    
    ll_ratio += betaln(1 - alpha, theta + (r_array + 1) * alpha).sum()
    ll_ratio -= betaln(1 - alpha_prime, theta + (r_array + 1) * alpha_prime).sum()

    #Correct for the transformation
    ll_ratio += np.log(alpha_prime * (1 - alpha_prime))
    ll_ratio -= np.log(alpha * (1 - alpha))

    if debug:
        print('Proposal: {}, ll_ratio: {}'.format(alpha_prime, ll_ratio))

    if np.isnan(ll_ratio):
        print('Uh oh! log likelihood ratio is NaN.')
        with open('debug.dat', 'a') as outfile:
            outfile.write('V_array: {}\n'.format(' '.join([i for i in V_array])))
            outfile.write('r_array: {}\n'.format(' '.join([i for i in r_array])))
        return False, alpha

    if np.log(np.random.rand()) < ll_ratio:
        return True, alpha_prime
    
    else:
        return False, alpha


def evaluate_sticks_ll(alpha, theta, V_array, r_array):
    ll = (-alpha * np.log(V_array) + (theta + (r_array + 1) * alpha) * np.log(1 - V_array)).sum()
    ll -= betaln(1 - alpha, theta + (r_array + 1) * alpha).sum()
    return ll


def evaluate_talpha_neg_ll(talpha, theta, V_array, r_array):
    alpha = expit(talpha)
    neg_ll = -evaluate_sticks_ll(alpha, theta, V_array, r_array)
    neg_ll -= np.log(alpha) + np.log(1 - alpha)
    return neg_ll


def evaluate_talpha_gradient(talpha, theta, V_array, r_array):
    alpha = expit(talpha)
    grad = (-np.log(V_array) + (r_array + 1) * np.log(1 - V_array)).sum()
    temp = digamma(1 - alpha)
    temp = -digamma(theta + (r_array + 1) * alpha) * (r_array + 1) + temp
    temp = temp + digamma(theta + r_array * alpha + 1) * r_array
    grad += temp.sum()
    grad += 1 / alpha - 1 / (1 - alpha)

    return -grad * alpha * (1 - alpha)


def sample_alpha_hmc(alpha, theta, V_array, r_array, num_steps=50, step_size=0.01, scale=1):

    neg_log_prob = partial(evaluate_talpha_neg_ll, theta=theta, V_array=V_array, r_array=r_array)
    dVdq = partial(evaluate_talpha_gradient, theta=theta, V_array=V_array, r_array=r_array)

    talpha = logit(alpha)
    talpha_array, accepted, rates, U = hamiltonian_monte_carlo(1, neg_log_prob, dVdq, talpha, num_steps, step_size, scale=scale)

    alpha_prime = expit(talpha_array[-1])

    return alpha_prime, accepted


def evaluate_ttheta_neg_ll(ttheta, alpha, V_array, r_array):
    theta = np.exp(ttheta)
    neg_ll = -evaluate_sticks_ll(alpha, theta, V_array, r_array)
    neg_ll -= np.log(theta)
    return neg_ll


def evaluate_ttheta_gradient(ttheta, alpha, V_array, r_array):
    theta = np.exp(ttheta)
    grad = np.log(1 - V_array).sum()
    temp = -digamma(theta + (r_array + 1) * alpha)
    temp = temp + digamma(theta + r_array * alpha + 1)
    grad += temp.sum()
    grad += 1 / theta
    return -grad * theta


def sample_theta_hmc(theta, alpha, V_array, r_array, num_steps=10, step_size=0.01, scale=1):

    neg_log_prob = partial(evaluate_ttheta_neg_ll, alpha=alpha, V_array=V_array, r_array=r_array)
    dVdq = partial(evaluate_ttheta_gradient, alpha=alpha, V_array=V_array, r_array=r_array)

    ttheta = np.log(theta)
    #import pdb 
    #pdb.set_trace()
    ttheta_array, accepted, rates, U = hamiltonian_monte_carlo(1, neg_log_prob, dVdq, ttheta, num_steps, step_size, scale=scale)

    theta_prime = np.exp(ttheta_array[-1])

    return theta_prime, accepted


def rjmcmc_jump_times(temporal_probs, nu):

    #Two options: delete or insert
    tp_candidate = deepcopy(temporal_probs)
    if np.random.rand() < 0.5:
        #Stupid delete - just a random deletion
        arrival_times, nodes = temporal_probs.get_arrival_times()
        deletion_ind = np.random.choice(len(arrival_times))

        tp_candidate.delete_change(nodes[deletion_ind], arrival_times[ind])

    else:
        #Insert candidate
        pass



def hamiltonian_monte_carlo(n_samples, negative_log_prob, dVdq, initial_position, num_steps=10,
                            step_size=0.01, scale=None):
    """Run Hamiltonian Monte Carlo sampling.

    Parameters
    ----------
    n_samples : int
    Number of samples to return
    negative_log_prob : callable
        The negative log probability to sample from
    initial_position : np.array
        A place to start sampling from.
    path_len : float
        How long each integration path is. Smaller is faster and more correlated.
    step_size : float
        How long each integration step is. Smaller is slower and more accurate.

    Returns
    -------
    np.array
        Array of length `n_samples`.
    """

    if scale is None:
        scale = 1
    # collect all our samples in a list
    samples = [initial_position]

    # Keep a single object for momentum resampling
    momentum = st.norm(0, 1)

    # If initial_position is a 10d vector and n_samples is 100, we want
    # 100 x 10 momentum draws. We can do this in one call to momentum.rvs, and
    # iterate over rows
    size = (n_samples,) + initial_position.shape[:1]
    acceptance_rates = []
    accepted = []

    U = [negative_log_prob(samples[-1])]
    for p0 in momentum.rvs(size=size):
        # Integrate over our path to get a new position and momentum
        q_new, p_new = leapfrog(
            samples[-1],
            scale * p0,
            dVdq,
            num_steps=num_steps,
            step_size=scale * step_size,
        )
        # Check Metropolis acceptance criterion
        start_log_p = negative_log_prob(samples[-1]) + np.sum(p0**2) / 2
        new_log_p = negative_log_prob(q_new) + np.sum(p_new**2) / 2
        # pdb.set_trace()

        acceptance_rates.append(start_log_p - new_log_p)
        if np.log(np.random.rand()) < min(0, start_log_p - new_log_p):
            samples.append(q_new)
            accepted.append(True)
            U.append(new_log_p)
        else:
            samples.append(np.copy(samples[-1]))
            accepted.append(False)
            U.append(U[-1])
        #print('Sample {} completed'.format(len(samples) - 1))

    return np.array(samples), accepted, acceptance_rates, U


def leapfrog(q, p, dVdq, num_steps, step_size):
    """Leapfrog integrator for Hamiltonian Monte Carlo.

    Parameters
    ----------
    q : np.floatX
        Initial position
    p : np.floatX
        Initial momentum
    dVdq : callable
        Gradient of the velocity
    path_len : float
        How long to integrate for
    step_size : float
        How long each integration step should be

    Returns
    -------
    q, p : np.floatX, np.floatX
        New position and momentum
    """
    #import pdb
    #pdb.set_trace()
    q, p = np.copy(q), np.copy(p)

    p -= step_size * dVdq(q) / 2  # half step
    for _ in range(num_steps - 1):

        q += step_size * p  # whole step
        p -= step_size * dVdq(q) #whole step
    q += step_size * p  # whole step
    p -= step_size * dVdq(q) / 2  # half step

    # q += step_size * p  # whole step
    # p -= step_size * dVdq(q) / 2  # half step

    # momentum flip at end
    return q, -p


def sample_theta(alpha, theta, V_array, r_array, sigma=50, debug=False):
    theta_prime = theta + np.random.randn() * sigma
    
    if theta_prime < 0:
        return False, theta
    
    #Calculate the log likelihood ratio
    ll_ratio = ((theta_prime - theta) * np.log(1 - V_array)).sum()
    
    ll_ratio += betaln(1 - alpha, theta + r_array * alpha).sum()
    ll_ratio -= betaln(1 - alpha, theta_prime + r_array * alpha).sum()
    if debug:
        print('Proposal: {}, ll_ratio: {}'.format(theta_prime, ll_ratio))
    if np.log(np.random.rand()) < ll_ratio:
        return True, theta_prime
    
    else:
        return False, theta


def evaluate_itime_likelihood(interactions, r, tp, proposal_time, begin_time, end_time, nu):
    ll = 0
    interaction_times = [t for (t, interaction) in interactions]

    #Evaluate the time from begin_time to proposal_time
    begin_ind = bisect_left(interaction_times, begin_time)
    proposal_ind = bisect_right(interaction_times, proposal_time)

    recs, degrees = np.unique([r for interaction in interactions[begin_ind:proposal_ind] for r in interaction[1]],
                              return_counts=True)
    degree_dict = dict(zip(recs, degrees))

    r = int(r)
    if r not in degree_dict:
        degree_dict[r] = 0
    if begin_time == tp.created_times[r]:
                degree_dict[r] -= 1

    stick = tp.get_stick(r, begin_time)
    if stick <= 0:
        import pdb
        pdb.set_trace()
    ll += degree_dict[r] * np.log(stick)
    ll += np.sum([v for (k, v) in degree_dict.items() if k > r]) * (1 - stick)

    #Evaluate the proposal_time to end_time
    end_ind = bisect_right(interaction_times, end_time)

    recs, degrees = np.unique([r for interaction in interactions[proposal_ind:end_ind] for r in interaction[1]],
                              return_counts=True)
    degree_dict = dict(zip(recs, degrees))

    if r not in degree_dict:
        degree_dict[r] = 0

    stick = tp.get_stick(r, proposal_time)

    if stick <= 0:
        import pdb
        pdb.set_trace()
    ll += degree_dict[r] * np.log(stick)
    ll += np.sum([v for (k, v) in degree_dict.items() if k > r]) * (1 - stick)

    ll += expon.logpdf(proposal_time - begin_time, scale=1/nu)
    ll+= expon.logpdf(end_time - proposal_time, scale=1/nu)

    return ll


def sample_interarrival_times(temporal_probs, interactions, theta, alpha, nu, sigma):

    num_recs = len(set([r for t, recs in interactions for r in recs]))

    nodes, arrival_times = zip(*[(k, t) for (k, v) in temporal_probs.arrival_times_dict.items()
                            for t in v[1:]])
    nodes = list(nodes)
    arrival_times = list(arrival_times)

    if len(temporal_probs.arrival_times_dict[-1]) > 0:
        arrival_times.append(temporal_probs.arrival_times_dict[-1][0])
        nodes.append(-1)

    arrival_times = np.array(arrival_times)
    sorted_inds = arrival_times.argsort()
    arrival_times = arrival_times[sorted_inds]
    nodes = np.array(nodes)[sorted_inds]

    accepted = []
    log_acceptance_probs = []
    for i, at in enumerate(arrival_times):

        r = int(nodes[i])
        if r == -1:
            accepted.append(False)
            continue
        if i == 0:
            begin_time = 0
        else:
            begin_time = arrival_times[i-1]
        if i == len(arrival_times) - 1:
            end_time = interactions[-1][0]
        else:
            end_time = arrival_times[i+1]

        ll_old = evaluate_itime_likelihood(interactions, r, temporal_probs, at, 
                                            begin_time, end_time, nu)

        at_new = at + sigma * np.random.randn()

        if at_new < temporal_probs.created_times[r]:
            accepted.append(False)
            continue
        #import pdb
        #pdb.set_trace()
        if i < len(arrival_times) - 1 and i > 0:
            if at_new <= arrival_times[i-1] or at_new >= arrival_times[i+1]:
                accepted.append(False)
                continue
        elif i == len(arrival_times) - 1:
            if at_new <= arrival_times[i-1]:
                accepted.append(False)
                continue
        elif i == 0:
            if at_new >= arrival_times[i+1] or at_new < 0:
                accepted.append(False)
                continue

        tp_candidate = deepcopy(temporal_probs)
        
        tp_candidate.move_change(r, at, at_new)
        ll_new = evaluate_itime_likelihood(interactions, r, tp_candidate, at_new, 
                                            begin_time, end_time, nu)

        log_acceptance_probs.append(ll_new - ll_old)
        if np.log(np.random.rand()) < ll_new - ll_old:
            accepted.append(True)
            temporal_probs = tp_candidate
            arrival_times[i] = at_new
        else:
            accepted.append(False)

    return temporal_probs, accepted, log_acceptance_probs


def run_chain(save_dir, num_times, created_times, created_sticks, 
                interactions, alpha, theta, nu, update_alpha=False, change_times=None,
              update_theta=False, update_interarrival_times=False, sigma_it=1, seed=None):
    np.random.seed(seed)

    max_time = interactions[-1][0]

    if change_times is None:
        change_times = [np.random.exponential(1 / nu)]
        while True:
            itime = np.random.exponential(1 / nu)
            if change_times[-1] + itime > max_time:
                break
            else:
                change_times.append(change_times[-1] + itime)

    print('Number of change times: {}'.format(len(change_times)))
    
    tp_initial = TemporalProbabilities(-1 * np.ones_like(change_times), -1 * np.ones_like(change_times),
                                         created_times, created_sticks, change_times)

    for t in range(num_times):
        if t % 100 == 0:
            print(t)
        #tp_initial, rec_choice, stick_choice = update_sticks_v2(tp_initial, interactions, alpha, theta)
        tp_initial, rec_choice, stick_choice = update_sticks_new_jump_update(tp_initial, interactions, alpha, theta)

        if update_interarrival_times:
            tp_initial, accepted, log_acceptance_probs = sample_interarrival_times(tp_initial,
                                                                                    interactions, theta,
                                                                                    alpha, nu, sigma_it)
        if update_alpha or update_theta:
            #Calculate V_array and r_array
            V_array = []
            r_array = []
            for k, v in tp_initial.stick_dict.items():
                for s in v:
                    if k != -1:
                        V_array.append(s)
                        r_array.append(k)
            V_array = np.array(V_array)
            r_array = np.array(r_array)

        if update_alpha:
            alpha, accepted = sample_alpha_hmc(alpha, theta, V_array, r_array)

        if update_theta:
            theta, accepted = sample_theta_hmc(theta, alpha, V_array, r_array)
            #print('theta: {}'.format(theta))
        params = {'alpha': alpha, 'theta': theta}

        if t >= num_times / 2:
            file_dir = save_dir / '{}.pkl'.format(t - int(num_times / 2))
            with file_dir.open('wb') as outfile:
                pickle.dump([tp_initial, params], outfile)
    return


def infer_teem(interactions, alpha, theta, nu, save_dir, num_chains=4, num_iters_per_chain=500, 
                update_alpha=True, update_theta=True, change_times=None, 
                update_interarrival_times=True):
    print('Creating Necessary Parameters')
    created_times = get_created_times(interactions)
    created_sticks = get_created_sticks(interactions, theta, alpha)

    rc_func = partial(run_chain, num_times=num_iters_per_chain, created_times=created_times,
                  created_sticks=created_sticks, change_times=change_times,
                  interactions=interactions, alpha=alpha, theta=theta, nu=nu,
                  update_alpha=update_alpha, update_theta=update_theta, 
                  update_interarrival_times=update_interarrival_times)

    if not pathlib.Path(save_dir).is_dir():
        pathlib.Path(save_dir).mkdir(parents=True)

    with (pathlib.Path(save_dir) / 'change_times.pkl').open('wb') as outfile:
        pickle.dump(change_times, outfile)
        
    save_dirs = [pathlib.Path(save_dir) / '{}'.format(i) 
                 for i in range(num_chains)]

    for sd in save_dirs:
        if not sd.is_dir():
            sd.mkdir(parents=True)

    start_time = time.time()
    print('Beginning Inference:')
    tp_lists = []

    with ProcessPoolExecutor() as executor:
        for _ in executor.map(rc_func, save_dirs):
            continue
    end_time = time.time()

    print('Took {} minutes.'.format((end_time - start_time) / 60))

    print('Calculating posterior estimates:')
    start_time = time.time()

    ((upper_limits, lower_limits, means),
    (probs_ul, probs_ll, probs)) = get_limits_and_means_different_times(save_dir, num_chains, num_iters_per_chain)
    end_time = time.time()

    print('Took {} minutes.'.format((end_time - start_time) / 60))

    return


def evaluate_posterior_log_likelihood(interactions, temporal_probs, alpha, theta, nu):

    #Evaluate sticks
    stick_r_array, V_array = zip(*[(k, i) for (k, v) in temporal_probs.stick_dict.items() for i in v
                                   if k != -1])
    V_array = np.array(V_array)
    stick_r_array = np.array(stick_r_array)

    ll = evaluate_sticks_ll(alpha, theta, V_array, stick_r_array)

    at_r_array, arrival_times = zip(*[(k, t) for (k, v) in temporal_probs.arrival_times_dict.items() 
                                        for t in v[1:]])
    at_r_array = list(at_r_array)
    arrival_times = list(arrival_times)

    if len(temporal_probs.arrival_times_dict[-1] > 0):
        arrival_times.append(temporal_probs.arrival_times_dict[-1][0])
        nodes.append(-1)

    arrival_times = np.array(arrival_times)
    sorted_inds = np.argsort(arrival_times)
    arrival_times = arrival_times[sorted_inds]
    at_r_array = np.array(at_r_array)[sorted_inds]

    interarrival_times = np.diff(arrival_times)
    #Interarrival times
    ll += st.expon.logpdf(interarrival_times, scale=1/nu).sum()
    
    #Choice of switching receiver
    ll += sum([np.log(temporal_probs.get_probability(int(r), t)) for (r, t) in zip(at_r_array, arrival_times)])

    #Evaluate the interactions
    num_recs = 0
    for t, interaction in interactions:
        for r in interaction:
            if r == num_recs:
                #Calculate tail probability
                ll += np.log(np.prod([1 - temporal_probs.get_stick(j, t) for j in range(num_recs)]))
                num_recs += 1
            else:
                ll += np.log(temporal_probs.get_probability(r, t))


    return ll


def get_limits_and_means_different_times(gibbs_dir, num_chains, num_iters_per_chain, 
    stick_name='stick_avgs.pkl', prob_name='prob_avgs.pkl'):

    times = []

    save_dirs = [os.path.join(gibbs_dir, '{}'.format(i)) for i in range(num_chains)]
    tp_master_list = []
    for save_dir in save_dirs:
        for i in range(int(num_iters_per_chain / 2)):
            save_path = os.path.join(save_dir, '{}.pkl'.format(i))
            with open(save_path, 'rb') as infile:
                tp, params = pickle.load(infile)
                times.append([t for v in tp.arrival_times_dict.values() for t in v])
                tp_master_list.append(tp)

    times = np.concatenate(times)
    times = np.unique(times)
    times.sort()
    
    num_times = len(times)
    num_recs = len(tp_master_list[0].created_times)
    means = np.zeros((num_times, num_recs))
    medians = np.zeros((num_times, num_recs))
    upper_limits = np.zeros((num_times, num_recs))
    lower_limits = np.zeros((num_times, num_recs))

    for r in range(num_recs):
        if r % 100 == 0:
            print(r)
        stick_list = []
        for tp in tp_master_list:
            try:
                sticks_ind = np.digitize(times, tp.arrival_times_dict[r], right=False) - 1
            except ValueError:
                import pdb
                pdb.set_trace()
            #sticks_ind[sticks_ind == len(tp.stick_dict[r])] = len(tp.stick_dict[r]) - 1
            sticks = np.array(tp.stick_dict[r])[sticks_ind]
            sticks[times < tp.created_times[r]] = 0
            stick_list.append(sticks)
        stick_array = np.array(stick_list)

        upper_limits[:, r] = np.percentile(stick_array, 97.5, axis=0)
        lower_limits[:, r] = np.percentile(stick_array, 2.5, axis=0)
        means[:, r] = stick_array.mean(axis=0)
        medians[:, r] = np.median(stick_array, axis=0)


    with open(os.path.join(gibbs_dir, stick_name), 'wb') as outfile:
        pickle.dump({'means': means,
                     'upper_limits': upper_limits,
                     'lower_limits': lower_limits,
                     'medians': medians}, outfile)


    probs = np.ones((means.shape[0], means.shape[1] + 1))
    probs[:, :-1] = means
    probs[:, 1:] = probs[:, 1:] * (np.cumprod(1 - means, axis=1))


    probs_ll = np.ones((upper_limits.shape[0], upper_limits.shape[1] + 1))
    probs_ul = np.ones((upper_limits.shape[0], upper_limits.shape[1] + 1))

    probs_ll[:, :-1] = lower_limits
    probs_ll[:, 1:] = probs_ll[:, 1:] * (np.cumprod(1 - upper_limits, axis=1))

    probs_ul[:, :-1] = upper_limits
    probs_ul[:, 1:] = probs_ul[:, 1:] * (np.cumprod(1 - lower_limits, axis=1))

    with open(os.path.join(gibbs_dir, prob_name), 'wb') as outfile:
        pickle.dump({'times': times,
                     'means': probs,
                     'upper_limits': probs_ul,
                     'lower_limits': probs_ll,
                     'medians': medians}, outfile)

    return (upper_limits, lower_limits, means), (probs_ul, probs_ll, probs)


def get_limits_and_means(gibbs_dir, times, num_chains, num_iters_per_chain, 
    stick_name='stick_avgs.pkl', prob_name='prob_avgs.pkl'):

    save_dirs = [os.path.join(gibbs_dir, '{}'.format(i)) for i in range(num_chains)]
    tp_master_list = []
    for save_dir in save_dirs:
        for i in range(int(num_iters_per_chain / 2)):
            save_path = os.path.join(save_dir, '{}.pkl'.format(i))
            with open(save_path, 'rb') as infile:
                tp_list, params = pickle.load(infile)
                tp_master_list.append(tp_list)

    num_times = len(times)
    num_recs = len(tp_master_list[0].created_times)
    means = np.zeros((num_times, num_recs))
    medians = np.zeros((num_times, num_recs))
    upper_limits = np.zeros((num_times, num_recs))
    lower_limits = np.zeros((num_times, num_recs))

    for r in range(num_recs):
        if r % 100 == 0:
            print(r)
        stick_list = []
        for tp in tp_master_list:
            try:
                sticks_ind = np.digitize(times, tp.arrival_times_dict[r], right=False) - 1
            except ValueError:
                import pdb
                pdb.set_trace()
            #sticks_ind[sticks_ind == len(tp.stick_dict[r])] = len(tp.stick_dict[r]) - 1
            sticks = np.array(tp.stick_dict[r])[sticks_ind]
            sticks[times < tp.created_times[r]] = 0
            stick_list.append(sticks)
        stick_array = np.array(stick_list)

        upper_limits[:, r] = np.percentile(stick_array, 97.5, axis=0)
        lower_limits[:, r] = np.percentile(stick_array, 2.5, axis=0)
        means[:, r] = stick_array.mean(axis=0)
        medians[:, r] = np.median(stick_array, axis=0)


    with open(os.path.join(gibbs_dir, stick_name), 'wb') as outfile:
        pickle.dump({'means': means,
                     'upper_limits': upper_limits,
                     'lower_limits': lower_limits,
                     'medians': medians}, outfile)


    probs = np.ones((means.shape[0], means.shape[1] + 1))
    probs[:, :-1] = means
    probs[:, 1:] = probs[:, 1:] * (np.cumprod(1 - means, axis=1))

    prob_medians = np.ones((medians.shape[0], medians.shape[1] + 1))
    prob_medians[:, :-1] = medians
    prob_medians[:, 1:] = prob_medians[:, 1:] * (np.cumprod(1 - medians, axis=1))

    probs_ll = np.ones((upper_limits.shape[0], upper_limits.shape[1] + 1))
    probs_ul = np.ones((upper_limits.shape[0], upper_limits.shape[1] + 1))

    probs_ll[:, :-1] = lower_limits
    probs_ll[:, 1:] = probs_ll[:, 1:] * (np.cumprod(1 - upper_limits, axis=1))

    probs_ul[:, :-1] = upper_limits
    probs_ul[:, 1:] = probs_ul[:, 1:] * (np.cumprod(1 - lower_limits, axis=1))

    with open(os.path.join(gibbs_dir, prob_name), 'wb') as outfile:
        pickle.dump({'means': probs,
                    'upper_limits': probs_ul,
                    'lower_limits': probs_ll,
                    'medians': prob_medians}, outfile)

    return (upper_limits, lower_limits, means), (probs_ul, probs_ll, probs)


def get_posterior_alphas(gibbs_dir, num_chains, num_iters_per_chain):

    save_dirs = [os.path.join(gibbs_dir, '{}'.format(i)) for i in range(num_chains)]
    alphas = []
    for save_dir in save_dirs:
        for i in range(int(num_iters_per_chain / 2)):
            save_path = os.path.join(save_dir, '{}.pkl'.format(i))
            with open(save_path, 'rb') as infile:
                tp_list, params = pickle.load(infile)
                alphas.append(params['alpha'])

    return alphas


def get_posterior_thetas(gibbs_dir, num_chains, num_iters_per_chain):

    save_dirs = [os.path.join(gibbs_dir, '{}'.format(i)) for i in range(num_chains)]
    thetas = []
    for save_dir in save_dirs:
        for i in range(int(num_iters_per_chain / 2)):
            save_path = os.path.join(save_dir, '{}.pkl'.format(i))
            with open(save_path, 'rb') as infile:
                tp_list, params = pickle.load(infile)
                thetas.append(params['theta'])

    return thetas


def rename_data_in_order(data):
    nodes_in_appearance = []
    renaming_dict = {}
    new_data = []
    
    for interaction in data:
        try:
            new_interaction = [renaming_dict[i] for i in interaction]
        except KeyError:
            new_interaction = []
            for i in interaction[1]:
                if i not in renaming_dict.keys():
                    renaming_dict[i] = len(nodes_in_appearance)
                    nodes_in_appearance.append(i)   
                new_interaction.append(renaming_dict[i])
        new_data.append([interaction[0], new_interaction])
    
    return nodes_in_appearance, renaming_dict, new_data
