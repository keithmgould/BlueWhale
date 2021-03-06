from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

# @build:deps [
# @/caffe2/caffe2/python:caffe2_py
# @/caffe2/caffe2/fb/data:hive_reader_python
# @/caffe2/proto:fb_protobuf
# @/hiveio:par_init
# ]

import random
import numpy as np
import unittest

from libfb.py.testutil import data_provider

from ml.rl.training.evaluator import \
    Evaluator
from ml.rl.thrift.core.ttypes import \
    RLParameters, TrainingParameters, \
    ContinuousActionModelParameters, KnnParameters
from ml.rl.training.continuous_action_dqn_trainer import \
    ContinuousActionDQNTrainer
from ml.rl.test.gridworld.gridworld_base import \
    DISCOUNT
from ml.rl.test.gridworld.gridworld_continuous import \
    GridworldContinuous
from ml.rl.test.gridworld.gridworld_continuous_enum import \
    GridworldContinuousEnum
from ml.rl.test.gridworld.gridworld_evaluator import \
    GridworldContinuousEvaluator, GridworldContinuousEnumEvaluator


class DataProvider(object):
    @staticmethod
    def envs():
        return [
            (GridworldContinuous(),),
            (GridworldContinuousEnum(),)
        ]

    @staticmethod
    def envs_and_evaluators():
        return [
            (
                GridworldContinuous(),
                GridworldContinuousEvaluator
            ),
            (
                GridworldContinuousEnum(),
                GridworldContinuousEnumEvaluator
            ),
        ]


class TestGridworldContinuous(unittest.TestCase):
    def setUp(self):
        super(self.__class__, self).setUp()
        np.random.seed(0)
        random.seed(0)

    def get_sarsa_parameters(self):
        return ContinuousActionModelParameters(
            rl=RLParameters(
                gamma=DISCOUNT,
                target_update_rate=0.5,
                reward_burnin=10,
                maxq_learning=False,
            ),
            training=TrainingParameters(
                layers=[-1, 200, 1],
                activations=['linear', 'linear'],
                minibatch_size=1024,
                learning_rate=0.01,
                optimizer='ADAM',
            ),
            knn=KnnParameters(
                model_type='DQN',
            )
        )

    def get_sarsa_trainer(self, environment):
        return ContinuousActionDQNTrainer(
            environment.normalization, environment.normalization_action,
            self.get_sarsa_parameters()
        )

    @data_provider(DataProvider.envs_and_evaluators, new_fixture=True)
    def test_trainer_single_batch_sarsa(self, environment, evaluator_class):
        states, actions, rewards, next_states, next_actions, is_terminal,\
            possible_next_actions, reward_timelines = \
            environment.generate_samples(100000, 1.0)
        trainer = self.get_sarsa_trainer(environment)
        predictor = trainer.predictor()
        evaluator = evaluator_class(environment, False)
        tdp = environment.preprocess_samples(
            states, actions, rewards, next_states, next_actions, is_terminal,
            possible_next_actions, reward_timelines
        )

        self.assertGreater(evaluator.evaluate(predictor), 0.15)

        trainer.stream_tdp(tdp)
        evaluator.evaluate(predictor)

        self.assertLess(evaluator.evaluate(predictor), 0.05)

    @data_provider(DataProvider.envs_and_evaluators, new_fixture=True)
    def test_trainer_single_batch_maxq(self, environment, evaluator_class):
        rl_parameters = self.get_sarsa_parameters()
        new_rl_parameters = ContinuousActionModelParameters(
            rl=RLParameters(
                gamma=DISCOUNT,
                target_update_rate=0.5,
                reward_burnin=10,
                maxq_learning=True,
            ),
            training=rl_parameters.training,
            knn=rl_parameters.knn
        )
        maxq_trainer = ContinuousActionDQNTrainer(
            environment.normalization, environment.normalization_action,
            new_rl_parameters
        )

        states, actions, rewards, next_states, next_actions, is_terminal,\
            possible_next_actions, reward_timelines = \
            environment.generate_samples(100000, 1.0)
        predictor = maxq_trainer.predictor()
        tbp = environment.preprocess_samples(
            states, actions, rewards, next_states, next_actions, is_terminal,
            possible_next_actions, reward_timelines
        )
        evaluator = evaluator_class(environment, True)
        self.assertGreater(evaluator.evaluate(predictor), 0.4)

        for _ in range(2):
            maxq_trainer.stream_tdp(tbp)
            evaluator.evaluate(predictor)

        self.assertLess(evaluator.evaluate(predictor), 0.1)

    @data_provider(DataProvider.envs, new_fixture=True)
    def test_evaluator_ground_truth(self, environment):
        states, actions, rewards, next_states, next_actions, is_terminal,\
            possible_next_actions, _ = environment.generate_samples(100000, 1.0)
        true_values = environment.true_values_for_sample(states, actions, False)
        # Hijack the reward timeline to insert the ground truth
        reward_timelines = []
        for tv in true_values:
            reward_timelines.append({0: tv})
        trainer = self.get_sarsa_trainer(environment)
        evaluator = Evaluator(trainer, DISCOUNT)
        tdp = environment.preprocess_samples(
            states, actions, rewards, next_states, next_actions, is_terminal,
            possible_next_actions, reward_timelines
        )

        trainer.stream_tdp(tdp, evaluator)

        self.assertLess(evaluator.td_loss[-1], 0.05)
        self.assertLess(evaluator.mc_loss[-1], 0.102)

    @data_provider(DataProvider.envs, new_fixture=True)
    def test_evaluator_timeline(self, environment):
        states, actions, rewards, next_states, next_actions, is_terminal,\
            possible_next_actions, reward_timelines = \
            environment.generate_samples(100000, 1.0)
        trainer = self.get_sarsa_trainer(environment)
        evaluator = Evaluator(trainer, DISCOUNT)

        tdp = environment.preprocess_samples(
            states, actions, rewards, next_states, next_actions, is_terminal,
            possible_next_actions, reward_timelines
        )
        trainer.stream_tdp(tdp, evaluator)

        self.assertLess(evaluator.td_loss[-1], 0.2)
        self.assertLess(evaluator.mc_loss[-1], 0.2)
