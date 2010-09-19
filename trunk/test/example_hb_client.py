#!/usr/bin/env python
import time, sys, logging
sys.path.append('.')
from asyncspread.connection import AsyncSpread
from asyncspread.listeners import CallbackListener, GroupCallback

def setup_logging(level=logging.INFO):
    logger = logging.getLogger()
    logger.setLevel(level)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(asctime)s ()- %(levelname)s - %(message)s'))
    logger.addHandler(ch)

setup_logging(logging.DEBUG)
myname = 'HBcli-%03d' % (int(time.time()*100) % 1000)
print 'I am', myname

(host, port) = ('localhost', 24999)
if len(sys.argv) > 1: host = sys.argv[1]
if len(sys.argv) > 2: port = int(sys.argv[2])

def got_conn(listener, conn):
    print 'Got connected:', conn
def got_dropped(listener, conn):
    print 'Lost connection to spread server on:', conn.name, 'Reconnecting with start_connect()'
    conn.start_connect()
def got_error(listener, conn, exc):
    print 'Got exception/error:', str(exc)
    if 'Connection refused' in exc:
        print 'Connection refused by server... Sleeping 1 seconds...'
        time.sleep(1)

def got_mesg(listener, conn, mesg):
    print '%s>> Got message, type=%4d, sender="%s", message: %s' % (conn.name, mesg.mesg_type, mesg.sender, mesg.data)

listener = CallbackListener(cb_conn=got_conn, cb_dropped=got_dropped, cb_error=got_error, cb_data=got_mesg)

hb_client = AsyncSpread(myname, host, port, listener=listener, start_connect=True)

loop=0
while loop < 10000:
    print '%s: client top of loop %d' % (myname, loop)
    loop += 1
    hb_client.run(10)
    if loop % 5 == 3:
        try:
            hb_client.multicast([':HB'], 'heartbeat ping from client', loop // 10)
        except: print 'cannot send, not connected?'
