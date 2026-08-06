import numpy as np
import os
import matplotlib.pyplot as plt

class RunningStats:
    def __init__(self, num_samples):
        self.n = 0
        self.old_m = np.zeros(num_samples, dtype=np.float64)
        self.new_m = np.zeros(num_samples, dtype=np.float64)
        self.old_s = np.zeros(num_samples, dtype=np.float64)
        self.new_s = np.zeros(num_samples, dtype=np.float64)

    def clear(self):
        self.n = 0
        self.old_m.fill(0)
        self.new_m.fill(0)
        self.old_s.fill(0)
        self.new_s.fill(0)

    def push(self, x):
        x = np.asarray(x, dtype=np.float64)
        self.n += 1

        if self.n == 1:
            self.old_m = self.new_m = x
            self.old_s = np.zeros_like(x)
        else:
            delta = x - self.old_m
            self.new_m = self.old_m + delta / self.n
            delta2 = x - self.new_m
            self.new_s = self.old_s + delta * delta2

            self.old_m = self.new_m
            self.old_s = self.new_s

    def mean(self):
        return self.new_m if self.n else np.zeros_like(self.new_m)

    def variance(self):
        return self.new_s / (self.n - 1) if self.n > 1 else np.zeros_like(self.new_s)

class TVLACalc:
    def __init__(self, num_samples):
        self.fixed_stats = RunningStats(num_samples)
        self.random_stats = RunningStats(num_samples)
        self.global_stats = RunningStats(num_samples)
        self.fixed_stats_sq = RunningStats(num_samples)
        self.random_stats_sq = RunningStats(num_samples)
        self.traceNum = 0

    def preprocess_trace(self, trace, global_mean):
        mean_free_trace = trace - global_mean
        squared_trace = mean_free_trace ** 2
        return squared_trace

    def addTrace(self, trace, coin):
        trace = np.asarray(trace, dtype=np.float64)
        self.global_stats.push(trace)
        global_mean = self.global_stats.mean()

        if coin == 0:
            self.fixed_stats.push(trace)
            preprocessed_trace = self.preprocess_trace(trace, global_mean)
            self.fixed_stats_sq.push(preprocessed_trace)
        else:
            self.random_stats.push(trace)
            preprocessed_trace = self.preprocess_trace(trace, global_mean)
            self.random_stats_sq.push(preprocessed_trace)
        self.traceNum += 1

    def get_mean_variance(self):
        mean_fixed = self.fixed_stats.mean()
        variance_fixed = self.fixed_stats.variance()
        mean_random = self.random_stats.mean()
        variance_random = self.random_stats.variance()
        return mean_fixed, variance_fixed, mean_random, variance_random

    def get_mean_variance_sq(self):
        mean_fixed_sq = self.fixed_stats_sq.mean()
        variance_fixed_sq = self.fixed_stats_sq.variance()
        mean_random_sq = self.random_stats_sq.mean()
        variance_random_sq = self.random_stats_sq.variance()
        return mean_fixed_sq, variance_fixed_sq, mean_random_sq, variance_random_sq

    def compute_tvla(self, mean_fixed, variance_fixed, mean_random, variance_random, n_fixed, n_random):
        epsilon = 1e-24
        denominator = np.sqrt((variance_fixed / n_fixed) + (variance_random / n_random) + epsilon)
        t_val = (mean_fixed - mean_random) / denominator
        return t_val

    def compute_first_order_tvla(self):
        mean_fixed, variance_fixed, mean_random, variance_random = self.get_mean_variance()
        n_fixed = self.fixed_stats.n
        n_random = self.random_stats.n
        return self.compute_tvla(mean_fixed, variance_fixed, mean_random, variance_random, n_fixed, n_random)

    def compute_second_order_tvla(self):
        mean_fixed_sq, variance_fixed_sq, mean_random_sq, variance_random_sq = self.get_mean_variance_sq()
        n_fixed_sq = self.fixed_stats_sq.n
        n_random_sq = self.random_stats_sq.n
        return self.compute_tvla(mean_fixed_sq, variance_fixed_sq, mean_random_sq, variance_random_sq, n_fixed_sq, n_random_sq)

    def save_tvla_results(self, directory, label, save_plot=True):
        t_val_first_order = self.compute_first_order_tvla()
        t_val_second_order = self.compute_second_order_tvla()
        
        # Save first-order t-values to CSV
        first_order_csv_file = os.path.join(directory, 'first_order_tvla_results.csv')
        np.savetxt(first_order_csv_file, t_val_first_order, delimiter=',')
        
        # Save second-order t-values to CSV
        second_order_csv_file = os.path.join(directory, 'second_order_tvla_results.csv')
        np.savetxt(second_order_csv_file, t_val_second_order, delimiter=',')
        
        # Save t-values to separate PNGs
        if save_plot:
            threshold = [4.5] * len(t_val_first_order)
            minus_threshold = [-4.5] * len(t_val_first_order)
            
            # First-order TVLA plot
            plt.figure(figsize=(12, 6))
            plt.plot(t_val_first_order, color='#1b3b6f', linewidth=0.6)
            plt.plot(threshold, color='#2e8b78', linestyle='--', linewidth=1.6)
            plt.plot(minus_threshold, color='#2e8b78', linestyle='--', linewidth=1.6)
            plt.ylim(-15, 15)
            plt.xlim(0, len(t_val_first_order))
            plt.xlabel('Sample No.')
            plt.ylabel('t-value')
            plt.title('First-Order TVLA Results')
            plt.savefig(os.path.join(directory, f'first_order_tvla_{label}.png'))
            plt.close()

            # Second-order TVLA plot
            plt.figure(figsize=(12, 6))
            plt.plot(t_val_second_order, color='#1b3b6f', linewidth=0.6)
            plt.plot(threshold, color='#2e8b78', linestyle='--', linewidth=1.6)
            plt.plot(minus_threshold, color='#2e8b78', linestyle='--', linewidth=1.6)
            plt.ylim(-15, 15)
            plt.xlim(0, len(t_val_second_order))
            plt.xlabel('Sample No.')
            plt.ylabel('t-value')
            plt.title('Second-Order TVLA Results')
            plt.savefig(os.path.join(directory, f'second_order_tvla_{label}.png'))
            plt.close()
        
        return t_val_first_order, t_val_second_order


