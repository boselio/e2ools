import numpy as np
import dill as pickle
from bisect import bisect_left, bisect_right
import bisect
from sklearn.base import BaseEstimator
from sklearn.utils import check_array
import numpy as np
import pdb
import scipy.optimize as opt
import pandas as pd
from collections import defaultdict
import random
import time
from functools import partial
import scipy
import scipy.sparse as sps
import scipy.stats as stats
#import pickle
import os.path
from copy import deepcopy
from ..choice_fns import choice_discrete_unnormalized
from .teem import TemporalProbabilities
import matplotlib.pyplot as plt
import seaborn as sns
sns.set()
from scipy.special import betaln, logsumexp
import pathlib
from concurrent.futures import ProcessPoolExecutor


class HTEEM(): 
    def __init__(self, nu, alpha=None, theta=None, theta_s=None, 
                    num_chains=4, num_iters_per_chain=500, 
                    holdout=100, alpha_hyperparams=(5, 5),
                    theta_hyperparams=(10, 10), lower_alpha_hyperparams=(5,5),
                    lower_theta_hyperparams=(10,10)):

        self.alpha_hyperparams = alpha_hyperparams
        self.theta_hyperparams = theta_hyperparams
        self.lower_theta_hyperparams = lower_theta_hyperparams

        self.alpha = alpha
        self.theta = theta
        self.theta_s = theta_s

        
    def initialize_state(self, interactions, change_times):

        #Initialize state variables
        ####Don't think I need this
        #Number of total tables across franchise serving each dish
        self.max_time = interactions[-1][0]
        self.global_table_counts = np.array([])
        ####
        #Sampled (or given) change times
        self.change_times = change_times
        #The locations that are sampled for each change time.
        self.change_locations = [(-1, -1) for _ in self.change_times]
        #indices of changes, per sender and per table
        self.table_change_inds = defaultdict(lambda: defaultdict(list))
        #Number of tables in each restaurant
        self.num_tables_in_s = defaultdict(int)
        #The inds that are for a particular receiver, in addition to the new table probability.
        self.receiver_inds = defaultdict(lambda: defaultdict(lambda: np.array([-1], dtype='int')))

        #For temporal version, table counts now must be list of lists (or arrays)
        #with each entry of the lower list corresponding to the tables counts at
        #a particular jump point.
        self.table_counts = defaultdict(list)
        self.sticks = defaultdict(list)
        #Created inds of each table, accordinf to the change times. 
        #This is a new thing; used to be created_times.
        self.created_inds = defaultdict(list)

        #Global info
        self.global_sticks = np.array([])
        self.global_probs = np.array([1])

        #Sender set
        self.s_set = set([interaction[1] for interaction in interactions])
        self.s_size = len(self.s_set)

        #Reciever set
        self.r_set = set([r for interaction in interactions for r in interaction[2]])
        self.r_size = len(self.r_set)

        self.created_sender_times = {}
        for (t, s, receivers) in interactions:
            if s not in self.created_sender_times:
                self.created_sender_times[s] = t

        if self.alpha is None:
            self.alpha = np.random.beta(*self.alpha_hyperparams)

        if self.theta is None: 
            self.theta = np.random.gamma(*self.theta_hyperparams)

        if self.theta_s is None:
            if len(self.lower_theta_hyperparams) != self.s_size:
                self.lower_theta_hyperparams = dict(zip(self.s_set, 
                                [self.lower_theta_hyperparams] * self.s_size))

            self.theta_s = {s: np.random.gamma(*self.lower_theta_hyperparams[s]) 
                                                            for s in self.s_set}
        else:
            try: 
                len(self.theta_s)
            except TypeError:
                self.theta_s = {s: self.theta_s for s in self.s_set}

        self._sample_table_configuration(interactions, initial=True)



    def run_chain(self, save_dir, num_times, interactions, change_times=None,
                    sample_parameters=True, update_alpha=False, update_theta=False,
                    update_interarrival_times=False, seed=None):
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

        self.initialize_state(interactions, change_times)

        
        for t in range(num_times):
            s_time = time.time()
            print(t)

            self._sample_table_configuration(interactions)
            self._sample_jump_locations(interactions)

            params = {'alpha': self.alpha, 'theta': self.theta,
                        'theta_s': self.theta_s,
                        'receiver_inds': self.receiver_inds,
                        'global_sticks': self.global_sticks,
                        'sticks': self.sticks,
                        'change_times': change_times,
                        'table_counts': self.table_counts,
                        'created_inds': self.created_inds
                        }


            if t >= num_times / 2:
                file_dir = save_dir / '{}.pkl'.format(t - int(num_times / 2))
                with file_dir.open('wb') as outfile:
                    pickle.dump(params, outfile)

            e_time = time.time()
            print(e_time - s_time)


    def infer(self, save_dir, interactions, num_chains=4, num_iters_per_chain=500, 
                    update_alpha=True, update_theta=True, change_times=None, 
                    update_interarrival_times=True):   

        self.current_save_dir = save_dir
        rc_func = partial(self.run_chain, num_times=num_iters_per_chain, 
                        interactions=interactions,
                      change_times=change_times, update_alpha=update_alpha, update_theta=update_theta, 
                      update_interarrival_times=update_interarrival_times)

        if not pathlib.Path(save_dir).is_dir():
            pathlib.Path(save_dir).mkdir(parents=True)

        if change_times is not None:
            with (pathlib.Path(save_dir) / 'initial_change_times.pkl').open('wb') as outfile:
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

        #print('Calculating posterior estimates:')
        #start_time = time.time()

        #((upper_limits, lower_limits, means),
        #(probs_ul, probs_ll, probs)) = get_limits_and_means_different_times(save_dir, num_chains, num_iters_per_chain)
        #end_time = time.time()

        #print('Took {} minutes.'.format((end_time - start_time) / 60))

        return

    def _sample_table_configuration(self, interactions, initial=False):

        
        if initial:
            for t, s, receivers in interactions:
                #import pdb
                #pdb.set_trace()
                for r in receivers:
                    self._add_customer(t, s, r)

            degree_mats = {}
            s_mats = {}

            #beta_mat = np.zeros((num_tables, len(change_times) + 1))
            #table_inds = {}
            #counter = 0

            num_senders = len(self.created_sender_times)

            for s in range(len(self.table_counts)):
                degree_mats[s] =  np.array(self.table_counts[s])
                s_mats[s] = np.vstack([np.flipud(np.cumsum(np.flipud(degree_mats[s]), axis=0))[1:, :], 
                                                        np.zeros((1, len(self.change_times) + 1))])

                for table in range(len(self.table_counts[s])):
                    try:
                        degree_mats[s][table, self.created_inds[s][table]] -= 1
                    except IndexError:
                        import pdb
                        pdb.set_trace()

            for s in range(len(self.table_counts)):
                for table in range(len(self.table_counts[s])):
                    #draw beta
                    begin_ind = self.created_inds[s][table]

                    new_stick = self.draw_local_beta(degree_mats[s][table,:].sum(),
                                        s_mats[s][table,:].sum(), self.theta_s[s])
                    self.sticks[s][table][begin_ind:] = new_stick
                    self.sticks[s][table][:begin_ind] = 1

        else:
            interaction_inds = np.random.permutation(len(interactions))
            #for t, s, interaction in interactions:
            for i in interaction_inds:
                t, s, receivers = interactions[i]
                for r in receivers:
                    #Remove a customer
                    self._remove_customer(t, s, r)
                    self._add_customer(t, s, r)

        #Update local sticks
        #for s in self.sticks.keys():
        #    reverse_counts = np.cumsum(self.table_counts[s][::-1])[::-1]
        #    reverse_counts = np.concatenate([reverse_counts[1:], [0]])
        #    a = 1 + self.table_counts[s]
        #    b = reverse_counts + self.theta_s[s]

        #    self.sticks[s] = np.random.beta(a, b)
        #    self.probs[s] = np.concatenate([self.sticks[s], [1]])
        #    self.probs[s][1:] = self.probs[s][1:] * np.cumprod(1 - self.probs[s][:-1])

        #Update global sticks
        reverse_counts = np.cumsum(self.global_table_counts[::-1])[::-1]
        reverse_counts = np.concatenate([reverse_counts[1:], [0]])
        #minus 1 because all the global "start" in the same global interval.
        a = 1 - self.alpha + self.global_table_counts - 1
        b = reverse_counts + self.theta + np.arange(1, len(self.global_table_counts)+ 1) * self.alpha
        self.global_sticks = np.random.beta(a, b)
        self.global_probs = np.concatenate([self.global_sticks, [1]])
        self.global_probs[1:] = self.global_probs[1:] * np.cumprod(1 - self.global_probs[:-1])


    def insert_table(self, t, s, r):
        time_bin = bisect_right(self.change_times, t)
        #Randomize?
        insert_left_point = bisect_left(self.created_inds[s], time_bin)
        insert_right_point = bisect_right(self.created_inds[s], time_bin)
        insert_point = np.random.choice(np.arange(insert_left_point, insert_right_point+1))

        for r_prime in self.receiver_inds[s].keys():
            ii = self.receiver_inds[s][r_prime] >= insert_point
            self.receiver_inds[s][r_prime][ii] = self.receiver_inds[s][r_prime][ii] + 1

        try:
            rec_insert_point = bisect_right(self.receiver_inds[s][r][:-1], insert_point)
        except IndexError:
            import pdb
            pdb.set_trace()

        self.receiver_inds[s][r] = np.insert(self.receiver_inds[s][r], rec_insert_point, insert_point)
        self.num_tables_in_s[s] += 1
        self.table_counts[s].insert(insert_point, np.zeros(len(self.change_times) + 1))
        self.table_counts[s][insert_point][time_bin] += 1
        self.created_inds[s].insert(insert_point, time_bin)
        self.sticks[s].insert(insert_point, np.ones(len(self.change_times) + 1) * np.random.beta(1, self.theta_s[s]))
        self.sticks[s][insert_point][:time_bin] = 1
        self.global_table_counts[r] += 1

        for s_temp in range(len(self.receiver_inds)):
            temp = np.sort(np.concatenate([l[:-1] for l in self.receiver_inds[s].values()]))
            assert (temp == np.arange(len(temp))).all()
            assert len(temp) == len(self.created_inds[s])
            assert len(temp) == len(self.table_counts[s])
            assert np.all(np.diff(self.created_inds[s_temp]) >= 0)
        try:
            assert np.all(np.diff(self.receiver_inds[s][r][:-1]) >= 0)
        except AssertionError:
            import pdb
            pdb.set_trace()


    def _add_customer(self, t, s, r, cython_flag=True):
        if len(self.global_table_counts) == r:
            assert r == len(self.global_sticks)
            #self.global_table_counts gets updated in insert_table
            self.global_table_counts = np.append(self.global_table_counts, [0])
            #self.global_table_counts[r] += 1
            #This is now wrong. Need to insert %after
            self.insert_table(t, s, r)

            #Draw global stick
            self.global_sticks = np.append(self.global_sticks, [np.random.beta(1 - self.alpha, 
                            self.theta + (len(self.global_sticks) + 1) * self.alpha)])
            self.global_probs = np.concatenate([self.global_sticks, [1]])
            self.global_probs[1:] = self.global_probs[1:] * np.cumprod(1 - self.global_probs[:-1])
            return

        probs, table_inds = self.get_unnormalized_probabilities(t, s, r)
        choice = choice_discrete_unnormalized(probs, np.random.rand())
        
        if choice == len(probs)-1:
            self.insert_table(t, s, r)
        else:
            table = table_inds[choice]
            time_ind = bisect_right(self.change_times, t)
            self.table_counts[s][table][time_ind] += 1



    def get_unnormalized_probabilities(self, t, s, r):
        time_bin = bisect_right(self.change_times, t)
        max_point = bisect_right(self.created_inds[s], time_bin)
        if max_point == 0:
            #No tables have been created at this time.
            rec_probs = [1.0]
            rec_inds = []
            return  rec_probs, rec_inds
        
        sticks = [self.get_stick(s, i, t) for i in range(max_point)]
        probs = np.concatenate([sticks, [1]])
        probs[1:] = probs[1:] * np.cumprod(1 - probs[:-1])
        try:
            max_rec_point = bisect_right([self.created_inds[s][i] for i in self.receiver_inds[s][r][:-1]], time_bin)
            rec_probs = np.concatenate([probs[self.receiver_inds[s][r][:max_rec_point]], [probs[-1]]])
        except IndexError:
            import pdb
            pdb.set_trace()
        rec_probs[-1] = rec_probs[-1] * self.global_probs[r]
    
        return rec_probs.tolist(), self.receiver_inds[s][r][:max_rec_point]


    def get_stick(self, s, table, t):
        time_bin = bisect_right(self.change_times, t)
        if time_bin < self.created_inds[s][table]:
            stick = 1
        else:
            stick = self.sticks[s][table][time_bin]
        return stick


    def get_table_counts(self, s, table, t):
        #change_ind = bisect_right(self.change_times, t)
        #before_ind = self.get_last_switch(s, i, change_ind)
        #after_ind = self.get_next_switch(s, i, before_ind)
        time_bin = bisect_right(self.change_times, t)
        if time_bin < self.created_inds[s][table]:
            counts = 0
        else:
            before_ind = self.get_last_switch(s, table, time_bin)
            after_ind = self.get_next_switch(s, table, time_bin)
            counts = sum(self.table_counts[s][table][before_ind:after_ind])

        return counts


    def delete_table(self, s, r, table, ind):
        self.num_tables_in_s[s] -= 1
        self.global_table_counts[r] -= 1
        self.sticks[s] = self.sticks[s][:table] + self.sticks[s][table+1:]
        self.table_counts[s] = self.table_counts[s][:table] +  self.table_counts[s][table+1:]
        self.created_inds[s] = self.created_inds[s][:table] + self.created_inds[s][table+1:]

        self.receiver_inds[s][r] = np.concatenate([self.receiver_inds[s][r][:ind],
                                               self.receiver_inds[s][r][ind+1:]])
        
        #Removed the ind table - so all tables greater than ind+1 -> ind
        for r in self.receiver_inds[s].keys():
            change = self.receiver_inds[s][r] > table
            self.receiver_inds[s][r][change] = self.receiver_inds[s][r][change] - 1


    def move_table_back(self, s, old_table, new_table, ind):
        #Pop the elements
        assert old_table < new_table
        self.table_counts[s].pop(old_table)
        self.table_counts[s].insert(new_table)
        self.sticks[s].pop(old_table)
        self.sticks[s].insert(new_table)
        self.created_inds[s].pop(old_table)
        self.created_inds[s].insert(new_table)



    def _remove_customer(self, t, s, r, cython_flag=True):
        #Choose uniformly at random a customer to remove.
        remove_probs = [self.get_table_counts(s, i, t) for i in self.receiver_inds[s][r][:-1]]
        
        ind = choice_discrete_unnormalized(remove_probs, np.random.rand())
        
        table = self.receiver_inds[s][r][ind]

        time_ind = bisect.bisect_right(self.change_times, t)
        self.table_counts[s][table][time_ind] -= 1
        #import pdb
        #pdb.set_trace()
        try:
            assert self.table_counts[s][table][time_ind] >= 0
        except AssertionError:
            import pdb
            pdb.set_trace()

        if self.table_counts[s][table][time_ind] == 0:
            #Check to see if the table has any counts at all
            if sum(self.table_counts[s][table]) == 0:
                self.delete_table(s, r, table, ind)
                #Removed the ind table - so all tables greater than ind+1 -> ind
                
            else:
                new_created_ind = next((i for i, x in enumerate(self.table_counts[s][table]) if x), None)
                new_table = bisect_left(self.created_inds, new_created_ind)

                #move the created_ind up to the next time we
                #see a degree for this table
                self.move_table_back(s, table, new_table)
                new_ind = bisect_left(self.receiver_inds[s][r][:-1], new_table)
                self.receiver_inds[s][r].pop(ind)
                self.receiver_inds[s][r].insert(new_ind, new_table)
                
                for r in self.receiver_inds[s].keys():
                    change = (self.receiver_inds[s][r] > table) & (self.receiver_inds[s][r] <= new_table)
                    self.receiver_inds[s][r][change] = self.receiver_inds[s][r][change] - 1

                self.change_inds[s][new_table] = new_created_ind
                self.sticks[s][new_table][:new_created_ind] = 1
                

        for s_temp in self.receiver_inds.keys():
            temp = np.sort(np.concatenate([l[:-1] for l in self.receiver_inds[s_temp].values()]))
            try:
                assert (temp == np.arange(len(temp))).all()
            except AssertionError:
                import pdb
                pdb.set_trace()

            try:
                assert len(temp) == len(self.created_inds[s_temp])
            except AssertionError:
                import pdb
                pdb.set_trace()

            try:
                assert len(temp) == len(self.table_counts[s_temp])
            except AssertionError:
                import pdb
                pdb.set_trace()
            
            
            
        try:
            assert self.receiver_inds[s][ind][-1] == -1
        except AssertionError:
            import pdb
            pdb.set_trace()


    def _remove_customer_old(self, t, s, r, cython_flag=True):
        #Choose uniformly at random a customer to remove.
        remove_probs = [self.get_table_counts(s, i, t) for i in self.receiver_inds[s][r][:-1]]

        remove_probs = list(remove_probs)
        #Check to see if any of the tables were created at this time
        deleted_inds = []
        deleted_tables = []

        time_ind = bisect.bisect_right(self.change_times, t)
        if time_ind == 0:
            before_time = 0
        else:
            before_time = self.change_times[time_ind - 1]

        for i, ind in enumerate(self.receiver_inds[s][r][:-1]):
            if (before_time <= self.created_times[s][ind]) and (self.created_times[s][ind] <= t):
                if sum(self.table_counts[s][ind]) != 1:
                    remove_probs[i] -= 1
                    deleted_inds.append(ind)
                    deleted_tables.append(i)

        #Check to see if remove probs > 0
        if sum(remove_probs) == 0:
            return False
        
        table = choice_discrete_unnormalized(remove_probs, np.random.rand())
        
        ind = self.receiver_inds[s][r][table]
        self.table_counts[s][ind][time_ind] -= 1
        try:
            assert self.table_counts[s][ind][time_ind] >= 0
        except AssertionError:
            import pdb
            pdb.set_trace()
        if sum(self.table_counts[s][ind]) == 0:
            self.num_tables_in_s[s] -= 1
            self.global_table_counts[r] -= 1
            self.sticks[s] = self.sticks[s][:ind] + self.sticks[s][ind+1:]
            self.table_counts[s] = self.table_counts[s][:ind] +  self.table_counts[s][ind+1:]
            self.receiver_inds[s][r] = np.concatenate([self.receiver_inds[s][r][:table],
                                                       self.receiver_inds[s][r][table+1:]])
            self.created_times[s] = self.created_times[s][:ind] + self.created_times[s][ind+1:]
            #Removed the ind table - so all tables greater than ind+1 -> ind
            for r in self.receiver_inds[s].keys():
                self.receiver_inds[s][r][self.receiver_inds[s][r] > ind] = self.receiver_inds[s][r][self.receiver_inds[s][r] > ind] - 1


        for s_temp in self.receiver_inds.keys():
            temp = np.sort(np.concatenate([l[:-1] for l in self.receiver_inds[s_temp].values()]))
            try:
                assert (temp == np.arange(len(temp))).all()
            except AssertionError:
                import pdb
                pdb.set_trace()

            try:
                assert len(temp) == len(self.created_times[s_temp])
            except AssertionError:
                import pdb
                pdb.set_trace()

            try:
                assert len(temp) == len(self.table_counts[s_temp])
            except AssertionError:
                import pdb
                pdb.set_trace()
            
            
            
        try:
            assert self.receiver_inds[s][ind][-1] == -1
        except AssertionError:
            import pdb
            pdb.set_trace()
        return True



    def _sample_jump_locations(self, interactions):

        num_tables = sum([len(v) for k, v in self.table_counts.items()])

        change_times = np.array(self.change_times)
        old_locs = self.change_locations
        sorted_inds = change_times.argsort()
        change_times = change_times[sorted_inds]
        old_locs = np.array(old_locs)[sorted_inds]

        interaction_times = np.array([interaction[0] for interaction in interactions])
        max_time = interactions[-1][0]
        #created_set = set()

        permuted_inds = np.random.permutation(len(change_times))
        
        # calculate all degrees between change times for all receivers
        degree_mats = {}
        s_mats = {}

        #beta_mat = np.zeros((num_tables, len(change_times) + 1))
        #table_inds = {}
        #counter = 0

        num_senders = len(self.created_sender_times)

        for s in range(len(self.table_counts)):
            degree_mats[s] =  np.array(self.table_counts[s])
            try:
                s_mats[s] = np.vstack([np.flipud(np.cumsum(np.flipud(degree_mats[s]), axis=0))[1:, :], 
                                                    np.zeros((1, len(self.change_times) + 1))])
            except ValueError:
                import pdb
                pdb.set_trace()

            for i in range(len(self.table_counts[s])):
                begin_ind = self.created_inds[s][i]
                degree_mats[s][i, begin_ind] -= 1

        for s in range(num_senders):
            try:
                assert (degree_mats[s] >= 0).all()
            except AssertionError:
                import pdb
                pdb.set_trace()
            assert (s_mats[s] >= 0).all()

        for ind in permuted_inds:
        #Need to calculate, the likelihood of each stick if that receiver
        #was not chosen.

            ct = self.change_times[ind]
            if ind > 0:
                begin_time = self.change_times[ind-1]
            else:
                begin_time = 0
            try:
                end_time = self.change_times[ind+1]
            except IndexError:
                end_time = interaction_times[-1] + 1

            num_created_tables = {}
            probs = {}
            log_probs = {}

            before_likelihood_components = {}
            after_likelihood_components = {}
            #Calculate likelihood of each jumps
            created_senders = [s for (s, t) in self.created_sender_times.items() if t < ct]

            for s in created_senders:
                #Calculate log probs for all potential jumps, at the period BEFORE the jump
                num_created_tables[s] = len([i for i in self.created_inds[s] if i <= ind])
                probs[s] = np.array([self.get_stick(s, i, ct - 1e-8) for i in range(num_created_tables[s])] + [1])
                probs[s][1:] = probs[s][1:] * np.cumprod(1 - probs[s][:-1])
                log_probs[s] = np.log(probs[s])

                #Add integrated new beta using future table counts.
                log_probs[s][:-1] += betaln(1 + degree_mats[s][:num_created_tables[s], ind+1], 
                                    self.theta_s[s] + s_mats[s][:num_created_tables[s], ind+1])
            
                #Now, need to add all other likelihood components, i.e. all degrees for
                #which the receiver did not jump.
                after_likelihood_components[s] = degree_mats[s][:num_created_tables[s], ind+1] * np.log(np.array(self.sticks[s])[:num_created_tables[s], ind+1])
                after_likelihood_components[s] += s_mats[s][:num_created_tables[s], ind+1] * np.log(1 - np.array(self.sticks[s])[:num_created_tables[s], ind+1])

                before_likelihood_components[s] = degree_mats[s][:num_created_tables[s], ind+1] * np.log(np.array(self.sticks[s])[:num_created_tables[s], ind])
                before_likelihood_components[s] += s_mats[s][:num_created_tables[s], ind+1] * np.log(1 - np.array(self.sticks[s])[:num_created_tables[s], ind])

            for s in created_senders:
                for ss in created_senders:
                    log_probs[s] += np.sum(before_likelihood_components[ss])
                    log_probs[s] += np.sum(after_likelihood_components[ss])
                log_probs[s][:-1] -= after_likelihood_components[s]

            #import pdb
            #pdb.set_trace()
            #First, choose sender:
            integrated_sender_log_probs = [logsumexp(log_probs[s]) for s in created_senders]
            integrated_sender_probs = np.exp(integrated_sender_log_probs - logsumexp(integrated_sender_log_probs))
            new_s = np.random.choice(created_senders, p=integrated_sender_probs)

            #log_prob = np.concatenate([log_probs[s] for s in range(num_senders)])
            #probs = np.exp(log_prob - logsumexp(log_prob))
            probs = np.exp(log_probs[new_s] - logsumexp(log_probs[new_s]))
            #num_total_tables = sum(num_created_tables.values())
            new_t = np.random.choice(num_created_tables[new_s] + 1, p=probs)

            #temp = np.cumsum([num_created_tables[i] + 1 for i in range(num_senders)])
            #new_s = bisect_right(temp, new_ind)
            #if new_s > 0:
            #    new_t = new_ind - temp[new_s - 1]

            new_choice = (new_s, new_t)

            if (new_choice[0] == old_locs[ind][0]) and (new_choice[1] == old_locs[ind][1]):
                if new_choice[1] == num_created_tables[new_s]:
                    #Do nothing, it stayed in the tail
                    continue
                else:
                    #Draw the beta
                    end_ind = self.get_next_switch(new_s, new_t, ind)
                    if end_ind == -1:
                        end_time = max_time
                    begin_ind = self.get_last_switch(new_s, new_t, ind)
                    end_ind = bisect_right(interaction_times, end_time)

                    new_stick = self.draw_local_beta(degree_mats[new_s][new_t, ind+1:end_ind].sum(), 
                                                s_mats[new_s][new_t, ind+1:end_ind].sum(), self.theta_s[new_s])
                    self.sticks[new_s][new_t][ind+1:end_ind] = new_stick

                    new_stick = self.draw_local_beta(degree_mats[new_s][new_t, begin_ind:ind+1].sum(), 
                                                s_mats[new_s][new_t, begin_ind:ind+1].sum(), self.theta_s[new_s])
                    self.sticks[new_s][new_t][begin_ind:ind+1] = new_stick


            else:
                old_loc = old_locs[ind]
                s_del = old_loc[0]
                t_del = old_loc[1]
                if s_del != -1:
                    if t_del < num_created_tables[s_del]:
                        self.table_change_inds[s_del][t_del].remove(ind)
                        # redraw the beta that we had deleted.
                        begin_ind = self.get_last_switch(s_del, t_del, ind)
                        end_ind = self.get_next_switch(s_del, t_del, ind)
                        if end_time == -1:
                            end_time = max_time

                        try:
                            new_stick = self.draw_local_beta(degree_mats[s_del][t_del, begin_ind:end_ind].sum(), 
                                                    s_mats[s_del][t_del, begin_ind:end_ind].sum(), self.theta_s[s_del])
                        except IndexError:
                            import pdb
                            pdb.set_trace()
                        self.sticks[s_del][t_del][begin_ind:end_ind] = new_stick


                if new_t == num_created_tables[new_s]:
                    #import pdb
                    #pdb.set_trace()
                    self.change_locations[ind] = (-1, -1)

                else:
                    self.change_locations[ind] = (new_s, new_t)
                    insert_ind = bisect_right(self.table_change_inds[new_s][new_t], ind)
                    self.table_change_inds[new_s][new_t].insert(insert_ind, ind)
                    # Draw the beta backward
                    begin_ind = self.get_last_switch(new_s, new_t, ind)
                    end_ind = self.get_next_switch(new_s, new_t, ind)
                    
                    try:
                        new_stick = self.draw_local_beta(degree_mats[new_s][new_t, ind+1:end_ind].sum(), 
                                                s_mats[new_s][new_t, ind+1:end_ind].sum(), self.theta_s[new_s])
                    except IndexError:
                        import pdb
                        pdb.set_trace()

                    self.sticks[new_s][new_t][ind+1:end_ind] = new_stick

                    new_stick = self.draw_local_beta(degree_mats[new_s][new_t, begin_ind:ind+1].sum(), 
                                                s_mats[new_s][new_t, begin_ind:ind+1].sum(), self.theta_s[new_s])
                    self.sticks[new_s][new_t][begin_ind:ind+1] = new_stick

        for s in range(num_senders):
            for t in range(len(self.table_counts[s])):
                #draw beta
                end_ind = self.get_next_switch(s, t, 0)

                new_stick = self.draw_local_beta(degree_mats[s][t,:end_ind].sum(),
                                        s_mats[s][t,:end_ind].sum(), self.theta_s[s])
                self.sticks[s][t][:end_ind] = new_stick

        return 


    def get_next_switch(self, s, i, ind):
        after_ind = bisect_right(self.table_change_inds[s][i], ind)
        if after_ind == len(self.table_change_inds[s][i]):
            return None
        return self.table_change_inds[s][i][after_ind]
        

    def get_last_switch(self, s, i, ind):
        before_ind = bisect_left(self.table_change_inds[s][i], ind)
        if before_ind == 0:
            return 0
        elif before_ind == len(self.table_change_inds[s][i]):
            before_ind = -1

        return self.table_change_inds[s][i][before_ind] + 1
            

    def draw_local_beta(self, d, s, theta):
        return np.random.beta(d + 1, s + theta)


    def read_files(self, save_dir=None, num_chains=4, num_iters_per_chain=500):
        if save_dir is None:
            save_dir = self.current_save_dir

        save_dirs = [save_dir /  '{}'.format(i) for i in range(num_chains)]
        param_dicts = []
        for d in save_dirs:
            for i in range(int(num_iters_per_chain / 2)):
                save_path = d / '{}.pkl'.format(i)
                with save_path.open('rb') as infile:
                    param_dicts.append(pickle.load(infile))

        return param_dicts
