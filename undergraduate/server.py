#!/usr/bin/python3
# -*- coding: utf-8 -*-
# @Time    : 2020/4/8 上午12:04
# @Author  : Boyka
# @Email   : upcvagen@163.com
# @File    : server.py
# @Software: PyCharm
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import json
import os
import threading

import cv2
import detectron.core.test_engine as infer_engine
import detectron.utils.c2 as c2_utils
import detectron.utils.keypoints as keypoint_utils
import numpy as np
from caffe2.python import workspace
from detectron.core.config import assert_and_infer_cfg
from detectron.core.config import merge_cfg_from_file
from flask import Flask, request
import logging
c2_utils.import_detectron_ops()
# OpenCL may be enabled by default in OpenCV3; disable it because it's not
# thread safe and causes unwanted GPU memory allocations.

lock = threading.Lock()  # 互斥锁
model = gpu_id = obj_classes = None
threshold = 0.6
app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

def convert_from_cls_format(cls_boxes, cls_keyps):
    """Convert from the class boxes/segms/keyps format generated by the testing
    code.
    """
    box_list = [b for b in cls_boxes if len(b) > 0]
    if len(box_list) > 0:
        boxes = np.concatenate(box_list)
    else:
        boxes = None
    if cls_keyps is not None:
        keyps = [k for klist in cls_keyps for k in klist]
    else:
        keyps = None
    return boxes, keyps


def vis_one_image(boxes, keypoints, thresh=0.6):
    person_bbox_list = []
    key_point_list = []
    if isinstance(boxes, list):
        boxes, keypoints = convert_from_cls_format(boxes, keypoints)

    if boxes is None or boxes.shape[0] == 0 or max(boxes[:, 4]) < thresh:
        return [], []
    dataset_keypoints, _ = keypoint_utils.get_keypoints()
    # Display in largest to smallest order to reduce occlusion
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    sorted_inds = np.argsort(-areas)

    for i in sorted_inds:
        bbox = boxes[i, :4]
        score = boxes[i, -1]
        if score < thresh:
            continue
        person_bbox_list.append(["person", score, int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])])

        if keypoints is not None and len(keypoints) > i:
            kps = keypoints[i]
            kp_in_one = []
            for j in range(17):
                if int(kps[2][j] < 0):
                    kp_in_one.append([dataset_keypoints[j], -1, -1])
                else:
                    kp_in_one.append([dataset_keypoints[j], int(kps[0][j]), int(kps[1][j])])
            key_point_list.append(kp_in_one)
    return person_bbox_list, key_point_list


def init_model(cfg_):
    global model
    global gpu_id
    global obj_classes
    global threshold

    gpu_id = cfg_["cfg"].get("gpu_id")
    obj_classes = cfg_["cfg"].get("classes")
    threshold = cfg_["cfg"].get("threshold")

    workspace.GlobalInit(['caffe2', '--caffe2_log_level=0'])
    # workspace.SwitchWorkspace("mask_model",True)
    merge_cfg_from_file(cfg_["cfg"].get("cfg_path"))
    assert_and_infer_cfg(make_immutable=False)
    model = infer_engine.initialize_model_from_cfg(cfg_["cfg"].get("wts_path"), gpu_id)


def cfg_format():
    """
    Transform the json to dict from the configure file.
    :return: Configure dict.
    """
    with open('cfg.json', 'r') as f:
        cfg_dict = json.load(f)
    return cfg_dict


@app.route('/register', methods=['POST', 'GET'])
def detect():
    img_data = request.files['file']
    logger.info(img_data)
    path = basedir + '/static/upload/img/'
    if not os.path.exists(path):
        os.makedirs(path)
    img_name = img_data.filename
    file_path = path + img_name
    img_data.save(file_path)

    # img = request.form["data"]
    # print(img)
    # img=np.array(eval(img))
    img = cv2.imread(img_data)
    result_box = []
    result_kps = []
    try:
        lock.acquire()
        with c2_utils.NamedCudaScope(gpu_id):
            cls_boxes, cls_segms, cls_keyps = infer_engine.im_detect_all(
                model, img, None, timers=None
            )
            result_box, result_kps = vis_one_image(cls_boxes, cls_keyps, threshold)
    except Exception as e:
        print(e)
    finally:
        lock.release()
    return {"bbox": str(result_box), "mask": str(result_kps)}


if __name__ == '__main__':
    cfg = cfg_format().get('person')
    init_model(cfg)
    app.run(host='0.0.0.0', port=5000)