import sys
import os
import time
import datetime
import json
import rover_application_base
import driver_ins1000


class RoverLogApp(rover_application_base.RoverApplicationBase):
    def __init__(self, user=False):
        '''Initialize and create a CSV file
        '''
        self.start_time = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        if not self.load_configuration():
            os._exit(1)
        if not os.path.exists('data/'):
            os.mkdir('data/')
        self.output_packets = self.rover_properties['userMessages']['outputPackets']
        self.first_row = {}
        self.log_file_names = {}
        self.log_files = {}
        try:
            for packet in self.output_packets:
                self.first_row[packet['name']] = 0
                self.log_file_names[packet['name']] = packet['name'] +'-' + self.start_time + '.csv'
                self.log_files[packet['name']] = open('data/' + self.log_file_names[packet['name']], 'w')# just log Compact Navigation Message
        except:
            pass

    def on_reinit(self):
        print ("RoverLogApp.on_reinit()")
        pass
        # Is it necessary to create a new file to log when replug serial connector?

        # self.start_time = datetime.datetime.now().strftime('%Y%m%d_%H_%M_%S')
        # try:
        #     for packet in self.output_packets:
        #         self.first_row[packet['name']] = 0
        #         self.log_file_names[packet['name']] = packet['name'] +'-' + self.start_time + '.csv'
        #         self.log_files[packet['name']] = open('data/' + self.log_file_names[packet['name']], 'w')# just log Compact Navigation Message
        # except:
        #     pass

    def on_find_active_rover(self):
        print ("RoverLogApp.on_find_active_rover()")

    def on_message(self, *args):
        packet_type = args[0]
        self.data = args[1]
        is_var_len_frame = args[2]
        if is_var_len_frame:
            self.log_var_len(self.data, packet_type)
        else:
            self.log(self.data, packet_type)

    def on_exit(self):
        pass

    def load_configuration(self):
        '''
        load properties from 'rover.json'
        returns: True when load successfully.
                 False when load failed.
        '''
        try:
            with open('setting/rover.json') as json_data:
                self.rover_properties = json.load(json_data)
            return True
        # except (ValueError, KeyError, TypeError) as error:
        except Exception as e:
            print(e)
            return Falsez

    def log(self, data, packet_type):
        ''' Parse the data, read in from the unit, and generate a data file using
            the json properties file to create a header and specify the precision
            of the data in the resulting data file.
        '''
        if not self.rover_properties:
            return

        output_packet = next((x for x in self.rover_properties['userMessages']['outputPackets'] if x['name'] == packet_type), None)

        '''Write row of CSV file based on data received.  Uses dictionary keys for column titles
        '''
        if not self.first_row[packet_type]:
            self.first_row[packet_type] = 1

            # Loop through each item in the data dictionary and create a header from the json
            #   properties that correspond to the items in the dictionary
            labels = ''
            keyIdx = -1
            for key in data:
                keyIdx= keyIdx + 1
                '''dataStr = output_packet['payload'][keyIdx]['name'] + \
                          ' [' + \
                          output_packet['payload'][keyIdx]['unit'] + \
                          ']'''
                dataStr = output_packet['payload'][keyIdx]['name']
                labels = labels + '{0:s},'.format(dataStr)

            # Remove the comma at the end of the string and append a new-line character
            labels = labels[:-1]
            header = labels + '\n'
        else:
            self.first_row[packet_type] += 1
            header = ''


        # Loop through the items in the data dictionary and append to an output string
        #   (with precision based on the data type defined in the json properties file)
        str = ''
        keyIdx = -1
        for key in data:
            keyIdx= keyIdx + 1
            outputPcktType = output_packet['payload'][keyIdx]['type']

            if outputPcktType == 'uint32' or outputPcktType == 'int32' or \
               outputPcktType == 'uint16' or outputPcktType == 'int16' or \
               outputPcktType == 'uint64' or outputPcktType == 'int64':
                # integers and unsigned integers
                str += '{0:d},'.format(data[key])
            elif outputPcktType == 'double':
                # double
                str += '{0:15.12f},'.format(data[key])
            elif outputPcktType == 'float':
                # print(3) #key + str(2))
                str += '{0:12.8f},'.format(data[key])
            elif outputPcktType == 'uint8':
                # byte
                str += '{0:d},'.format(data[key])
            elif outputPcktType == 'uchar' or outputPcktType == 'char':
                # character
                str += '{:},'.format(data[key])
            else:
                # unknown
                str += '{0:3.5f},'.format(data[key])
        # 
        str = str[:-1]
        str = str + '\n'
        self.log_files[packet_type].write(header+str)

    def log_var_len(self, data, packet_type):
        ''' Parse the data, read in from the unit, and generate a data file using
            the json properties file to create a header and specify the precision
            of the data in the resulting data file.
        '''
        if not self.rover_properties:
            return

        output_packet = next((x for x in self.rover_properties['userMessages']['outputPackets'] if x['name'] == packet_type), None)

        '''Write row of CSV file based on data received.  Uses dictionary keys for column titles
        '''
        if not self.first_row[packet_type]:
            self.first_row[packet_type] = 1

            # Loop through each item in the data dictionary and create a header from the json
            #   properties that correspond to the items in the dictionary
            labels = ''
            for value in output_packet['payload']:
                dataStr = value['name']
                labels = labels + '{0:s},'.format(dataStr)
            # Remove the comma at the end of the string and append a new-line character
            labels = labels[:-1]
            header = labels + '\n'
        else:
            self.first_row[packet_type] += 1
            header = ''

        # Loop through the items in the data dictionary and append to an output string
        #   (with precision based on the data type defined in the json properties file)
        str = ''
        const_str = ''
        var_str = ''
        var_fileld_tpyes = []
        var_fileld_num = len(output_packet['payload']) - output_packet['var_num']['field_idx']
        const_fileld_num = len(output_packet['payload']) - var_fileld_num

        for idx, value in enumerate(output_packet['payload']):
            if idx >= const_fileld_num:
                var_fileld_tpyes.append(value['type'])

        for idx, key in enumerate(data):
            if idx < const_fileld_num:
                outputPcktType = output_packet['payload'][idx]['type']

                if outputPcktType == 'uint32' or outputPcktType == 'int32' or \
                outputPcktType == 'uint16' or outputPcktType == 'int16' or \
                outputPcktType == 'uint64' or outputPcktType == 'int64':
                    # integers and unsigned integers
                    const_str += '{0:d},'.format(list(key.values())[0])
                elif outputPcktType == 'double':
                    # double
                    const_str += '{0:15.12f},'.format(list(key.values())[0])
                elif outputPcktType == 'float':
                    # print(3) #key + str(2))
                    const_str += '{0:12.8f},'.format(list(key.values())[0])
                elif outputPcktType == 'uint8':
                    # byte
                    const_str += '{0:d},'.format(list(key.values())[0])
                elif outputPcktType == 'uchar' or outputPcktType == 'char':
                    # character
                    const_str += '{:},'.format(list(key.values())[0])
                else:
                    # unknown
                    const_str += '{0:3.5f},'.format(key.values()[0])
            else:
                idx_key = -1
                for k ,v in key.items():
                    idx_key += 1
                    outputPcktType = var_fileld_tpyes[idx_key]
                    if outputPcktType == 'uint32' or outputPcktType == 'int32' or \
                    outputPcktType == 'uint16' or outputPcktType == 'int16' or \
                    outputPcktType == 'uint64' or outputPcktType == 'int64':
                        # integers and unsigned integers
                        var_str += '{0:d},'.format(v)
                    elif outputPcktType == 'double':
                        # double
                        var_str += '{0:15.12f},'.format(v)
                    elif outputPcktType == 'float':
                        # print(3) #key + str(2))
                        var_str += '{0:12.8f},'.format(v)
                    elif outputPcktType == 'uint8':
                        # byte
                        var_str += '{0:d},'.format(v)
                    elif outputPcktType == 'uchar' or outputPcktType == 'char':
                        # character
                        var_str += '{:},'.format(v)
                    else:
                        # unknown
                        var_str += '{0:3.5f},'.format(v)

                str = const_str + var_str
                str = str[:-1]
                str = str + '\n'
                self.log_files[packet_type].write(header+str)
                header = ''
                str = ''
                var_str = ''

    def close(self):
        time.sleep(0.1)
        try:
            for packet in self.output_packets:
                self.log_files[packet['name']].close()
        except:
            pass


def main():
    '''main'''
    driver = driver_ins1000.RoverDriver()
    rover_log = RoverLogApp()
    driver.set_app(rover_log)
    while True:
        try:
            driver.reinit()
            driver.find_device()
        except KeyboardInterrupt:  # response for KeyboardInterrupt such as Ctrl+C
            print('User stop this program by KeyboardInterrupt! File:[{0}], Line:[{1}]'.format(__file__, sys._getframe().f_lineno))
            break
        if not driver.start_collection():
            break

if __name__ == '__main__':
    main()
