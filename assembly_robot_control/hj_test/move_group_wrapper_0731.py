#!/usr/bin/env python
import tf
import rospy
import time
import math as m
import copy 
import geometry_msgs.msg
import moveit_msgs.msg
from sensor_msgs.msg import JointState
from moveit_commander import MoveGroupCommander, PlanningSceneInterface

from ur5e_inv_kin_wrapper import UR5eInvKinForTF
from Parts_hj import*
from const import *
import utils

def list_str(some_list, some_key):
  msg = ""
  try:
    for i in range(len(some_list)):
      msg += "{}: {:.3f} ".format(some_key[i], some_list[i])
  except:
    print "failed to make list look pretty!"

  return msg

class MoveGroupCommanderWrapper(MoveGroupCommander):
  def __init__(self, name, _eef_link=None):
    # super(MoveGroupCommanderWrapper, self).__init__(group_name)
    MoveGroupCommander.__init__(self, name)
    
    # setup for move group
    self.set_planning_time(3)
    self.set_num_planning_attempts(5)
    self.set_max_velocity_scaling_factor(1)
    self.set_max_acceleration_scaling_factor(1)

    if _eef_link is None:
      eef_link = 'tcp_gripper_closed'
      _eef_link = name[:5] + eef_link
    else:
      eef_link = _eef_link[5:]    
    MoveGroupCommander.set_end_effector_link(self, _eef_link)
    
    # setup for ur5e invkin
    eef_offset = TCP_OFFSET[eef_link]
    self.ur5e = UR5eInvKinForTF(eef_offset)
    print"eef_link: {}, eef_offset: {}".format(eef_link, eef_offset)

  def get_name(self):
    '''
    how to handle method overloading
    '''
    print "My name is {}".format(self.__class__.__name__)
    # return super(MoveGroupCommanderWrapper, self).get_name()
    return MoveGroupCommander.get_name(self)

  def _list_to_js(self, joint_list):
    js = JointState()
    js.name = self.get_active_joints()
    js.position = joint_list
    return js

  def set_end_effector_link(self, _eef_link):
    MoveGroupCommander.set_end_effector_link(self, _eef_link)
    
    eef_link = _eef_link[5:]
    eef_offset = TCP_OFFSET[eef_link]
    self.ur5e.set_eef_offset(eef_offset)

  def _get_best_ik_plan(self, trans, rot):
    cur_joint = self.get_current_joint_values()
    inv_sol = self.ur5e.inv_kin_full_sorted(trans, rot, cur_joint)
    self.ur5e.print_inv_sol(inv_sol)
    
    print "="*100
    print "current q: ", cur_joint

    for i in range(8):
      if inv_sol[i]['valid']:
        selected_q = (inv_sol[i]['inv_sol'])
        print "selected q: ", selected_q

        self.ur5e.publish_state(selected_q, True)
        (success, traj, b, err) = self.plan(self._list_to_js(selected_q))
        
        if success:
          print "plan success: {}".format(b)
          user_choice = raw_input("--> press [y/n]")  
          if user_choice == 'y':
            return inv_sol[i]['idx'], traj
          else:
            continue        
        else:
          print "plan error:", b, err

    return -1, -1

  def _get_selected_ik_plan(self, trans, rot, idx):
    cur_joint = self.get_current_joint_values()
    inv_sol = self.ur5e.inv_kin_full(trans, rot, cur_joint)
    self.ur5e.print_inv_sol(inv_sol)
    
    print "="*100
    print "current q: ", cur_joint
    
    if inv_sol[idx]['valid']:
      selected_q = (inv_sol[idx]['inv_sol'])
      print "selected q: ", selected_q
      
      self.ur5e.publish_state(selected_q, True)
      (success, traj, b, err) = self.plan(self._list_to_js(selected_q))
      
      if success:
        print "plan success: {}".format(b)
        return inv_sol[idx]['idx'], traj
      else:
        print "plan error:", b, err
    
    return -1, -1

  def _get_best_ik(self, trans, rot):
    cur_joint = self.get_current_joint_values()
    inv_sol = self.ur5e.inv_kin_full_sorted(trans, rot, cur_joint)
    self.ur5e.print_inv_sol(inv_sol)
    
    print "="*100
    print "current q: ", cur_joint

    for i in range(8):
      if inv_sol[i]['valid']:
        selected_q = (inv_sol[i]['inv_sol'])
        print "selected q: ", selected_q

        self.ur5e.publish_state(selected_q, True)
        (success, traj, b, err) = self.plan(self._list_to_js(selected_q))
        
        if success:
          print "plan success: {}".format(b)
          user_choice = raw_input("--> press [y/n]")  
          if user_choice == 'y':
            return inv_sol[i]['idx'], traj
          else:
            continue        
        else:
          print "plan error:", b, err

    return -1, -1

  def go_to_initial_pose(self):
    joint_goal = [-m.pi/2, -m.pi/2,-m.pi/2,-m.pi/2, m.pi/2, m.pi]
    
    self.go(joint_goal, wait=True)
    self.stop()

  def go_to_pose_goal(self, trans, rot, idx=None):
    if idx is None:
      (s_idx, traj) = self._get_best_ik_plan(trans, rot)
    else:
      (s_idx, traj) = self._get_selected_ik_plan(trans, rot, idx)

    if s_idx >= 0:
      self.execute(traj, wait=True)
      self.stop()
    
    return s_idx

  def go_linear_to_pose_goal(self, trans, rot, idx):
    cp = self.get_current_pose()
    ce = self.get_end_effector_link()

    consts = moveit_msgs.msg.Constraints()
    oc = moveit_msgs.msg.OrientationConstraint()
    oc.header.frame_id = cp.header.frame_id
    oc.link_name = ce
    oc.orientation = cp.pose.orientation
    oc.absolute_x_axis_tolerance = 0.01
    oc.absolute_y_axis_tolerance = 0.01
    oc.absolute_z_axis_tolerance = 0.01
    oc.weight = 10
    consts.orientation_constraints = [oc]
    
    self.set_path_constraints(consts)
    s_idx = self.go_to_pose_goal(trans, rot, idx)

    print "is_cleaned?", self.clear_path_constraints()

    return s_idx

  def _grasp_to_pregrasp(self, g_trans, g_rot, g_offset):
    g_mat = utils.tf_to_mat(g_trans, g_rot)
    gp_mat = utils.tf_to_mat([0, 0, -g_offset], [0, 0, 0, 1])
    p_mat = tf.transformations.concatenate_matrices(g_mat, gp_mat)
    (p_trans, p_rot) = utils.mat_to_tf(p_mat)

    return p_trans, p_rot

  def move_to_grasp_part(self, g_trans, g_rot, g_offset):
    '''
    offset : z dir wrt grasp pose
    '''
    (pg_trans, pg_rot) \
      = self._grasp_to_pregrasp(g_trans, g_rot, g_offset)

    print "pre grasp pose| " + list_str(pg_trans, ['x','y','z']) \
            + list_str(pg_rot, ['x','y','z','w'])
    print "grasp pose| " + list_str(g_trans, ['x','y','z']) \
            + list_str(g_rot, ['x','y','z','w'])

    (result, plan) = self._get_best_ik_plan(g_trans, g_rot)
    print "******plan0=", result
    result = self.go_to_pose_goal(pg_trans, pg_rot, result)
    print "******plan1=", result
    result = self.go_linear_to_pose_goal(g_trans, g_rot, result)
    print "******plan2=", result
    result = self.go_linear_to_pose_goal(pg_trans, pg_rot, result)
    print "******plan3=", result

def main():
  rospy.init_node('move_group_wrapper_test', anonymous=True)
  mg_rob1 = MoveGroupCommanderWrapper('rob1_arm', 'rob1_real_ee_link')
  assembly_scene = Parts('part2')
  listener = tf.TransformListener()

  print "ENTER"
  raw_input()

  # mg_rob1.go_to_initial_pose()
  # print "ENTER"
  # raw_input()
  
  assembly_scene.add_mesh(PART2_PATH)
  print "ENTER"
  raw_input()

  assembly_scene.send_full_grasp_pose('part2')
  print "ENTER"
  raw_input()

  try:
    mg_rob1.set_end_effector_link('rob1_tcp_gripper_closed')
        
    print "ENTER"
    raw_input()

    grasp_offset = 0.2

    (grasp_trans, grasp_rot) \
      = listener.lookupTransform('rob1_real_base_link', 'part2_grasp', rospy.Time(0))

    mg_rob1.move_to_grasp_part(grasp_trans, grasp_rot, grasp_offset)
    

  except Exception as e:
    print e
  
  print "ENTER"
  raw_input()

if __name__ == '__main__':
  main()
