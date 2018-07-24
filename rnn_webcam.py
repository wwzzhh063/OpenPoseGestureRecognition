
import parameters as pa
import tensorflow as tf
import gpu_network
import rnn_network
import cv2
import numpy as np
from PIL import Image

def main(argv=None):
    g_1 = tf.Graph()
    g_2 = tf.Graph()
    with g_1.as_default():
        batch_size = 1

        # Place Holder
        img_holder = tf.placeholder(tf.float32, [batch_size, pa.PH, pa.PW, 3])
        # Entire network
        paf_pcm_tensor = gpu_network.PoseNet().inference_paf_pcm(img_holder)
        saver = tf.train.Saver()

    with g_2.as_default():
        NUM_CLASSES = 9  # 8 classes + 1 for no move
        NUM_JOINTS = 8

        # batch_time_joint_holder:
        btjh = tf.placeholder(tf.float32, [1, 1, NUM_JOINTS, 2])  # 2:xy
        c_state_holder = tf.placeholder(tf.float32, [32])
        h_state_holder = tf.placeholder(tf.float32, [32])
        
        state_tuple = ([c_state_holder], [h_state_holder])
        
        with tf.variable_scope("rnn-net"):
            # b t c(0/1)
            img_j_xy = tf.reshape(btjh, [-1, NUM_JOINTS, 2])
            img_fe = rnn_network.extract_features_from_joints(img_j_xy)
            btf = tf.reshape(img_fe, [1, 1, -1])
            pred, state = rnn_network.build_rnn_network(btf, NUM_CLASSES, state_tuple)
            # model evaluation
            btc_pred = tf.transpose(pred, [1, 0, 2])  # TBC to BTC
            btc_pred_max = tf.argmax(btc_pred, 2)
            rnn_saver = tf.train.Saver()


    # Session Saver
    sess1 = tf.Session(graph=g_1)
    sess2 = tf.Session(graph=g_2)

    ckpt = tf.train.get_checkpoint_state("logs/")
    if ckpt:
        saver.restore(sess1, ckpt.model_checkpoint_path)
    else:
        raise FileNotFoundError("CPM ckpt not found.")

    rnn_ckpt = tf.train.get_checkpoint_state("rnn_logs/")
    if rnn_ckpt:
        rnn_saver.restore(sess2, rnn_ckpt.model_checkpoint_path)
    else:
        raise FileNotFoundError("RNN ckpt not found.")

    cap = cv2.VideoCapture(0)
    
    rnn_saved_state = None
    # Camera output
    cam_out = np.zeros([512, 512, 3], dtype=np.uint8)
    # Prediction output
    map_h = 512
    map_w = 512
    sk_out = np.zeros([map_h, map_w], np.uint8)
    iter = 0
    assert cap.isOpened(),"Camera not supported."
    while cap.isOpened():
        ret, frame = cap.read()
        
        cam_out[0:480, 0:512, :] = frame[0:480, 0:512, :]
        sk_out.fill(0)
        
        rgb = cv2.cvtColor(cam_out, cv2.COLOR_BGR2RGB)
        rgb = rgb.astype(np.float32)
        rgb_norm = rgb / 255.
        rgb_norm = rgb_norm[np.newaxis]
        
        feed_dict = {img_holder: rgb_norm}
        paf_pcm = sess1.run(paf_pcm_tensor, feed_dict=feed_dict)
        pcm = paf_pcm[:, :, :, 14:]
        pcm = np.clip(pcm, 0., 1.)

        # 6 joint in image
        img_j6 = []
        for idx_joint in range(8):
            heat = pcm[0, :, :, idx_joint]
            c_coor_1d = np.argmax(heat)
            c_coor_2d = np.unravel_index(
                c_coor_1d, [pa.HEAT_SIZE[1], pa.HEAT_SIZE[0]])
            c_value = heat[c_coor_2d]
            j_xy = []  # x,y
            if c_value > 0.15:
                percent_h = c_coor_2d[0] / pa.HEAT_H
                percent_w = c_coor_2d[1] / pa.HEAT_W
                j_xy.append(percent_w)
                j_xy.append(percent_h)
            else:
                j_xy.append(-1.)
                j_xy.append(-1.)
            # Joint points
            img_j6.append(j_xy)  # [j][XY]

        # video_utils.save_joints_position(v_name)
        joint_xy = np.asarray(img_j6)
        joint_data = joint_xy[np.newaxis, np.newaxis, :, :]
        
        # Skeleton video
        # Inside one image
        for b1, b2 in pa.bones:
            if np.less(
                joint_xy[b1, :],
                0).any() or np.less(
                joint_xy[b2, :],
                0).any():
                continue  # no detection
            x1 = int(joint_xy[b1, 0] * map_w)
            y1 = int(joint_xy[b1, 1] * map_h)
            x2 = int(joint_xy[b2, 0] * map_w)
            y2 = int(joint_xy[b2, 1] * map_h)
            cv2.line(sk_out, (x1, y1), (x2, y2), (255, 255, 255))
        
        if rnn_saved_state is None:
            rnn_saved_state = ([np.zeros(32), np.zeros(32)])
        feed_dict = {btjh: joint_data, c_state_holder: rnn_saved_state[0], h_state_holder: rnn_saved_state[1]}
        btc_pred_num, state_num = sess2.run([btc_pred_max, state], feed_dict=feed_dict)
        rnn_saved_state = ([state_num[0][0], state_num[1][0]])
        pred = np.reshape(btc_pred_num, [-1])

        pred_text = pa.police_dict[pred[0]]
        
        
        cv2.putText(sk_out, pred_text, (50, 450), cv2.FONT_HERSHEY_SIMPLEX, 2, (255,255,255), 2)
        cv2.imshow('Camera', cam_out)
        cv2.imshow('Skeleton', sk_out)
        key = cv2.waitKey(5)
        if key == 27:  # Esc key to stop
            break
        print(str(iter) + ' ' + pred_text)
        iter = iter + 1

    cap.release()
    cv2.destroyAllWindows()

    sess1.close()
    sess2.close()
    exit(0)

if __name__ == "__main__":
    tf.app.run()

