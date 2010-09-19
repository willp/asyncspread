#!/usr/bin/env python
import time, sys, logging
sys.path.append('.')
from asyncspread.connection import AsyncSpread
from asyncspread.listeners import SpreadListener, CallbackListener, GroupCallback

def setup_logging(level=logging.INFO):
    logger = logging.getLogger()
    logger.setLevel(level)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(asctime)s ()- %(levelname)s - %(message)s'))
    logger.addHandler(ch)

def ping_response(success, elapsed):
    print 'Client PING callback: Success: %s.  Elapsed time: %.8f' % (success, elapsed)

setup_logging(logging.INFO)
myname = 'HBsrv-%03d' % (int(time.time()*100) % 1000)
print 'I am', myname

def got_conn(listener, conn):
    print 'Got connected:', conn, '\nJoining the :HB channel...'
    conn.join(':HB')
def got_dropped(listener, conn):
    print 'Lost connection to spread server on:', conn.name, 'Reconnecting...'
    conn.start_connect()
def got_error(listener, conn, exc):
    print 'Got exception/error:', str(exc)
    if 'Connection refused' in exc:
        print 'Connection refused by server... Sleeping 1 seconds...'
        time.sleep(1)

def hb_join(conn, group, member, cause):
    print 'HB join: on group (%s) new member: "%s" joined. Reason: %s' % (group, member, cause)
def hb_leave(conn, group, member, cause):
    print 'HB LEAVE: on group (%s) member: "%s" left. Reason: %s' % (group, member, cause)
def hb_mesg(conn, message):
    print '%s>> HB message: %s' % (conn.name, message)
gcb_hb = GroupCallback(cb_join=hb_join, cb_leave=hb_leave, cb_data=hb_mesg)

listener = CallbackListener(cb_conn=got_conn, cb_dropped=got_dropped, cb_error=got_error)
listener.set_group_cb(':HB', gcb_hb)

(host, port) = ('localhost', 24999)
if len(sys.argv) > 1: host = sys.argv[1]
if len(sys.argv) > 2: port = int(sys.argv[2])
hb_srv = AsyncSpread(myname, host, port, listener=listener, start_connect=True)
print 'hb_srv is:', hb_srv
loop=0
while loop < 1000:
    print 'client top of loop'
    loop += 1
    hb_srv.run(10)
