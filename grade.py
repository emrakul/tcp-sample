import sys
import os
import collections
import random

from reliable_transport import NetworkLink, Sender, Application, Receiver, logger


class SimulatingNetwork():
    class Link(NetworkLink):
        def __init__(self, names, latency, mtu,
                     packet_loss, packet_reorder, corruption):
            self.queue = []
            self.names = names
            self.latency = latency
            self.mtu = mtu
            self.time = 0
            self.receiver = None

            self.random = random.Random(42)
            self.packet_loss = packet_loss
            self.packet_reorder = packet_reorder
            self.corruption = corruption

        def on_timer_tick(self):
            self.time += 1

            while self.queue:
                if self.queue[0][0] > self.time:
                    break

                packet = self.queue.pop(0)[1]
                logger.debug("Delivering packet %s to %s", packet, self.names[1])
                self.receiver.on_msg(packet)

        def send_packet(self, data):
            if type(data) is not bytes:
                raise TypeError("data must be type bytes")

            logger.debug("%s sending packet %s", self.names[0].title(), data)
            if len(data) > self.mtu:
                logger.debug("Packet dropped because it was bigger than mtu")
                return

            if (self.packet_loss is not None and
                self.random.random() < self.packet_loss):
                logger.debug("Packet lost in network")
                return

            if (self.corruption is not None and
                self.random.random() < self.corruption):

                max_position = len(data)
                if self.random.random() > 0.5: # try corrupting header
                    max_position = min(max_position, 16)
                position = self.random.randint(0, max_position - 1)
                bit = self.random.randint(0, 7)

                logger.debug("Packet corrupted at %d bit" % position)

                data = bytearray(data)
                data[position] = data[position] ^ (1 << bit)
                data = bytes(data)

            self.queue.append((
                self.time + self.latency + self.random.randint(0, self.packet_reorder),
                data
            ))
            self.queue.sort()

    def on_timer_tick(self):
        self.sender_link.on_timer_tick()
        self.receiver_link.on_timer_tick()

    def set_sender(self, sender):
        self.receiver_link.receiver = sender

    def set_receiver(self, receiver):
        self.sender_link.receiver = receiver

    def __init__(self, latency, mtu=1500,
                 packet_loss=None, packet_reorder=0, corruption=None):
        self.sender_queue = []
        self.receiver_queue = []
        self.mtu = mtu

        self.sender_link = SimulatingNetwork.Link(
            ["sender", "receiver"], latency, mtu,
            packet_loss, packet_reorder, corruption)
        self.receiver_link = SimulatingNetwork.Link(
            ["receiver", "sender"], latency, mtu,
            packet_loss, packet_reorder, corruption)


CHECK_WAIT = 0
CHECK_FINISH = 1
CHECK_ERROR = 2


class SimpleApplication(Application):
    def __init__(self, data, timeout):
        self.received = b''
        self.time = 0
        self.test_data = b''.join(data)
        self.queued_data = data[:]
        self.timeout = timeout

    def check(self):
        if self.time > self.timeout:
            return CHECK_ERROR, "Timeout! Transfer not finished in %d milliseconds" % self.timeout

        if self.test_data[:len(self.received)] != self.received:
            return CHECK_ERROR, "Data corruption! Data sent: %s. Data received: %s." % (
                self.test_data, self.received)

        if len(self.received) == len(self.test_data):
            return CHECK_FINISH, ""
        else:
            return CHECK_WAIT, ""

    def on_timer_tick(self, sender):
        self.time += 1

        while self.queued_data:
            logger.debug("Application offering %s to sender", self.queued_data[0])
            if sender.write(self.queued_data[0]):
                logger.debug("Sender accepted data")
                self.queued_data.pop(0)
            else:
                logger.debug("Sender rejected data, will try again on next iteration")
                break

    def on_data(self, data):
        if type(data) is not bytes:
            raise TypeError("data must be type bytes")

        logger.debug("Application received %s from receiver", data)

        self.received += data
        return True


TestCase = collections.namedtuple('TestCase', 'name network app')

OKGREEN = '\033[92m'
WARNING = '\033[93m'
FAIL = '\033[91m'
ENDC = '\033[0m'
BOLD = '\033[1m'

def run_simulation(test_cases):
    max_name = 0
    for test in test_cases:
        max_name = max(max_name, len(test.name))

    for test in test_cases:
        print(BOLD, test.name, ".", " " * (max_name - len(test.name)), ENDC, sep="", end="")

        network = test.network
        app = test.app

        sender = Sender(network.sender_link, network.mtu)
        network.set_sender(sender)
        receiver = Receiver(network.receiver_link, app)
        network.set_receiver(receiver)

        time = 0
        while True:
            # advance time
            time += 1
            app.on_timer_tick(sender)
            sender.on_timer_tick()
            receiver.on_timer_tick()
            network.on_timer_tick()

            code, msg = app.check()
            if code == CHECK_WAIT:
                continue
            elif code == CHECK_ERROR:
                print(" ", FAIL, BOLD, "FAIL", ENDC, " ", msg, sep="")
                return
            elif code == CHECK_FINISH:
                print(" ", OKGREEN, BOLD, "OK", ENDC, sep="")
                break


def test_protocol():

    bad_network = [
        TestCase("One byte over network with huge packet loss",
                 SimulatingNetwork(latency=1, packet_loss=0.9),
                 SimpleApplication([b'f'], timeout=1000)),

        TestCase("Network with packet reordering",
                          SimulatingNetwork(mtu=50, latency=20, packet_reorder=10),
                          SimpleApplication([b'test' for _ in range(10)], timeout=1000)),


        TestCase("Network with data corruption",
                 SimulatingNetwork(mtu=50, latency=20, corruption=0.9),
                 SimpleApplication([b'test' for _ in range(10)], timeout=1000)),
        TestCase("Network with small packet loss",
                                  SimulatingNetwork(mtu=100, latency=1, packet_loss=0.05),
                                  SimpleApplication([b'test' for _ in range(10)], timeout=1000)),
    ]

    simple_cases = [
        TestCase("Transfer one byte over reliable network",
                 SimulatingNetwork(latency=0),
                 SimpleApplication([b'f'], timeout=10)),
        TestCase("One kilobyte write",
                 SimulatingNetwork(latency=0),
                 SimpleApplication([b'z' * 100], timeout=10)),
        TestCase("Many small writes",
                 SimulatingNetwork(latency=0),
                 SimpleApplication([b'f' for _ in range(1024)], timeout=10)),
        TestCase("Write bigger than mtu",
                 SimulatingNetwork(latency=0),
                 SimpleApplication([b'f' * 2000], timeout=10)),
    ]


    window_management = [

    ]


    run_simulation(simple_cases  + bad_network)

    print(WARNING + BOLD + "Test suite is incomplete, don't forget to pull latest changes" + ENDC)

if __name__ == "__main__":
    test_protocol()
