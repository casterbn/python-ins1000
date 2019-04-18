# -*- coding: utf-8 -*
"""
Created on 2019-04-09
@author: Ocean
"""
import struct
import copy
import utility
import collections

class Msg_060C_topic_0A(object):
    def __init__(self, frame):
        ''' initialization
        '''
        self.frame = frame
        self.payload_len = 0
        self.topic = 0
        self.indicators = 0
        self.flags = 0
        self.ICD_num = 0
        self.min_vel = 0
        self.max_unaided_time = 0
        self.max_output_rate = 0
        self.imu_rotation_matrix = []
        self.output_position_offset = []
        self.smooth_mode = 0
        self.GNSS_lever_arm_center = [] #shape: [antenna_num][3]
        self.GNSS_lever_arm_housing_mark = [] #shape: [antenna_num][3]
        self.internal_lever_arm = []
        self.GNSS_lever_arm_uncertainty = []
        self.ICD_configuration = []
        # DMI configurations
        self.DMI_id = 0
        self.DMI_scale_factor = 0
        self.DMI_lever_arm= []
        self.DMI_lever_arm_uncertainty = 0
        self.DMI_options = 0
        # get from self.indicators
        self.extended_version_flag = 0
        self.antenna_num = 0
        self.DMI_exists = 0
        # get from self.flags
        self.flags_init_heading_from_GNSS_vel = True
        self.flags_leverarm_from_imu_center
        # used to packet the '8.4 User Configuration Setup' message.
        self.msg_060D_cmd = ''

        self.SCALING_MAX_OUTPUT_RATE = 1.0e-1
        self.SCALING_OUTPUT_POSITION_OFFSET = 1.0e-4
        self.SCALING_LEVER_ARM = 1.0e-4
        self.SCALING_LEVER_ARM_UNCERTAINTY = 1.0e-2
        self.SCALING_DMI_LEVER_ARM = 1.0e-4
        self.SCALING_DMI_LEVER_ARM_UNCERTAINTY = 1.0e-2

        self.unpack_msg_060C_topic_0A()
        pass

    def unpack_msg_060C_topic_0A(self):
        '''
        parse AF20060C0A message which topic is 0A.
        '''
        PAYLOAD_LEN_IDX = 4
        payload_len = 256 * self.frame[PAYLOAD_LEN_IDX + 1] + self.frame[PAYLOAD_LEN_IDX]
        payload = self.frame[6:payload_len+6]   # extract the payload
        
        MASK_ANTENNA_NUM = 3
        MASK_EXTENDED_VERSION_FLAG = 8
        MASK_DMI_EXISTS = 4
        MASK_FLAGS_INIT_HEADING_FROM_GNSS_VEL = 1
        MASK_FLAGS_LEVERARM_FROM_IMU_CENTER = 4

        i = 0
        self.topic = payload[i] # uint8_t
        i+=1

        self.indicators = payload[i] # uint8_t
        # antenna_num is the 1st and 2nd bits in 'Aiding sensor indicators' filed.
        self.antenna_num = self.indicators & MASK_ANTENNA_NUM
        # extended_version_flag is the 3rd bit in 'Aiding sensor indicators' filed.
        self.extended_version_flag = (self.indicators & MASK_EXTENDED_VERSION_FLAG > 0) 
        # DMI_exists flag is the 4 bits in 'Aiding sensor indicators' filed.
        self.DMI_exists = self.indicators & MASK_DMI_EXISTS
        i+=1

        self.flags = payload[i] # uint8_t
        # if flags_init_heading_from_GNSS_vel is True, means Enable "Initialize heading from GNSS velocity".        
        self.flags_init_heading_from_GNSS_vel = (self.flags & MASK_FLAGS_INIT_HEADING_FROM_GNSS_VEL == 0)   
        # if flags_leverarm_from_imu_center is False, means leverarm is w.r.t housing mark        
        self.flags_leverarm_from_imu_center = (self.flags & MASK_FLAGS_LEVERARM_FROM_IMU_CENTER == 0)   
        i+=1

        self.ICD_num = payload[i] # uint8_t
        i+=1

        self.min_vel = payload[i] # uint8_t
        i+=1

        self.max_unaided_time = payload[i+1]*256+payload[i] # uint16_t
        i+=2

        self.max_output_rate = payload[i+1]*256+payload[i] # uint16_t
        i+=2

        v = struct.pack('72B', *payload[i:i+72]) # double[3][3]
        self.imu_rotation_matrix = list(struct.unpack('<9d', v))
        i+=72

        v = struct.pack('12B', *payload[i:i+12]) # # int32_t[3]
        self.output_position_offset = list(struct.unpack('<3i', v))
        i+=12

        if self.extended_version_flag:
            self.smooth_mode = payload[i] # uint8_t
            i+=1

        # data_int = int.from_bytes(payload[i:i+4], byteorder='little', signed=True)
        fmt = '{0}B'.format(4*self.antenna_num*3) 
        v = struct.pack(fmt, *payload[i:i+4*self.antenna_num*3]) 
        fmt = '<{0}i'.format(self.antenna_num*3) #int32[antenna_num][3]
        l = list(struct.unpack(fmt, v))
        if self.flags_leverarm_from_imu_center:
            self.GNSS_lever_arm_center = ([l[n:n + 3] for n in range(0, len(l), 3)]) #eg.[[0.2819, 0.0036, -0.0673], [-0.3277, 0.0036, -0.0673]]
        else:
            self.GNSS_lever_arm_housing_mark = ([l[n:n + 3] for n in range(0, len(l), 3)]) #eg.[[0.2819, 0.0036, -0.0673], [-0.3277, 0.0036, -0.0673]]
        i += 4*self.antenna_num*3

        if self.extended_version_flag:
            fmt = '{0}B'.format(2*self.antenna_num)
            v = struct.pack(fmt, *payload[i:i+2*self.antenna_num]) 
            fmt = '<{0}H'.format(self.antenna_num) #uint16_t[nA]
            self.GNSS_lever_arm_uncertainty = list(struct.unpack(fmt, v))
            i += 2*self.antenna_num

        if self.ICD_num > 0:
            self.ICD_configuration = list(p for p in payload[i:i+2*self.ICD_num]) # uint8_t[ICD_num*2]
            i += 2*self.ICD_num

        # Note: haven't verify below code snippet since have no virtual hex data with DMI info.
        # DMI configuration block. 
        if self.DMI_exists > 0:
            
            self.DMI_id = payload[i]
            i+=1

            v = struct.pack('8B', *payload[i:i+8]) # 1 double
            self.DMI_scale_factor = struct.unpack('<d', v)[0]
            i+=8

            v = struct.pack('12B', *payload[i:i+12]) # int32_t[3]
            self.DMI_lever_arm = list(struct.unpack('<3i', v))
            i+=12

            if self.extended_version_flag:
                v = struct.pack('2B', *payload[i:i+2]) # uint16_t
                self.DMI_lever_arm_uncertainty = struct.unpack('<H', v)[0]
                i+=2
                self.DMI_options = payload[i]

    def pack_msg_060D(self):
        '''
        pack 060D message. ref 8.4. User Configuration Setup.
        '''
        MASK_ANTENNA_NUM = 3
        MASK_EXTENDED_VERSION_FLAG = 8
        MASK_DMI_EXISTS = 4
        MASK_FLAGS_LEVERARM_FROM_IMU_CENTER = 4

        FRAME_HEADER = bytearray(b'\xAF\x20\x06\x0D')
        self.msg_060D_cmd = copy.deepcopy(FRAME_HEADER)
        self.msg_060D_cmd.append(self.topic) # uint8_t
        self.msg_060D_cmd.append(self.indicators) # uint8_t
        if self.flags_leverarm_from_imu_center:
            self.flags = (self.flags & (~MASK_FLAGS_LEVERARM_FROM_IMU_CENTER))  # set bit 2 to 0.            
        else:
            self.flags = (self.flags | MASK_FLAGS_LEVERARM_FROM_IMU_CENTER)              
        self.msg_060D_cmd.append(self.flags) # uint8_t
        self.msg_060D_cmd.append(self.ICD_num) # uint8_t
        self.msg_060D_cmd.append(self.min_vel) # uint8_t
        v = self.max_unaided_time.to_bytes(2, byteorder='little', signed=False) # uint16_t
        self.msg_060D_cmd += v

        v = (self.max_output_rate).to_bytes(2, byteorder='little', signed=False) # uint16_t
        # v = (1051).to_bytes(2, byteorder='little', signed=False) # uint16_t
        self.msg_060D_cmd += v

        v = struct.pack('<9d', *(self.imu_rotation_matrix)) # double[3][3]
        self.msg_060D_cmd += v

        v = struct.pack('<3i', *(list(int(p) for p in self.output_position_offset))) # int32_t[3]
        self.msg_060D_cmd += v

        if self.extended_version_flag:
            self.msg_060D_cmd.append(self.smooth_mode) # uint8_t

        fmt = '<{0}i'.format(self.antenna_num*3) #int32_t[antenna_num][3]
        v=[]
        if self.flags_leverarm_from_imu_center:
            for lever_arm in self.GNSS_lever_arm_center:
                v+=lever_arm
        else:
            for lever_arm in self.GNSS_lever_arm_housing_mark:
                v+=lever_arm
        v = struct.pack(fmt, *v) 
        self.msg_060D_cmd += v

        if self.extended_version_flag: #uint16_t[nA]
            fmt = '<{0}H'.format(self.antenna_num)
            v = struct.pack(fmt, *(self.GNSS_lever_arm_uncertainty))
            self.msg_060D_cmd += v

        if self.ICD_num > 0:
            fmt = '<{0}B'.format(2*self.ICD_num) # uint8_t[ICD_num*2]
            v = struct.pack(fmt, *(self.ICD_configuration))
            self.msg_060D_cmd += v


        # Note: haven't verify below code snippet since have no virtual hex data with DMI info.
        # DMI configuration block. 
        if self.DMI_exists > 0:
            self.msg_060D_cmd.append(self.DMI_exists) # uint8_t

            v = struct.pack('<d', self.DMI_scale_factor) # double
            self.msg_060D_cmd += v

            v = struct.pack('<3i', *(self.DMI_lever_arm)) # int32_t[3]
            self.msg_060D_cmd += v

            if self.extended_version_flag:
                v = struct.pack('<H', self.DMI_lever_arm_uncertainty) # uint16_t
                self.msg_060D_cmd += v
                self.msg_060D_cmd.append(self.DMI_options) # uint8_t

        # fill payload length.
        msg_060D_payload_length = len(self.msg_060D_cmd) - len(FRAME_HEADER)
        v = msg_060D_payload_length.to_bytes(2, byteorder='little', signed=False) # uint16_t
        PAYLOAD_LEN_IDX = 4
        self.msg_060D_cmd[PAYLOAD_LEN_IDX:PAYLOAD_LEN_IDX] = v
        # fill check_sum.
        result = utility.check_sum(self.msg_060D_cmd[PAYLOAD_LEN_IDX + 2:])
        self.msg_060D_cmd.append(result[1]) 
        self.msg_060D_cmd.append(result[0]) 
        pass

    def get_max_output_rate(self):
        return self.max_output_rate * self.SCALING_MAX_OUTPUT_RATE

    def set_max_output_rate(self, max_output_rate):
        self.max_output_rate = int(max_output_rate / self.SCALING_MAX_OUTPUT_RATE)

    def get_output_position_offset(self):
        return list(p*self.SCALING_OUTPUT_POSITION_OFFSET for p in self.output_position_offset)

    def set_output_position_offset(self, utput_position_offset):
        self.output_position_offset = list(int(p/self.SCALING_OUTPUT_POSITION_OFFSET) for p in utput_position_offset)

    def get_imu_rotation_matrix(self):
        data = collections.OrderedDict()
        for i, c in enumerate(self.imu_rotation_matrix):
            data['C{0}'.format(i)] = c
        return data

    def set_imu_rotation_matrix(self, matrix):
        if len(matrix) != 9:
            raise ValueError("Size of IMU Rotation Matrix is incorrect!")
        self.imu_rotation_matrix = matrix

    def get_GNSS_lever_arm_center(self):
        GNSS_lever_arm_center = []
        for an in range(self.antenna_num):
            GNSS_lever_arm_center.append([p*self.SCALING_LEVER_ARM for p in self.GNSS_lever_arm_center[an] ])
        return GNSS_lever_arm_center

    # center = housing mark + internal
    def set_GNSS_lever_arm_center(self, lever_arm):
        if len(lever_arm) != self.antenna_num or len(lever_arm[0]) != 3:
            raise ValueError("Size of GNSS Lever arm is incorrect!")

        GNSS_lever_arm_center = []
        for an in range(self.antenna_num):
            GNSS_lever_arm_center.append([int(p/self.SCALING_LEVER_ARM) for p in lever_arm[an] ])
        self.GNSS_lever_arm_center = GNSS_lever_arm_center

        self.GNSS_lever_arm_housing_mark = []
        for an in range(self.antenna_num):
            self.GNSS_lever_arm_housing_mark.append([self.GNSS_lever_arm_center[an][i] - self.internal_lever_arm[i] for i in range(3) ])

    def get_GNSS_lever_arm_housing_mark(self):
        GNSS_lever_arm_housing_mark = []
        if len(self.GNSS_lever_arm_housing_mark) == 0:
            return GNSS_lever_arm_housing_mark
        for an in range(self.antenna_num):
            GNSS_lever_arm_housing_mark.append([p*self.SCALING_LEVER_ARM for p in self.GNSS_lever_arm_housing_mark[an] ])
        return GNSS_lever_arm_housing_mark

    def set_GNSS_lever_arm_housing_mark(self, lever_arm):
        if len(lever_arm) != self.antenna_num or len(lever_arm[0]) != 3:
            raise ValueError("Size of GNSS Lever arm is incorrect!")

        GNSS_lever_arm_housing_mark = []
        for an in range(self.antenna_num):
            GNSS_lever_arm_housing_mark.append([int(p/self.SCALING_LEVER_ARM) for p in lever_arm[an] ])
        self.GNSS_lever_arm_housing_mark = GNSS_lever_arm_housing_mark

        self.GNSS_lever_arm_center = []
        for an in range(self.antenna_num):
            self.GNSS_lever_arm_center.append([self.GNSS_lever_arm_housing_mark[an][i] + self.internal_lever_arm[i] for i in range(3) ])

    def update_GNSS_lever_arm_by_internal_lever_arm(self, internal_lever_arm):
        self.internal_lever_arm = [int(p/self.SCALING_LEVER_ARM) for p in internal_lever_arm]

        if self.flags_leverarm_from_imu_center:
            for an in range(self.antenna_num):
                self.GNSS_lever_arm_housing_mark.append([self.GNSS_lever_arm_center[an][i] - self.internal_lever_arm[i] for i in range(3) ])
        else:
            for an in range(self.antenna_num):
                self.GNSS_lever_arm_center.append([self.GNSS_lever_arm_housing_mark[an][i] + self.internal_lever_arm[i] for i in range(3) ])

