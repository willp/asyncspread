#!/usr/bin/python2.6
import time, sys, logging
sys.path.append('.')
import asyncspread

def setup_logging(level=logging.INFO):
    logger = logging.getLogger()
    logger.setLevel(level)
    ch = logging.StreamHandler()
    #ch.setLevel(level)
    ch.setFormatter(logging.Formatter('%(asctime)s ()- %(levelname)s - %(message)s'))
    logger.addHandler(ch)

def ping_response(success, elapsed):
    print 'Client PING callback: Success: %s.  Elapsed time: %.8f' % (success, elapsed)

setup_logging(logging.INFO)
myname1 = 'tra1-%05d' % (int(time.time()*100) % 1000)
myname2 = 'tra2-%05d' % (int(time.time()*100) % 1000)
print 'I am', myname1, 'and:', myname2
#
class MyListener(asyncspread.SpreadPingListener):
    def handle_data(self, conn, message):
        print 'Got message:', message
        print 'From connection:', conn

#    def handle_timer(self, conn):
#        pass

#listener = asyncspread.SpreadPingListener()
map=dict()
listener = MyListener()
sp1 = asyncspread.AsyncSpread(myname1, sys.argv[1], 24999, listener=listener,map=map)
print 'SP1 is:', sp1
sp2 = asyncspread.AsyncSpread(myname2, sys.argv[1], 24999, listener=listener, map=map)
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
    sp1.loop(50)
    sp2.loop(50)
    if loop > 500:
        sp1.disconnect()
        sp1.loop(100)
        sp2.disconnect()
        sp2.loop(100)
