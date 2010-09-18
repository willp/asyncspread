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

setup_logging(logging.WARNING)
myname1 = 'ExL1-%05d' % (int(time.time()*100) % 1000)
myname2 = 'ExL2-%05d' % (int(time.time()*100) % 1000)
print 'I am', myname1, 'and:', myname2

def got_conn(listener, conn):
    print 'Got connected:', conn
    for g in (':Disc', ':HB', ':Log'):
        conn.join(g)
def got_data(listener, conn, message):
    print '%s>>  %s' % (conn.name, message)
def got_dropped(listener, conn):
    print 'Lost connection to spread server'
    conn.start_connect()
def got_error(listener, conn, exc):
    print 'Got exception/error:', str(exc)
    if 'Connection refused' in exc:
        print 'Connection refused by server... Sleeping 1 seconds...'
        time.sleep(1)

listener = CallbackListener(cb_conn=got_conn, cb_data=got_data, cb_dropped=got_dropped, cb_error=got_error)

host = 'localhost'
port = 24999
if len(sys.argv) > 1:
    host = sys.argv[1]
if len(sys.argv) > 2:
    port = int(sys.argv[2])
sp1 = AsyncSpread(myname1, host, port, listener=listener, start_connect=True)
sp2 = AsyncSpread(myname2, host, port, listener=listener, start_connect=True, map=sp1.map())
print 'SP1 is:', sp1
print 'SP2 is:', sp2
sp1.run(1, 1)
loop=0
while loop < 1000: # sp1.connected or sp2.connected:
    print 'client top of loop'
    loop += 1
    try:
        sp1.multicast([':Log'], 'sp1: my multicast num %d' % (loop), 0)
        sp2.multicast([':Disc'], 'sp2: SECOND connection: multicast num %d' % (loop), 0)
    except:
        print 'Cannot send message... Not connected?'
    sp1.run(timeout=1, count=2)
