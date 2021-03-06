# -*- coding: utf-8 -*-
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import tensorflow as tf

from libs.utils import bbox_transform
from libs.utils.iou_rotate import iou_rotate_calculate2


class Loss(object):
    def __init__(self, cfgs):
        self.cfgs = cfgs

    def focal_loss(self, labels, pred, anchor_state, alpha=0.25, gamma=2.0):

        # filter out "ignore" anchors
        indices = tf.reshape(tf.where(tf.not_equal(anchor_state, -1)), [-1, ])
        labels = tf.gather(labels, indices)
        pred = tf.gather(pred, indices)

        # compute the focal loss
        per_entry_cross_ent = (tf.nn.sigmoid_cross_entropy_with_logits(
            labels=labels, logits=pred))
        prediction_probabilities = tf.sigmoid(pred)
        p_t = ((labels * prediction_probabilities) +
               ((1 - labels) * (1 - prediction_probabilities)))
        modulating_factor = 1.0
        if gamma:
            modulating_factor = tf.pow(1.0 - p_t, gamma)
        alpha_weight_factor = 1.0
        if alpha is not None:
            alpha_weight_factor = (labels * alpha +
                                   (1 - labels) * (1 - alpha))
        focal_cross_entropy_loss = (modulating_factor * alpha_weight_factor *
                                    per_entry_cross_ent)

        # compute the normalizer: the number of positive anchors
        normalizer = tf.stop_gradient(tf.where(tf.equal(anchor_state, 1)))
        # normalizer = tf.stop_gradient(tf.where(tf.greater_equal(anchor_state, 0)))
        normalizer = tf.cast(tf.shape(normalizer)[0], tf.float32)
        normalizer = tf.maximum(1.0, normalizer)

        # normalizer = tf.stop_gradient(tf.cast(tf.equal(anchor_state, 1), tf.float32))
        # normalizer = tf.maximum(tf.reduce_sum(normalizer), 1)

        return tf.reduce_sum(focal_cross_entropy_loss) / normalizer

    def smooth_l1_loss(self, targets, preds, anchor_state, sigma=3.0, weight=None):
        sigma_squared = sigma ** 2
        indices = tf.reshape(tf.where(tf.equal(anchor_state, 1)), [-1, ])
        preds = tf.gather(preds, indices)
        targets = tf.gather(targets, indices)

        # compute smooth L1 loss
        # f(x) = 0.5 * (sigma * x)^2          if |x| < 1 / sigma / sigma
        #        |x| - 0.5 / sigma / sigma    otherwise
        regression_diff = preds - targets
        regression_diff = tf.abs(regression_diff)

        regression_loss = tf.where(
            tf.less(regression_diff, 1.0 / sigma_squared),
            0.5 * sigma_squared * tf.pow(regression_diff, 2),
            regression_diff - 0.5 / sigma_squared
        )

        if weight is not None:
            regression_loss = tf.reduce_sum(regression_loss, axis=-1)
            weight = tf.gather(weight, indices)
            regression_loss *= weight

        normalizer = tf.stop_gradient(tf.where(tf.equal(anchor_state, 1)))
        normalizer = tf.cast(tf.shape(normalizer)[0], tf.float32)
        normalizer = tf.maximum(1.0, normalizer)

        # normalizer = tf.stop_gradient(tf.cast(tf.equal(anchor_state, 1), tf.float32))
        # normalizer = tf.maximum(tf.reduce_sum(normalizer), 1)

        return tf.reduce_sum(regression_loss) / normalizer

    def iou_smooth_l1_loss_log(self, targets, preds, anchor_state, target_boxes, anchors, sigma=3.0, is_refine=False):
        if self.cfgs.METHOD == 'H' and not is_refine:
            x_c = (anchors[:, 2] + anchors[:, 0]) / 2
            y_c = (anchors[:, 3] + anchors[:, 1]) / 2
            h = anchors[:, 2] - anchors[:, 0] + 1
            w = anchors[:, 3] - anchors[:, 1] + 1
            theta = -90 * tf.ones_like(x_c)
            anchors = tf.transpose(tf.stack([x_c, y_c, w, h, theta]))

        sigma_squared = sigma ** 2
        indices = tf.reshape(tf.where(tf.equal(anchor_state, 1)), [-1, ])

        preds = tf.gather(preds, indices)
        targets = tf.gather(targets, indices)
        target_boxes = tf.gather(target_boxes, indices)
        anchors = tf.gather(anchors, indices)

        boxes_pred = bbox_transform.rbbox_transform_inv(boxes=anchors, deltas=preds,
                                                        scale_factors=self.cfgs.ANCHOR_SCALE_FACTORS)

        # compute smooth L1 loss
        # f(x) = 0.5 * (sigma * x)^2          if |x| < 1 / sigma / sigma
        #        |x| - 0.5 / sigma / sigma    otherwise
        regression_diff = preds - targets
        regression_diff = tf.abs(regression_diff)
        regression_loss = tf.where(
            tf.less(regression_diff, 1.0 / sigma_squared),
            0.5 * sigma_squared * tf.pow(regression_diff, 2),
            regression_diff - 0.5 / sigma_squared
        )

        overlaps = tf.py_func(iou_rotate_calculate2,
                              inp=[tf.reshape(boxes_pred, [-1, 5]), tf.reshape(target_boxes[:, :-1], [-1, 5])],
                              Tout=[tf.float32])

        overlaps = tf.reshape(overlaps, [-1, 1])
        regression_loss = tf.reshape(tf.reduce_sum(regression_loss, axis=1), [-1, 1])
        # -ln(x)
        iou_factor = tf.stop_gradient(-1 * tf.log(overlaps)) / (tf.stop_gradient(regression_loss) + self.cfgs.EPSILON)
        # iou_factor = tf.Print(iou_factor, [iou_factor], 'iou_factor', summarize=50)

        normalizer = tf.stop_gradient(tf.where(tf.equal(anchor_state, 1)))
        normalizer = tf.cast(tf.shape(normalizer)[0], tf.float32)
        normalizer = tf.maximum(1.0, normalizer)

        # normalizer = tf.stop_gradient(tf.cast(tf.equal(anchor_state, 1), tf.float32))
        # normalizer = tf.maximum(tf.reduce_sum(normalizer), 1)

        return tf.reduce_sum(regression_loss * iou_factor) / normalizer

    def iou_smooth_l1_loss_exp(self, targets, preds, anchor_state, target_boxes, anchors, sigma=3.0, alpha=1.0, beta=1.0, is_refine=False):
        if self.cfgs.METHOD == 'H' and not is_refine:
            x_c = (anchors[:, 2] + anchors[:, 0]) / 2
            y_c = (anchors[:, 3] + anchors[:, 1]) / 2
            h = anchors[:, 2] - anchors[:, 0] + 1
            w = anchors[:, 3] - anchors[:, 1] + 1
            theta = -90 * tf.ones_like(x_c)
            anchors = tf.transpose(tf.stack([x_c, y_c, w, h, theta]))

        sigma_squared = sigma ** 2
        indices = tf.reshape(tf.where(tf.equal(anchor_state, 1)), [-1, ])

        preds = tf.gather(preds, indices)
        targets = tf.gather(targets, indices)
        target_boxes = tf.gather(target_boxes, indices)
        anchors = tf.gather(anchors, indices)

        boxes_pred = bbox_transform.rbbox_transform_inv(boxes=anchors, deltas=preds,
                                                        scale_factors=self.cfgs.ANCHOR_SCALE_FACTORS)

        # compute smooth L1 loss
        # f(x) = 0.5 * (sigma * x)^2          if |x| < 1 / sigma / sigma
        #        |x| - 0.5 / sigma / sigma    otherwise
        regression_diff = preds - targets
        regression_diff = tf.abs(regression_diff)
        regression_loss = tf.where(
            tf.less(regression_diff, 1.0 / sigma_squared),
            0.5 * sigma_squared * tf.pow(regression_diff, 2),
            regression_diff - 0.5 / sigma_squared
        )

        overlaps = tf.py_func(iou_rotate_calculate2,
                              inp=[tf.reshape(boxes_pred, [-1, 5]), tf.reshape(target_boxes[:, :-1], [-1, 5])],
                              Tout=[tf.float32])

        overlaps = tf.reshape(overlaps, [-1, 1])
        regression_loss = tf.reshape(tf.reduce_sum(regression_loss, axis=1), [-1, 1])
        # 1-exp(1-x)
        iou_factor = tf.stop_gradient(tf.exp(alpha*(1-overlaps)**beta)-1) / (tf.stop_gradient(regression_loss) + self.cfgs.EPSILON)
        # iou_factor = tf.stop_gradient(1-overlaps) / (tf.stop_gradient(regression_loss) + cfgs.EPSILON)
        # iou_factor = tf.Print(iou_factor, [iou_factor], 'iou_factor', summarize=50)

        normalizer = tf.stop_gradient(tf.where(tf.equal(anchor_state, 1)))
        normalizer = tf.cast(tf.shape(normalizer)[0], tf.float32)
        normalizer = tf.maximum(1.0, normalizer)

        # normalizer = tf.stop_gradient(tf.cast(tf.equal(anchor_state, 1), tf.float32))
        # normalizer = tf.maximum(tf.reduce_sum(normalizer), 1)

        return tf.reduce_sum(regression_loss * iou_factor) / normalizer

    def angle_focal_loss(self, labels, pred, anchor_state, alpha=0.25, gamma=2.0):

        indices = tf.reshape(tf.where(tf.equal(anchor_state, 1)), [-1, ])
        labels = tf.gather(labels, indices)
        pred = tf.gather(pred, indices)

        # compute the focal loss
        per_entry_cross_ent = - labels * tf.log(tf.sigmoid(pred) + self.cfgs.EPSILON) \
                              - (1 - labels) * tf.log(1 - tf.sigmoid(pred) + self.cfgs.EPSILON)

        prediction_probabilities = tf.sigmoid(pred)
        p_t = ((labels * prediction_probabilities) +
               ((1 - labels) * (1 - prediction_probabilities)))
        modulating_factor = 1.0
        if gamma:
            modulating_factor = tf.pow(1.0 - p_t, gamma)
        alpha_weight_factor = 1.0
        if alpha is not None:
            alpha_weight_factor = (labels * alpha +
                                   (1 - labels) * (1 - alpha))
        focal_cross_entropy_loss = (modulating_factor * alpha_weight_factor *
                                    per_entry_cross_ent)

        # compute the normalizer: the number of positive anchors
        normalizer = tf.stop_gradient(tf.where(tf.equal(anchor_state, 1)))
        normalizer = tf.cast(tf.shape(normalizer)[0], tf.float32)
        normalizer = tf.maximum(1.0, normalizer)

        # normalizer = tf.stop_gradient(tf.cast(tf.equal(anchor_state, 1), tf.float32))
        # normalizer = tf.maximum(tf.reduce_sum(normalizer), 1)

        return tf.reduce_sum(focal_cross_entropy_loss) / normalizer
