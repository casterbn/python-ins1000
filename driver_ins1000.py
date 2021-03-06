# -*- coding: utf-8 -*
"""
Driver for INS1000 Rover.
Based on PySerial https://github.com/pyserial/pyserial
Created on 2018-07-01
@author: Ocean
"""

import sys
import os
import threading
import datetime
import time
import operator
import struct
import glob
import math
import json
import collections
import serial
import serial.tools.list_ports
from message import Msg_060C_topic_0A, Msg_NTRIP
if sys.version_info[0] > 2:
    from queue import Queue
else:
    from Queue import Queue
import utility
import communicator

class RoverDriver:
    def __init__(self):
        ''' initialization
        '''
        self.cmt = communicator.SerialPort()
        # self.cmt = communicator.TCPIP()
        self.threads = []  # thread of receiver and paser
        self.exit_thread = False  # flag of exit threads
        self.exit_lock = threading.Lock()  # lock of exit_thread
        self.data_queue = Queue()  # data container
        self.data_lock = threading.Lock()  # lock of data_queue
        self.web_clients = []
        self.web_clients_lock = threading.Lock()  # lock of web_clients
        self.web_cmds = []
        self.web_cmds_lock = threading.Lock() # lock of web_cmds
        self.app = None
        self.msgs = {}
        self.cmds = {}
        self.connection_status = 0 # status of connection with device. 0: unconnected 1:connected.
        self.cmds['queryProductId'] = b'\xAF\x20\x06\x0B\x01\x00\x01\x01\x01'
        self.cmds['queryEngineVersion'] = b'\xAF\x20\x06\x0B\x01\x00\x02\x02\x02'
        self.cmds['queryFirmwareVersion'] = b'\xAF\x20\x06\x0B\x01\x00\x0C\x0C\x0C'
        self.cmds['queryInternalLeverArm'] = b'\xAF\x20\x06\x0B\x01\x00\x04\x04\x04'
        self.cmds['queryUserConfiguration'] = b'\xAF\x20\x06\x0B\x01\x00\x0A\x0A\x0A'
        self.cmds['queryNTRIPConfiguration'] = b'\xAF\x20\x06\x0A\x01\x00\x01\x01\x01'
        self.nav_pos_vel_mode = {0:'INVALID', 1:'DEAD_RECKON', 2:'STAND_ALONE', 3:'PRECISE_POINT_POSITIONING', 4:'CODE_DIFF', 5:'RTK_FLOAT', 6:'RTK_FIXED', 7:'USER_AIDING'}
        self.nav_att_mode = {0:'INVALID', 1:'COARSE', 2:'FINE'}
        self.setting_folder = os.path.join(os.getcwd(), r'setting')  # use to store some configuration files.
        self.connection_file = os.path.join(self.setting_folder, 'connection.json')
        self.rover_properties = utility.load_configuration(os.path.join(self.setting_folder, 'rover.json'))
        if not self.rover_properties:
            os._exit(1)
        print('Rover driver start at:{0}'.format(datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        threading.Thread(target=self.auto_del_timeout_web_cmds, args=()).start()
        
    def reinit(self):
        ''' re-init parameters when occur SerialException.
        '''
        self.cmt.close()
        if not self.data_queue.empty():
            self.data_queue.get()
        self.exit_thread = False
        self.threads = []  # clear threads
        if self.app:
            self.app.on_reinit()
        self.msgs.clear()
        self.connection_status = 0

    def set_app(self, app):
        self.app = app

    def add_client(self, client):
        self.web_clients_lock.acquire()
        self.web_clients.append(client)
        self.web_clients_lock.release()

    def remove_client(self, client):
        self.web_clients_lock.acquire()
        self.web_clients.remove(client)
        self.web_clients_lock.release()

    def receiver(self):
        ''' receive rover data and push data into data_queue.
            return when occur Exception
        '''
        while True:
            self.exit_lock.acquire()
            if self.exit_thread:
                self.exit_lock.release()
                self.cmt.close()
                return
            self.exit_lock.release()

            try:
                data = bytearray(self.cmt.read(self.cmt.read_size))
            except Exception as e:
                self.exit_lock.acquire()
                self.exit_thread = True  # Notice thread paser to exit.
                self.exit_lock.release()
                return  # exit thread receiver

            if len(data):
                # print(datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S:') + ' '.join('0X{0:x}'.format(data[i]) for i in range(len(data))))
                self.data_lock.acquire()
                for d in data:
                    self.data_queue.put(d)
                self.data_lock.release()
            else:
                time.sleep(0.001)

    def parser(self):
        ''' get rover data from data_queue and parse data into one whole frame.
            return when occur Exception in thread receiver.
        '''
        HEADER_05 = [0XAF, 0X20, 0X05]
        HEADER_06 = [0XAF, 0X20, 0X06]
        HEADER_07 = [0XAF, 0X20, 0X07]
        PAYLOAD_LEN_IDX = 4
        MSG_SUB_ID_IDX = 3
        MAX_FRAME_LIMIT = 500  # assume max len of frame is smaller than MAX_FRAME_LIMIT.

        sync_pattern = collections.deque(3*[0], 3)
        find_header = False
        frame = []
        payload_len = 0

        while True:
            self.exit_lock.acquire()
            if self.exit_thread:
                self.exit_lock.release()
                return  # exit thread parser
            self.exit_lock.release()

            self.data_lock.acquire()
            if self.data_queue.empty():
                self.data_lock.release()
                time.sleep(0.001)
                continue
            else:
                data = self.data_queue.get()
                self.data_lock.release()
                # print(datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S:') + hex(data))

                if find_header:
                    frame.append(data)
                    if PAYLOAD_LEN_IDX + 2 == len(frame):
                        payload_len = 256 * frame[PAYLOAD_LEN_IDX + 1] + frame[PAYLOAD_LEN_IDX]
                    elif 6 + payload_len + 2 == len(frame):  # 6: len of header; 2:len of checksum.
                        find_header = False
                        # checksum
                        result = utility.check_sum(frame[PAYLOAD_LEN_IDX + 2:PAYLOAD_LEN_IDX + payload_len + 2])
                        if result[0] == frame[-2] and result[1] == frame[-1]:
                            # find a whole frame
                            self.parse_frame(frame)
                        else:
                            print("Checksum error!")
                    else:
                        pass

                    if payload_len > MAX_FRAME_LIMIT or len(frame) > MAX_FRAME_LIMIT:
                        find_header = False
                        payload_len = 0

                else:  # if hasn't found header [0XAF, 0X20, 0X05] or [0XAF, 0X20, 0X07].
                    sync_pattern.append(data)
                    if operator.eq(list(sync_pattern), HEADER_05):
                        frame = HEADER_05[:]  # header_tp.copy()
                        find_header = True
                    elif operator.eq(list(sync_pattern), HEADER_06):
                        frame = HEADER_06[:]
                        find_header = True
                    elif operator.eq(list(sync_pattern), HEADER_07):
                        frame = HEADER_07[:]
                        find_header = True
                    else:
                        pass

    def handle_KeyboardInterrupt(self):
        ''' handle KeyboardInterrupt.
            returns: True when occur KeyboardInterrupt.
                     False when receiver and parser threads exit.
        '''
        while True:
            self.exit_lock.acquire()
            if self.exit_thread:
                self.exit_lock.release()
                return False  # return when receiver and parser threads exit
            self.exit_lock.release()

            try:
                time.sleep(0.1)
            except KeyboardInterrupt:  # response for KeyboardInterrupt such as Ctrl+C
                self.exit_lock.acquire()
                self.exit_thread = True  # Notice thread receiver and paser to exit.
                self.exit_lock.release()
                print('User stop this program by KeyboardInterrupt! File:[{0}], Line:[{1}]'.format(__file__, sys._getframe().f_lineno))
                return True

    def start_collection(self):
        ''' start two threads: receiver and parser.
            returns False when user trigger KeyboardInterrupt to stop this program.
            otherwise returns True.
        '''
        if not self.cmt.open():
            return True

        funcs = [self.receiver, self.parser]
        for func in funcs:
            t = threading.Thread(target=func, args=())
            t.start()
            print("Thread[{0}({1})] start at:[{2}].".format(t.name, t.ident, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            self.threads.append(t)

        self.query_rover_cfg_setup()
        self.connection_status = 1

        data = { 'messageType' : 'queryResponse', 'data' : {'packetType' : 'DeviceStatus', 'packet' : {'returnStatus' : 0} }}
        self.web_clients_lock.acquire()
        for client in self.web_clients:
            client.on_driver_message(data)
        self.web_clients_lock.release()

        if self.handle_KeyboardInterrupt():
            return False

        for t in self.threads:
            t.join()
            print("Thread[{0}({1})] stop at:[{2}].".format(t.name, t.ident, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        
        self.connection_status = 0
        data = { 'messageType' : 'queryResponse', 'data' : {'packetType' : 'DeviceStatus', 'packet' : {'returnStatus' : 1} }}
        self.web_clients_lock.acquire()
        for client in self.web_clients:
            client.on_driver_message(data)
        self.web_clients_lock.release()

        self.cmt.close()
        return True

    def find_device(self):
        rev = self.cmt.find_device()
        if self.app and rev:
            self.app.on_find_active_rover()
        return rev
        
    def write(self,n):
        try:
            self.cmt.write(n)
        except Exception as e:
            print(e)
            self.exit_lock.acquire()
            self.exit_thread = True  # Notice thread paser and receiver to exit.
            self.exit_lock.release()

    def get_packet_type(self):
        return self.packet_type

    def set_packet_type(self, packet_type):  # consider add lock when other thread invoke this function.
        self.packet_type = packet_type

    def parse_frame(self, frame):
        '''Parses packet payload using rover.json as reference
        '''
        PAYLOAD_LEN_IDX = 4
        payload_len = 256 * frame[PAYLOAD_LEN_IDX + 1] + frame[PAYLOAD_LEN_IDX]
        payload = frame[6:payload_len+6]   # extract the payload
        header = ''.join(["%02X" % x for x in frame[0:PAYLOAD_LEN_IDX]]).strip()
        data = []

        # Find the packet properties from Rover's JSON description
        output_packet = next((x for x in self.rover_properties['userMessages']['outputPackets'] if x['header'] == header), None)
        input_packet = next((x for x in self.rover_properties['userMessages']['inputPackets'] if x['header'] == header), None)

        if output_packet:
            var_num = None
            is_var_len_frame = False
            try:
                var_num = output_packet['var_num']
                is_var_len_frame = True
            except KeyError:  # if there is no 'var_num' key.
                pass

            if var_num is not None:  # means this is a variable length frame, such as "Satellite Signal Strength" and "SV Visibility"
                # time_start = time.time()
                data = self.unpack_output_packet_var_len(output_packet, payload)
                # time_end = time.time()
                # print('[{0}]:unpack_output_packet_var_len cost:{1}'.format(datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S'), time_end-time_start))
                pass
            else:
                data = self.unpack_output_packet(output_packet, payload, payload_len)
                self.change_scale(output_packet, data)
            if data:
                if self.app:
                    self.app.on_message(output_packet['name'], data, is_var_len_frame)
                self.packet_handler(output_packet['name'], data, is_var_len_frame)
        elif header.startswith('AF2006'): # some messages start with 'AF2006' are different decoding rule with message list in rover.json, so need to handle specially.
            self.msg_typeid_06_handler(frame)
        elif input_packet:
            # data = self.unpack_input_packet(input_packet['responsePayload'], payload)
            pass
        else:
            pass
        return data
    
    def msg_typeid_06_handler(self, frame):
        '''

        '''
        PAYLOAD_SUB_ID_IDX = 3
        PAYLOAD_LEN_IDX = 4
        PAYLOAD_TOPIC_IDX = 6
        payload_len = 256 * frame[PAYLOAD_LEN_IDX + 1] + frame[PAYLOAD_LEN_IDX]
        payload = frame[6:payload_len+6]   # extract the payload
        sub_id = frame[PAYLOAD_SUB_ID_IDX]
        topic_tp = frame[PAYLOAD_TOPIC_IDX]

        # UserConfiguration. ref msg8.4, rover report the 'IMU rotation matrix' and 'GNSS antenna lever arm' messages.
        if sub_id == 0X0C:
            if topic_tp == 0X0A: 
                msg_060C_topic_0A = Msg_060C_topic_0A(frame)

                # update GNSS lever-arm by internal lever-arm.
                if 'Internal Lever-arm' in self.msgs:
                    msgs_internal_lever_arm = self.msgs['Internal Lever-arm']
                    if msgs_internal_lever_arm['Validity']:
                        internal_lever_arm = msgs_internal_lever_arm['Internal lever-arm vector']
                        msg_060C_topic_0A.update_GNSS_lever_arm_by_internal_lever_arm(internal_lever_arm)
                self.msgs['Msg_060C_topic_0A'] = msg_060C_topic_0A

                # pack GNSS lever-arm json message.
                user_configuration_json_msg = msg_060C_topic_0A.pack_user_configuration_json_msg()
                data = { 'messageType' : 'queryResponse', 'data' : {'packetType' : 'UserConfiguration', 'packet' : user_configuration_json_msg }}
                # print ("userConfiguration:", json.dumps(data))

                cmd_type = self.get_web_cmds('queryUserConfiguration')
                if cmd_type: # send UserConfiguration to web client if web client has sent query cmd to driver.
                    # if self.app:
                    #     self.app.on_message("UserConfiguration", user_configuration_json_msg, True)
                    self.web_clients_lock.acquire()
                    for client in self.web_clients:
                        client.on_driver_message(data)
                    self.web_clients_lock.release()
            elif topic_tp == 0X04: # handle 'Internal Lever-arm' message.
                validity = payload[1] # Validity 0: Invalid, 1: Valid
                if validity:
                    v = struct.pack('24B', *payload[2:2+24]) # double[3]
                    internal_lever_arm = list(struct.unpack('<3d', v))
                    data = collections.OrderedDict()
                    data['Topic'] = 0X04
                    data['Validity'] = validity
                    data['Internal lever-arm vector'] = internal_lever_arm
                    self.msgs['Internal Lever-arm'] = data
                    # print("internal_lever_arm:", data)
                    if 'Msg_060C_topic_0A' in self.msgs:
                        msg_060C_topic_0A = self.msgs['Msg_060C_topic_0A']
                        # center = housing mark + internal
                        msg_060C_topic_0A.update_GNSS_lever_arm_by_internal_lever_arm(internal_lever_arm)
            elif topic_tp == 0X0C: # Firmware version
                len_fmt = '{0}B'.format(payload_len-1)
                b = struct.pack(len_fmt, *payload[1:])
                data = collections.OrderedDict()
                data['firmwareVersion'] = b.decode() # bytes to string
                if self.app:
                    self.app.on_message( "FirmwareVersion", data, False)

                data = { 'messageType' : 'queryResponse', 'data' : {'packetType' : 'FirmwareVersion', 'packet' : data }}
                self.web_clients_lock.acquire()
                for client in self.web_clients:
                    client.on_driver_message(data)
                self.web_clients_lock.release()
        elif sub_id == 0X06: # ref 8.1: System Response
            msg_type_request = payload[0]
            msg_sub_id_request = payload[1]
            response = payload[2]
            topic_tp = payload[3]
            # User Configuration Setup, such as IMU matrix and GNSS lever-arm
            if msg_type_request == 0X06 and msg_sub_id_request == 0X0D and topic_tp == 0X0A:
                if response == 1: #ACK
                    status = 0
                elif response == 2: #NACK
                    status = 1
                else: 
                    status = 1

                cmd_type = self.get_web_cmds('setUserConfiguration')
                if cmd_type:
                    data = { 'messageType' : 'setResponse', 'data' : {'packetType' : cmd_type, 'packet' : {'returnStatus':status} }}
                    # if self.app:
                    #     self.app.on_message("UserConfiguration", user_configuration_json_msg, True)
                    self.web_clients_lock.acquire()
                    for client in self.web_clients:
                        client.on_driver_message(data)
                    self.web_clients_lock.release()
            else:
                print('Receive system response, msg_type:{0}, msg_sub_id:{1}, topic:{2}'.format(msg_type_request, msg_sub_id_request, topic_tp))
        elif sub_id == 0X0A:
            if topic_tp == 0X03 and payload_len == 155: # NTIP query response.
                msg_NTRIP = Msg_NTRIP()
                msg_NTRIP.unpack_NTRIP_msg(frame)
                data = msg_NTRIP.pack_NTRIP_configuration_json_msg()

                data = { 'messageType' : 'queryResponse', 'data' : {'packetType' : 'NTRIPConfiguration', 'packet' : data }}
                # print ('NTRIPConfiguration:', json.dumps(data))
                
                cmd_type = self.get_web_cmds('queryNTRIPConfiguration')
                if cmd_type: # send UserConfiguration to web client if web client has sent query cmd to driver.
                    self.web_clients_lock.acquire()
                    for client in self.web_clients:
                        client.on_driver_message(data)
                    self.web_clients_lock.release()
            elif topic_tp == 0X04 or topic_tp == 0X05: 
                #  ACK of setting NTIP: AF 20 06 0A 01 00 04 04 04
                # NACK of setting NTIP: AF 20 06 0A 01 00 05 05 05
                status = 0 if topic_tp == 0X04 else 1
                data = { 'messageType' : 'setResponse', 'data' : {'packetType' : 'NTRIPConfiguration', 'packet' : {'returnStatus':status} }}
                print ('setNTRIPConfiguration:', json.dumps(data))
                cmd_type = self.get_web_cmds('setNTRIPConfiguration')
                if cmd_type:
                    self.web_clients_lock.acquire()
                    for client in self.web_clients:
                        client.on_driver_message(data)
                    self.web_clients_lock.release()
            else:
                pass
        else:
            pass

        # from pprint import pprint
        # pprint (vars(msg_060C_topic_0A))
        # print('********************')
        
    def handle_string_filed(self, value, payload, string_len):
        '''
            handle_string_filed is used to parse one type of message which Payload is only one string field, 
            such as message 5.18(Engine Version Message) and 6.1(Text Message).
        '''
        pack_fmt = string_len*'c'
        len_fmt = '{0}B'.format(string_len)
        b = struct.pack(len_fmt, *payload)
        data = struct.unpack(pack_fmt, b)
        out = [(value['name'], b.decode())] # bytes to string
        data = collections.OrderedDict(out)
        return data

    def unpack_output_packet(self, output_message, payload, payload_len):
        length = 0
        pack_fmt = '<'
        for value in output_message['payload']:
            if value['type'] == 'string':
                return self.handle_string_filed(value, payload, payload_len)
            elif value['type'] == 'float':
                pack_fmt += 'f'
                length += 4
            elif value['type'] == 'uint32':
                pack_fmt += 'I'
                length += 4
            elif value['type'] == 'int32':
                pack_fmt += 'i'
                length += 4
            elif value['type'] == 'int16':
                pack_fmt += 'h'
                length += 2
            elif value['type'] == 'uint16':
                pack_fmt += 'H'
                length += 2
            elif value['type'] == 'double':
                pack_fmt += 'd'
                length += 8
            elif value['type'] == 'int64':
                pack_fmt += 'q'
                length += 8
            elif value['type'] == 'uint64':
                pack_fmt += 'Q'
                length += 8
            elif value['type'] == 'char':
                pack_fmt += 'c'
                length += 1
            elif value['type'] == 'uchar':
                pack_fmt += 'B'
                length += 1
            elif value['type'] == 'uint8':
                pack_fmt += 'B'
                length += 1
        len_fmt = '{0}B'.format(length)
        b = struct.pack(len_fmt, *payload)
        data = struct.unpack(pack_fmt, b)
        out = [(value['name'], data[idx]) for idx, value in enumerate(output_message['payload'])]
        data = collections.OrderedDict(out)
        return data

    def unpack_output_packet_var_len(self, output_message, payload):
        length = 0
        pack_fmt = '<'
        var_num_type = output_message['var_num']['type']
        var_num_idx = output_message['var_num']['idx']
        var_num_field_idx = output_message['var_num']['field_idx']
        p = []

        if var_num_type == 'uint8':
            pack_fmt += 'B'
            length = 1
            p = payload[var_num_idx: var_num_idx+length]
        elif var_num_type == 'uint16':
            pack_fmt += 'H'
            length = 2
            p = payload[var_num_idx: var_num_idx+length]
        elif var_num_type == 'uint32':
            pack_fmt += 'I'
            length = 4
            p = payload[var_num_idx: var_num_idx+length]
        elif var_num_type == 'uint64':
            pack_fmt += 'Q'
            length = 8
            p = payload[var_num_idx: var_num_idx+length]

        len_fmt = '{0}B'.format(length)
        b = struct.pack(len_fmt, *p)
        var_num = struct.unpack(pack_fmt, b)  # eg. var_num is N_SV in "Satellite Signal Strength" frame
        if var_num[0] == 0:
            return []

        idx = 0
        var_len_one_gropu = 0
        var_pack_fmt = None

        length = 0
        pack_fmt = '<'
        for value in output_message['payload']:
            if value['type'] == 'float':
                pack_fmt += 'f'
                length += 4
            elif value['type'] == 'uint32':
                pack_fmt += 'I'
                length += 4
            elif value['type'] == 'int32':
                pack_fmt += 'i'
                length += 4
            elif value['type'] == 'int16':
                pack_fmt += 'h'
                length += 2
            elif value['type'] == 'uint16':
                pack_fmt += 'H'
                length += 2
            elif value['type'] == 'double':
                pack_fmt += 'd'
                length += 8
            elif value['type'] == 'int64':
                pack_fmt += 'q'
                length += 8
            elif value['type'] == 'uint64':
                pack_fmt += 'Q'
                length += 8
            elif value['type'] == 'char':
                pack_fmt += 'c'
                length += 1
            elif value['type'] == 'uchar':
                pack_fmt += 'B'
                length += 1
            elif value['type'] == 'uint8':
                pack_fmt += 'B'
                length += 1

            idx += 1
            if var_num_field_idx == idx:
                var_len_one_gropu = length
                var_pack_fmt = pack_fmt

        idx = 0
        field_names = []
        for idx, value in enumerate(output_message['payload']):
            field_names.append(value['name'])

        var_len_one_gropu = length - var_len_one_gropu  #eg. for "Satellite Signal Strength", var_len_one_gropu is 10. (SV system [1 Byte] + SVID [1 Byte] + L1CN0 [foat 4 Bytes] + L2CN0 [foat 4 Bytes])
        length += var_len_one_gropu * (var_num[0]-1)

        var_pack_fmt = pack_fmt[len(var_pack_fmt):len(pack_fmt)]  #eg. for "Satellite Signal Strength", var_pack_fmt is "BBff".
        var_fileld_num = len(var_pack_fmt)  #eg. for "Satellite Signal Strength", var_fileld_num is 4, the number of variable filelds.
        const_fileld_num = len(pack_fmt) - var_fileld_num - 1 #eg. for "Satellite Signal Strength", const_fileld_num is 4, the number of const filelds.
        pack_fmt += var_pack_fmt * (var_num[0]-1)

        # const_fileld_names = field_names[0:var_fileld_num+1]  #eg. for "Satellite Signal Strength", const_fileld_names is ['System time','GPS time','Receiver_ID','Antenna_ID','N_SV']
        var_fileld_names = field_names[var_fileld_num+1:len(pack_fmt)]  #eg. for "Satellite Signal Strength", var_fileld_names is ['SV_system','SVID','L1CN0','L2CN0']
        field_names += var_fileld_names * (var_num[0]-1)

        len_fmt = '{0}B'.format(length)
        b = struct.pack(len_fmt, *payload)
        payload_data = struct.unpack(pack_fmt, b)

        data = []
        info = collections.OrderedDict()
        for idx, value in enumerate(field_names):
            if idx < const_fileld_num:
                info[value] = payload_data[idx]
                if idx == const_fileld_num-1:
                    data.append(info.copy())
                    info.clear()
            else:
                info[value] = payload_data[idx]
                if len(info) == var_fileld_num:
                    data.append(info.copy())
                    info.clear()

        # print (json.dumps(data))
        # print("***************")
        return data

    def change_scale(self, output_message, data):
        '''change scaling if fild with a "Scaling" attribute.
            For example, unit of Latitude in payload is radian, but we are used to deg, so it's necessary to change scaling from radian to deg.
            returns: False when some fild changed failed, should check the rover.json.
                     True when successful.
        '''
        for value in output_message['payload']:
            try:
                Scaling = value['Scaling']
            except KeyError:  # if there is no 'Scaling' key.
                continue

            try:
                data[value['name']] = data[value['name']] * eval(Scaling)
            except Exception as e:  # value['name']  or Scaling is incorrect.
                print(e)
                return False
        return True

    def packet_handler(self, packet_type, packet, is_var_len):
        # need to restore in self.msgs
        TP_KFN  = 'KFN'
        TP_CNM  = 'CNM'
        TP_GH   = 'GH'
        TP_SA   = 'SA' # Sensor Activity
        TP_NCA  = 'NCA' # NTRIP Client Activity
        # NO need to push to self.msgs        
        TP_SSS  = 'SSS'
        TP_GSVM = 'GSVM'
        TP_TSM  = 'TSM'
        # msg_type should set to 'queryResponse' in Json msg.
        TP_PID  = 'ProductID'
        TP_EV   = 'EngineVersion'
        # construct new type of message.
        TP_NAV  = 'NAV'
        TP_SS   = 'SS' # Subsystems Status

        msg_type = 'event'
        # self.msgs is used to restore the newest packets.
        if TP_KFN == packet_type:
            self.msgs[TP_KFN] = packet
        elif TP_CNM == packet_type:
            self.msgs[TP_CNM] = packet
        elif TP_GH == packet_type:
            self.msgs[TP_GH] = packet
        elif TP_SA == packet_type:
            self.msgs[TP_SA] = packet
        elif TP_NCA == packet_type:
            self.msgs[TP_NCA] = packet
        elif TP_PID == packet_type:
            msg_type = 'queryResponse'
            if not isinstance(packet['Product ID'], str):
                packet['Product ID'] = str(packet['Product ID'])
        elif TP_EV == packet_type:
            msg_type = 'queryResponse'
        else:
            pass

        # send to web client.
        data = { 'messageType' : msg_type, 'data' : {'packetType' : packet_type, 'packet' : packet }}
        self.web_clients_lock.acquire()
        for client in self.web_clients:
            client.on_driver_message(data, packet, is_var_len)
        self.web_clients_lock.release()

        '''
        Driver has to construct some packets based on existing packets,such as:
        1. 'NAV' (navigation information) packet which based on 'KFN','CNM' and 'GH'.
        2. 'SS' packet which based on 'SA' and 'NCA'
        '''
        # make sure have received 'KFN', 'CNM' and 'GH' already before construct 'NAV'
        if TP_KFN in self.msgs and TP_CNM in self.msgs and TP_GH in self.msgs and TP_CNM == packet_type:
            r2d = 180/math.pi
            pos_rms_n = self.msgs[TP_CNM]['Position RMS-N']
            pos_rms_e = self.msgs[TP_CNM]['Position RMS-E']
            pos_rms_d = self.msgs[TP_CNM]['Position RMS-D']
            vel_rms_n = self.msgs[TP_CNM]['Velocity RMS-N']
            vel_rms_e = self.msgs[TP_CNM]['Velocity RMS-E']
            vel_rms_d = self.msgs[TP_CNM]['Velocity RMS-D']
            att_rms_n = self.msgs[TP_CNM]['Attitude RMS-N']
            att_rms_e = self.msgs[TP_CNM]['Attitude RMS-E']
            att_rms_d = self.msgs[TP_CNM]['Attitude RMS-D']
            q0 = self.msgs[TP_CNM]['Attitude quaternion-Scalar']
            q1 = self.msgs[TP_CNM]['Attitude quaternion-X']
            q2 = self.msgs[TP_CNM]['Attitude quaternion-Y']
            q3 = self.msgs[TP_CNM]['Attitude quaternion-Z']
            euler_angle = utility.cal_attitude(q0, q1, q2, q3)

            nav = collections.OrderedDict()
            nav['System time'] = int(self.msgs[TP_KFN]['System time'])
            nav['Time of week'] = self.msgs[TP_CNM]['Time of week']
            nav['GPS week'] = self.msgs[TP_CNM]['GPS week']
            nav['Position mode'] = self.nav_pos_vel_mode[self.msgs[TP_KFN]['Position mode']]
            nav['Latitude'] = self.msgs[TP_CNM]['Latitude']
            nav['Longitude'] = self.msgs[TP_CNM]['Longitude']
            nav['Ellipsoidal height'] = self.msgs[TP_CNM]['Ellipsoidal height']
            nav['MSL height'] = self.msgs[TP_CNM]['Ellipsoidal height'] - self.msgs[TP_GH]['Geoid height']
            nav['Position RMS'] = math.sqrt(math.pow(pos_rms_n,2)+math.pow(pos_rms_e,2)+math.pow(pos_rms_d,2))
            nav['Velocity mode'] = self.nav_pos_vel_mode[self.msgs[TP_KFN]['Velocity mode']]
            nav['Vel N'] = self.msgs[TP_CNM]['Vel N']
            nav['Vel E'] = self.msgs[TP_CNM]['Vel E']
            nav['Vel D'] = self.msgs[TP_CNM]['Vel D']
            nav['Velocity RMS'] = math.sqrt(math.pow(vel_rms_n,2)+math.pow(vel_rms_e,2)+math.pow(vel_rms_d,2))
            nav['Attitude status'] = self.nav_att_mode[self.msgs[TP_KFN]['Attitude status']]
            nav['Roll'] = euler_angle[0]*r2d
            nav['Pitch'] = euler_angle[1]*r2d
            nav['Heading'] = euler_angle[2]*r2d
            nav['Attitude RMS'] = math.sqrt(math.pow(att_rms_n,2)+math.pow(att_rms_e,2)+math.pow(att_rms_d,2))
            # nav['Accel_X'] = self.msgs[TP_CNM]['Accel_X']
            # nav['Accel_Y'] = self.msgs[TP_CNM]['Accel_Y']
            # nav['Accel_Z'] = self.msgs[TP_CNM]['Accel_Z']
            # nav['Gyro_X'] = self.msgs[TP_CNM]['Gyro_X']
            # nav['Gyro_Y'] = self.msgs[TP_CNM]['Gyro_Y']
            # nav['Gyro_Z'] = self.msgs[TP_CNM]['Gyro_Z']

            if self.app:
                self.app.on_message(TP_NAV, nav, False)

            data = { 'messageType' : 'event', 'data' : {'packetType' : TP_NAV, 'packet' : nav }}
            self.web_clients_lock.acquire()
            for client in self.web_clients:
                client.on_driver_message(data, nav, False)
            self.web_clients_lock.release()
            # print (json.dumps(nav))
            # print("***************")        
        elif TP_SA == packet_type:
            data = collections.OrderedDict()
            data['IMU Status'] = 1 if packet['IMU message count'] > 0 else 0
            data['GNSS Status'] = 1 if packet['GNSS message count'] > 0 else 0
            data['PPS Status'] = 1 if packet['PPS count'] > 0 else 0
            data['NTRIP Status'] = 0
            self.msgs[TP_SS] = data
            if self.app:
                self.app.on_message(TP_SS, data, False)

            web_data = { 'messageType' : 'event', 'data' : {'packetType' : TP_SS, 'packet' : data }}
            self.web_clients_lock.acquire()
            for client in self.web_clients:
                client.on_driver_message(web_data, data, False)
            self.web_clients_lock.release()
        elif TP_NCA == packet_type:
            data = collections.OrderedDict()
            data['IMU Status']   = 0
            data['GNSS Status']  = 0
            data['PPS Status']   = 0
            data['NTRIP Status'] = 1 if packet['NTRIP message size'] > 0 else 0
            self.msgs[TP_SS] = data
            if self.app:
                self.app.on_message(TP_SS, data, False)

            web_data = { 'messageType' : 'event', 'data' : {'packetType' : TP_SS, 'packet' : data }}
            self.web_clients_lock.acquire()
            for client in self.web_clients:
                client.on_driver_message(web_data, data, False)
            self.web_clients_lock.release()
        else:
            pass

    def handle_cmd_msg(self, message):
        '''
        Prase command message from web clint, 
        and send corresponding hex format command message to rover.
        '''
        CMD_TP_EVENT = 'event'
        CMD_TP_QUERY = 'query'
        CMD_TP_SET = 'set'
        
        CMD_MODEL = 'Model'
        CMD_PRODUCT_ID = 'ProductID'
        CMD_ENGINE_VERSION = 'EngineVersion'
        CMD_FIRMWARE_VERSION = 'FirmwareVersion'
        CMD_IMU_ROTATION_MATRIX = 'IMURotationMatrix'
        CMD_GNSS_ANTENNA_LEVER_ARM = 'GNSSAntennaLeverArm'
        CMD_USER_CONFIGURAION = 'UserConfiguration'
        CMD_NTRIP_CONFIGURAION = 'NTRIPConfiguration'

        if message['messageType'] == CMD_TP_QUERY:
            if message['data']['packetType'] == CMD_MODEL:
                data = collections.OrderedDict()
                data[CMD_MODEL] = 'INS1000'
                packet = { 'messageType' : 'queryResponse', 'data' : {'packetType' : CMD_MODEL, 'packet' : data }}
                # print (CMD_MODEL, json.dumps(packet))
                self.web_clients_lock.acquire()
                for client in self.web_clients:
                    client.all_packets.append(packet)
                self.web_clients_lock.release()
            elif message['data']['packetType'] == CMD_PRODUCT_ID:
                self.write(self.cmds['queryProductId'])
            elif message['data']['packetType'] == CMD_ENGINE_VERSION:
                self.write(self.cmds['queryEngineVersion'])
            elif message['data']['packetType'] == CMD_FIRMWARE_VERSION:
                self.write(self.cmds['queryFirmwareVersion'])
            elif message['data']['packetType'] == CMD_USER_CONFIGURAION:
                self.web_cmds_lock.acquire()
                self.web_cmds.append({'queryUserConfiguration' : datetime.datetime.now()})
                self.web_cmds_lock.release()
                self.write(self.cmds['queryUserConfiguration'])
            elif message['data']['packetType'] == CMD_NTRIP_CONFIGURAION:
                self.web_cmds_lock.acquire()
                self.web_cmds.append({'queryNTRIPConfiguration' : datetime.datetime.now()})
                self.web_cmds_lock.release()
                self.write(self.cmds['queryNTRIPConfiguration'])
            else:
                pass
        elif message['messageType'] == CMD_TP_SET:
            if message['data']['packetType'] == CMD_IMU_ROTATION_MATRIX:
                # matrix = list(message['data']['packet'])
                matrix = message['data']['packet']
                if 'Msg_060C_topic_0A' in self.msgs:
                    self.web_cmds_lock.acquire()
                    self.web_cmds.append({'setIMURotationMatrix' : datetime.datetime.now()})
                    self.web_cmds_lock.release()
                    msg_060C_topic_0A = self.msgs['Msg_060C_topic_0A']
                    msg_060C_topic_0A.set_imu_rotation_matrix(matrix)
                    msg_060C_topic_0A.pack_msg_060D()
                    self.write(msg_060C_topic_0A.msg_060D_cmd)
                    # l=[] # for debug
                    # for b in msg_060C_topic_0A.msg_060D_cmd:
                    #     l.append(hex(b))
                    # print(l)
                else:
                    self.write(self.cmds['queryUserConfiguration'])
                    # send NACK to web client

            elif message['data']['packetType'] == CMD_GNSS_ANTENNA_LEVER_ARM:
                packet = message['data']['packet']
                antenna_num = packet[0]['Antenna_num']
                lever_arm_wrt_imu_center = True if (packet[0]['LeverArm WRT'] == 'IMU Center') else False
                lever_arms = {}
                for i in range(1, antenna_num+1):
                    lever_arms[packet[i]['Antenna_ID']] = [packet[i]['LeverArm_X'],packet[i]['LeverArm_Y'],packet[i]['LeverArm_Z']]
                # ensure lever-arm is sorted by Antenna_ID.
                lever_arm = [lever_arms[k] for k in sorted(lever_arms.keys())] 
                if 'Msg_060C_topic_0A' in self.msgs:
                    self.web_cmds_lock.acquire()
                    self.web_cmds.append({'setGNSSAntennaLeverArm' : datetime.datetime.now()})
                    self.web_cmds_lock.release()

                    msg_060C_topic_0A = self.msgs['Msg_060C_topic_0A']
                    if lever_arm_wrt_imu_center:
                        msg_060C_topic_0A.set_GNSS_lever_arm_center(lever_arm)
                    else:
                        msg_060C_topic_0A.set_GNSS_lever_arm_housing_mark(lever_arm)
                    msg_060C_topic_0A.pack_msg_060D()
                    self.write(msg_060C_topic_0A.msg_060D_cmd)
                else:
                    self.write(self.cmds['queryUserConfiguration'])
                    # send NACK to web client

            elif message['data']['packetType'] == CMD_NTRIP_CONFIGURAION:
                self.web_cmds_lock.acquire()
                self.web_cmds.append({'setNTRIPConfiguration' : datetime.datetime.now()})
                self.web_cmds_lock.release()

                packet = message['data']['packet']
                msg_NTRIP = Msg_NTRIP()
                msg_NTRIP.pack_msg_NTRIP(packet)
                # cmd = [hex(d) for d in msg_NTRIP.msg_ntrip_cmd]
                # print(datetime.datetime.now().strftime('%Y_%m_%d_%H_%M_%S:') + " ".join(cmd))
                self.write(msg_NTRIP.msg_ntrip_cmd)

        else:
            pass
        pass

    def query_rover_cfg_setup(self):
        '''
        query rover configurations setup
        '''
        self.write(self.cmds['queryInternalLeverArm'])
        self.write(self.cmds['queryUserConfiguration'])
        self.write(self.cmds['queryNTRIPConfiguration'])
        pass

    def auto_del_timeout_web_cmds(self):
        TIME_OUT = 5
        while (True):
            now = datetime.datetime.now()
            self.web_cmds_lock.acquire()
            len_reversed_web_client = len(self.web_cmds)
            for idx, cmd in enumerate(reversed(self.web_cmds)):
                if (now-list(cmd.values())[0]).total_seconds() > TIME_OUT:
                    del self.web_cmds[len_reversed_web_client-idx-1]
            self.web_cmds_lock.release()
            time.sleep(0.5)
        pass

    def get_web_cmds(self, cmd_type):
        _cmd_tp = None
        self.web_cmds_lock.acquire()
        for idx, cmd in enumerate(self.web_cmds):
            if cmd_type == 'setUserConfiguration':
                if list(cmd.keys())[0] == 'setIMURotationMatrix':
                    _cmd_tp = 'IMURotationMatrix'
                    del self.web_cmds[idx]
                    break                    
                elif list(cmd.keys())[0] == 'setGNSSAntennaLeverArm':
                    _cmd_tp = 'GNSSAntennaLeverArm'
                    del self.web_cmds[idx]
                    break                    
                else:
                    pass
            elif list(cmd.keys())[0] == cmd_type:
                _cmd_tp = cmd_type
                del self.web_cmds[idx]
                break
            else:
                pass    
        self.web_cmds_lock.release()
        return _cmd_tp


if __name__ == '__main__':
    pass
