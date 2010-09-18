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
myname1 = 'ExL1-%05d' % (int(time.time()*100) % 1000)
myname2 = 'ExL2-%05d' % (int(time.time()*100) % 1000)
print 'I am', myname1, 'and:', myname2

def got_conn(listener, conn):
    print 'Got connected:', conn
    for g in (':Disc', ':HB', ':Log'):
        print 'joining:', g
        conn.join(g)
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
    print 'HB message: %s' % (message)
gcb_hb = GroupCallback(cb_join=hb_join, cb_leave=hb_leave, cb_data=hb_mesg)

def new_hb_listener():
    '''factory style method for returning a new CallbackListener, wired up with generic HB connection callbacks'''
    return CallbackListener(cb_conn=got_conn, cb_dropped=got_dropped, cb_error=got_error)

listener1 = new_hb_listener()
listener2 = new_hb_listener()
for lst in [listener1, listener2]:
    lst.set_group_cb(':HB', gcb_hb)

host = 'localhost'
port = 24999
if len(sys.argv) > 1:
    host = sys.argv[1]
if len(sys.argv) > 2:
    port = int(sys.argv[2])
sp1 = AsyncSpread(myname1, host, port, listener=listener1, start_connect=True)
sp2 = AsyncSpread(myname2, host, port, listener=listener2, start_connect=True, map=sp1.map())
print 'SP1 is:', sp1
print 'SP2 is:', sp2
sp1.run(10)
loop=0
while loop < 1000: # sp1.connected or sp2.connected:
    print 'client top of loop'
    loop += 1
    try:
        sp1.multicast([':HB'], 'sp1: my multicast num %d' % (loop), 0)
        sp2.multicast([':Disc'], 'sp2: SECOND connection: multicast num %d' % (loop), 0)
    except:
        print 'Cannot send message... Not connected?'
    sp1.run(1)
    sp2.run(1)
