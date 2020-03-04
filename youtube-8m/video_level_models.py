# Copyright 2017 Antoine Miech All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Contains model definitions."""
import math

import models
import tensorflow as tf
import utils

from tensorflow import flags
import tensorflow.contrib.slim as slim

FLAGS = flags.FLAGS
flags.DEFINE_integer(
    "moe_num_mixtures", 2,#2
    "The number of mixtures (excluding the dummy 'expert') used for MoeModel.")
flags.DEFINE_float(
    "moe_l2", 1e-6, #1e-8
    "L2 penalty for MoeModel.")
flags.DEFINE_integer(
    "moe_low_rank_gating", -1,
    "Low rank gating for MoeModel.")
flags.DEFINE_bool(
    "moe_prob_gating", True, #False
    "Prob gating for MoeModel.")
flags.DEFINE_string(
    "moe_prob_gating_input", "prob",
    "input Prob gating for MoeModel.")
flags.DEFINE_bool(
    "gating_remove_diag", False,
    "input Prob gating for MoeModel.")
flags.DEFINE_float(
    "l2_penalty", 1e-8,
    "the l2 penalty of classifier weights and bias"
)
class LogisticModel(models.BaseModel):
  """Logistic model with L2 regularization."""

  def create_model(self, model_input, vocab_size, l2_penalty=None, **unused_params):

    l2_penalty = l2_penalty or FLAGS.l2_penalty
    logits = slim.fully_connected(
        model_input, vocab_size, activation_fn=None,
        weights_regularizer=slim.l2_regularizer(l2_penalty),
        biases_regularizer=slim.l2_regularizer(l2_penalty),
        weights_initializer=slim.variance_scaling_initializer())
    output = tf.nn.sigmoid(logits)
    return {"predictions": output}#, "logits": logits


class MoeModel(models.BaseModel):
  """A softmax over a mixture of logistic models (with L2 regularization)."""

  def create_model(self,
                   model_input,
                   vocab_size,
                   is_training=True,
                   num_mixtures=None,
                   l2_penalty=1e-8,
                   **unused_params):

    num_mixtures = num_mixtures or FLAGS.moe_num_mixtures
    low_rank_gating = FLAGS.moe_low_rank_gating
    l2_penalty = FLAGS.moe_l2;
    gating_probabilities = FLAGS.moe_prob_gating
    gating_input = FLAGS.moe_prob_gating_input

    input_size = model_input.get_shape().as_list()[1]
    remove_diag = FLAGS.gating_remove_diag

    if low_rank_gating == -1:
        gate_activations = slim.fully_connected(
            model_input,
            vocab_size * (num_mixtures + 1),
            activation_fn=None,
            biases_initializer=None,
            weights_regularizer=slim.l2_regularizer(l2_penalty),
            scope="gates")
    else:
       gate_activations1 = slim.fully_connected(
            model_input,
            low_rank_gating,
            activation_fn=None,
            biases_initializer=None,
            weights_regularizer=slim.l2_regularizer(l2_penalty),
            scope="gates1")
       gate_activations = slim.fully_connected(
            gate_activations1,
            vocab_size * (num_mixtures + 1),
            activation_fn=None,
            biases_initializer=None,
            weights_regularizer=slim.l2_regularizer(l2_penalty),
            scope="gates2")


    expert_activations = slim.fully_connected(
        model_input,
        vocab_size * num_mixtures,
        activation_fn=None,
        weights_regularizer=slim.l2_regularizer(l2_penalty),
        scope="experts")

    gating_distribution = tf.nn.softmax(tf.reshape(
        gate_activations,
        [-1, num_mixtures + 1]))  # (Batch * #Labels) x (num_mixtures + 1)
    expert_distribution = tf.nn.sigmoid(tf.reshape(
        expert_activations,
        [-1, num_mixtures]))  # (Batch * #Labels) x num_mixtures

    probabilities_by_class_and_batch = tf.reduce_sum(
        gating_distribution[:, :num_mixtures] * expert_distribution, 1)
    probabilities = tf.reshape(probabilities_by_class_and_batch,
                                     [-1, vocab_size])

    if gating_probabilities:
        if gating_input == 'prob':
            gating_weights = tf.get_variable("gating_prob_weights",
              [vocab_size, vocab_size],
              initializer = tf.random_normal_initializer(stddev=1 / math.sqrt(vocab_size)))
            gates = tf.matmul(probabilities, gating_weights)
        else:
            gating_weights = tf.get_variable("gating_prob_weights",
              [input_size, vocab_size],
              initializer = tf.random_normal_initializer(stddev=1 / math.sqrt(vocab_size)))
 
            gates = tf.matmul(model_input, gating_weights)
        
        if remove_diag:
            #removes diagonals coefficients
            diagonals = tf.matrix_diag_part(gating_weights)
            gates = gates - tf.multiply(diagonals,probabilities)

        gates = slim.batch_norm(
              gates,
              center=True,
              scale=True,
              is_training=is_training,
              scope="gating_prob_bn")

        gates = tf.sigmoid(gates)

        probabilities = tf.multiply(probabilities,gates)


    return {"predictions": probabilities}
