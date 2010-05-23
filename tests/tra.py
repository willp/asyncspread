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
myname = 'tra-%06d' % (int(time.time()*100) % 1000)
print 'I am', myname
#
class MyListener(asyncspread.SpreadPingListener):
    def handle_data(self, conn, message):
        print 'Got message:', message

    def handle_timer(self, conn):
        pass

#listener = asyncspread.SpreadPingListener()
listener = MyListener()
sp = asyncspread.AsyncSpread(myname, sys.argv[1], 24999, listener=listener)
sp.start_connect()

for g in ('gr1', 'gr2', 'abc123', 'def', 'group2', 'AZ', ''):
    sp.join(g)
loop=0
while sp.connected:
    loop += 1
    print 'client top of loop'
    sp.multicast(['gr2', 'AZ'], 'my multicast num %d' % (loop), 0, self_discard=False)
    sp.multicast([], 'To No groups: my multicast num %d' % (loop), 0, self_discard=False)
    listener.ping(sp, ping_response)
    sp.loop(50)
    if loop > 500:
        sp.disconnect()
        sp.loop(100)
