import struct
import zlib
import logging
from time import sleep
import datetime
import threading

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class NetworkLink():
    def send_packet(self, packet):
        pass


class Application():
    def on_data(self, data):
        pass


class Sender():



    def __init__(self, network, mtu):
        self.network = network
        self.mtu = mtu
        self.current_number = 0
        self.cache = {}
        self.ids = set(range(2000))
        self.rtt = 10
        self.alpha = 0.05

    def on_msg(self, msg):
        number = struct.unpack('I', msg)
        logger.debug('number ACKed {}'.format(number[0]))
        """
        if number[0] < 0:
            logger.debug(self.cache)
            self.cache[-number[0]][1] = 0
            self.network.send_packet(self.cache[-number[0]][0])
            """
        if number[0] in self.cache:
            logger.debug("FREED: %d", number[0])
            sample = self.cache[number[0]][1]
            self.rtt = int(self.alpha * self.rtt + (1-self.alpha)*sample)
            self.cache.pop(number[0])
            self.ids.add(number[0])


    def on_timer_tick(self):
        logger.debug("TICK! Cache size %d", len(self.cache))
        for i in self.cache:
            self.cache[i][1] += 1
            if self.cache[i][1] > 12:
                logger.debug('\033[93m' + "Resending %d" + '\033[0m', i)
                self.network.send_packet(self.cache[i][0])


    def write(self, data):
        data_length = len(data)
        eff_mtu = self.mtu-4-4-4
        i = 0
        total_length = int(data_length/eff_mtu)+1
        logger.debug("total_length %d", total_length)
        while data_length > 0:
            i += 1
            data_length -= eff_mtu
            fragment = data[(i-1)*eff_mtu:(i*eff_mtu)]
            crc = zlib.crc32(fragment)
            number = self.ids.pop()
            logger.debug("Number gone: %d total_length: %d", number, total_length)
            message = struct.pack(('<{}sIII'.format(len(fragment))), fragment, number, total_length, crc)
            self.network.send_packet(message)
            self.cache[number] = [message, 0]

        return True

class Receiver():
    def __init__(self, network, app):
        self.network = network
        self.app = app
        self.cache = {}
        self.num_of_packets_recieved = 0
        self.length = 0
        self.current = 0

    def on_msg(self, msg):

        data, number, total_length, crc = struct.unpack(('<{}sIII'.format(len(msg)-4-4-4)),msg)
        computed_crc = zlib.crc32(data)
        self.length = total_length
        if crc != computed_crc:
            logger.debug('\033[93m' + "NOT Accepting. Corruption %d != %d" + '\033[0m', crc, computed_crc)
            #control = struct.pack('i', -number)
            #self.network.send_packet(control)
        else:
            control = struct.pack('I', number)
            self.network.send_packet(control)
            if total_length > 1:
                self.cache[number] = data
            else:
                self.app.on_data(data)



    def on_timer_tick(self):
        logger.debug("reciever cache size %d, currentPacket %d", len(self.cache), self.current)
        if self.current in self.cache:
            self.app.on_data(self.cache[self.current])
            self.cache.pop(self.current)
            self.current +=1


        #self.network.send_packet(control)
