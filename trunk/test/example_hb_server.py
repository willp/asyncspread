#!/usr/bin/env python
import time, sys, logging
sys.path.append('.')
from asyncspread.connection import AsyncSpread
from asyncspread.listeners import SpreadListener

def setup_logging(level=logging.INFO):
    logger = logging.getLogger()
    logger.setLevel(level)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(asctime)s ()- %(levelname)s - %(message)s'))
    logger.addHandler(ch)

setup_logging(logging.INFO)

class HeartbeatServer(SpreadListener):
    def __init__(self, name):
        SpreadListener.__init__(self)
        self.name = name
        self.hb_count = 0
        print 'I am', myname

    def handle_connected(self, conn):
        print 'Got connected:', conn, '\nJoining the :HB channel...'
        conn.join(':HB')
    def handle_dropped(self, conn):
        print 'Lost connection to spread server on:', conn.name, 'Reconnecting with start_connect()'
        conn.start_connect()
    def handle_error(self, conn, exc):
        print 'Got exception/error:', str(exc)
        if 'Connection refused' in exc:
            print 'Connection refused by server... Sleeping 1 seconds...'
            time.sleep(1)
    def handle_group_join(self, conn, group, member, cause):
        print 'Another HB server joined: "%s" joined. Reason: %s' % (member, cause)
    def handle_group_leave(self, conn, group, member, cause):
        print 'A HB server LEFT: "%s" left. Reason: %s' % (member, cause)
    def handle_data(self, conn, message):
        self.hb_count += 1
        sender = message.sender
        data = message.data
        mtype = message.mesg_type
        print '%s>> HB message, type=%d, sender="%s", message: %s' % (conn.name, mtype, sender, data)
        # and send a response back
        conn.unicast(sender, 'HB Reply:: %d received' % (self.hb_count), mtype)

myname = 'HBsrv-%03d' % (int(time.time()*100) % 1000)
hb_listener = HeartbeatServer(myname)

(host, port) = ('localhost', 24999)
if len(sys.argv) > 1: host = sys.argv[1]
if len(sys.argv) > 2: port = int(sys.argv[2])
hbs = AsyncSpread(myname, host, port, listener=hb_listener, start_connect=True)
print 'hbs is:', hbs

loop=0
while loop < 10000:
    print '%s: client top of loop %d' % (myname, loop)
    loop += 1
    hbs.run(10)
