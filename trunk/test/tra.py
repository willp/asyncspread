#!/usr/bin/python2.4
import time, sys, logging
sys.path.append('.')
import asyncspread.connection as conn
import asyncspread.listeners as listen


def setup_logging(level=logging.INFO):
    logger = logging.getLogger()
    logger.setLevel(level)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(asctime)s ()- %(levelname)s - %(message)s'))
    logger.addHandler(ch)

def ping_response(success, elapsed):
    print 'Client PING callback: Success: %s.  Elapsed time: %.8f' % (success, elapsed)

setup_logging(logging.INFO)
myname1 = 'tra1-%05d' % (int(time.time()*100) % 1000)
myname2 = 'tra2-%05d' % (int(time.time()*100) % 1000)
print 'I am', myname1, 'and:', myname2

class MyListener(listen.SpreadPingListener):
    def handle_data(self, conn, message):
        print 'Got message:', message
        print 'From connection:', conn

map=dict()
listener = MyListener()
host = 'localhost'
port = 24999
if len(sys.argv) > 1:
    host = sys.argv[1]
if len(sys.argv) > 2:
    port = int(sys.argv[2])
sp1 = conn.AsyncSpread(myname1, host, port, listener=listener, start_connect=True, map=map)
print 'SP1 is:', sp1
sp2 = conn.AsyncSpread(myname2, host, port, listener=listener, start_connect=True, map=map)
sp1.start_connect()
sp2.start_connect()
print 'My map:', map
for g in ('gr1', 'gr2', 'abc123', 'def', 'group2', 'AZ', ''):
    sp1.join(g)
    sp2.join(g)
loop=0
while sp1.connected or sp2.connected:
    loop += 1
    print 'client top of loop'
    sp1.multicast(['gr2', 'AZ'], 'my multicast num %d' % (loop), 0, self_discard=False)
    sp1.multicast([], 'To No groups: my multicast num %d' % (loop), 0, self_discard=False)
    sp2.multicast(['gr2', 'AZ'], 'SECOND connection: multicast num %d' % (loop), 0, self_discard=False)
    listener.ping(sp1, ping_response)
    listener.ping(sp2, ping_response)
    sp1.loop(1)
    if loop > 500:
        sp1.disconnect()
        sp1.loop(100)
        sp2.disconnect()
        sp2.loop(100)
